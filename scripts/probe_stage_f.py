"""Small real-provider long conversation, dependent PDF/CSV and worker probe.

Prices are explicitly synthetic fixtures, not SITECO commercial information.
The original PDF and existing deployments are never modified.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import httpx

from probe_stage_d_analysis import stop_process, cleanup_worker_containers, jobs

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / 'test_data/Brochures/Indoor Lightening/SITECO_Rondel_21_Product_Flyer.pdf'
EXPECTED = {'0MD5307L1830', '0MD5307L0930'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--reuse-runtime', type=Path, help='Read-only source/index copy from a prior stage-f probe')
    parser.add_argument('--continue-session', help='Explicitly continue this copied probe session, preserving prior receipts')
    args = parser.parse_args()
    if args.continue_session and not args.reuse_runtime:
        parser.error('--continue-session requires --reuse-runtime')
    target = ROOT / 'data/stage-f' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    runtime, work = target / 'runtime', target / 'worker'
    runtime.mkdir(parents=True)
    if args.reuse_runtime:
        source_runtime = args.reuse_runtime.resolve()
        if not source_runtime.is_relative_to((ROOT / 'data/stage-f').resolve()):
            parser.error('--reuse-runtime must be inside data/stage-f')
        with closing(sqlite3.connect((source_runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as source_db:
            with closing(sqlite3.connect(runtime / 'app.sqlite3')) as destination_db:
                source_db.backup(destination_db)
        shutil.copytree(source_runtime / 'uploads', runtime / 'uploads')
        if args.continue_session:
            with closing(sqlite3.connect((source_runtime / 'conversation-checkpoints.sqlite3').as_uri() + '?mode=ro', uri=True)) as source_db:
                with closing(sqlite3.connect(runtime / 'conversation-checkpoints.sqlite3')) as destination_db:
                    source_db.backup(destination_db)
    (runtime / 'tokenizers').mkdir()
    tokenizer = (ROOT / 'data/docker-e2e/tokenizers/voyage-4-tokenizer.json').read_bytes()
    assert sha256(tokenizer).hexdigest() == 'c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539'
    (runtime / 'tokenizers/voyage-4-tokenizer.json').write_bytes(tokenizer)
    original_hash = sha256(PDF.read_bytes()).hexdigest()
    receipt = {'status': 'started', 'runtime': str(runtime), 'source_hash': original_hash,
               'price_data': 'Synthetic verification fixture; not actual SITECO pricing', 'runs': [], 'checks': []}
    receipt['continued_from'] = str(args.reuse_runtime) if args.continue_session else None
    env = os.environ.copy()
    env.update(DATA_DIR=str(runtime), PYTHONPATH=str(ROOT / 'backend'), GENERATION_PROVIDER='gemini',
               EXECUTION_IMAGE=args.image, EXECUTION_WORKER_TOKEN=secrets.token_urlsafe(32))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    server = worker = None
    logs, active = [], None

    def start(command, name):
        log = (target / name).open('w', encoding='utf-8')
        logs.append(log)
        return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def start_server(name):
        return start([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory',
                      '--host', '127.0.0.1', '--port', str(port)], name)

    try:
        server = start_server('server.log')
        with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
            def healthy():
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        if client.get('/api/health').status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    if server.poll() is not None:
                        break
                    time.sleep(.2)
                raise RuntimeError('server_start_failed')

            def call(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.is_error:
                    raise RuntimeError(f'http_{response.status_code}')
                return response.json()

            healthy()
            settings = call('GET', '/api/settings')
            receipt.update(provider=settings['generation']['provider'],
                model=settings['generation']['profiles']['gemini']['model'], embedding=settings['embedding']['model'])
            worker = start([sys.executable, str(ROOT / 'scripts/run_python_worker.py'),
                '--backend', url, '--work-dir', str(work), '--image', args.image], 'worker.log')
            sid = args.continue_session or call('POST', '/api/sessions')['session_id']
            receipt['session_id'] = sid
            base = '/api/sessions/' + sid

            def upload(name, content, media):
                prior = next((d for d in call('GET', '/api/documents')
                              if d['original_filename'] == name and d['status'] == 'ready'), None)
                if prior:
                    version = call('GET', '/api/document-versions/' + prior['document_id'])
                    state = call('GET', base)
                    if not any(s['version_id'] == version['version_id'] for s in state['sources']):
                        call('POST', base + '/sources', json={'source': {k: version[k] for k in ('document_id', 'version_id')},
                             'expected_data_version': state['data_version']})
                    return prior
                doc = call('POST', '/api/documents', params={'session_id': sid}, files={'file': (name, content, media)})
                deadline = time.monotonic() + 180
                while doc['status'] != 'ready':
                    if doc['status'] == 'failed' or time.monotonic() >= deadline:
                        raise RuntimeError('ingestion_failed')
                    time.sleep(.3)
                    doc = call('GET', '/api/documents/' + doc['document_id'])
                return doc

            def capture(result):
                events = call('GET', f'/api/developer/sessions/{sid}/runs/{result["run_id"]}/events')
                with closing(sqlite3.connect((runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
                    tasks = [{'task': json.loads(t), 'result': json.loads(r)} for t, r in db.execute(
                        'SELECT task,result FROM conversation_tasks WHERE run_id=?', (result['run_id'],))]
                calls = [e['payload'] for e in events if e['kind'] == 'model_call']
                receipt['runs'].append({'run': result, 'model_calls': calls, 'tasks': tasks})
                # Clarification replies have their own bounded user-authorized attempt.
                retries = [e['payload']['model_call_baseline'] for e in events
                           if e['kind'] in ('retry', 'clarification_round') and 'model_call_baseline' in e['payload']]
                baselines = [0, *retries, len(calls)]
                assert all(b-a <= 6 for a,b in zip(baselines, baselines[1:]))

            def wait(result):
                nonlocal active
                active = base + '/runs/' + result['run_id']
                deadline = time.monotonic() + 300
                while result['status'] in ('queued', 'running'):
                    if time.monotonic() >= deadline or worker.poll() is not None:
                        raise RuntimeError('run_timeout')
                    time.sleep(.3)
                    result = call('GET', active)
                return result

            def run(question, name, *, waiting=False):
                nonlocal active
                prior = next((r for r in call('GET', base + '/runs') if r['request_id'] == name), None)
                if prior:
                    if waiting and prior.get('clarification') and prior['status'] in ('waiting', 'stopped'):
                        capture(prior)
                        return prior
                    if prior['status'] not in ('completed', 'waiting'):
                        prior = wait(call('POST', base + '/runs/' + prior['run_id'] + '/resume', json={}))
                    capture(prior)
                    assert prior['status'] == ('waiting' if waiting else 'completed'), prior.get('error')
                    active = None
                    return prior
                state = call('GET', base)
                body = {'request_id': name, 'question': question, 'expected_data_version': state['data_version'],
                        'expected_rule_version': state['rule_version']}
                result = call('POST', base + '/runs', json=body)
                assert call('POST', base + '/runs', json=body)['run_id'] == result['run_id']
                result = wait(result)
                capture(result)
                assert result['status'] == ('waiting' if waiting else 'completed'), result.get('error')
                active = None
                return result

            def table(result):
                tables = [a for a in result['artifacts'] if a['kind'] == 'table']
                assert tables
                return call('GET', base + '/artifacts/' + tables[0]['artifact_id'])

            def prices(value, expected):
                payload = value['payload']
                assert payload['columns'] == ['Order No.', 'Price']
                found = {r[0]: Decimal(str(r[1])) for r in payload['rows']}
                assert found == {key: Decimal(amount) for key, amount in expected.items()}, found

            pdf = upload(PDF.name, PDF.read_bytes(), 'application/pdf')
            old = upload('verification_prices_C.csv',
                b'Order No.;Price\n0MD5307L1830;150.00\n0MD5307L0930;250.00\n0MD5307L1840;50.00\n0MD5307L0940;60.00\n', 'text/csv')
            receipt['documents'] = [pdf, old]
            run('本会话请用中文回答。我的项目代号是蓝桥，后续提到项目代号时请沿用；这不是文件中的产品事实。', 'preference')
            initial = run('请先从 Rondel PDF 的订单变体中找出色温 3000 K、ON/OFF 的全部产品编号，'
                '再用这些编号精确连接 verification_prices_C.csv 的 Order No. 列查询价格。不要按编号猜色温。'
                '这次是报价用途，PDF说明用途是产品说明。Price 是点小数，无缺失，不推断货币，单位称测试价格单位。'
                '结果表恰好两列 Order No.、Price；编号保持原始字符串和前导零。说明产品依据并引用。', 'dependent')
            first = table(initial)
            prices(first, {'0MD5307L1830': '150.00', '0MD5307L0930': '250.00'})
            assert initial['answer']['citations']
            receipt['checks'].append('PDF-selected 3000 K identifiers match original page; exact synthetic C prices and leading zeros')
            filtered = run('只在刚才已有结果表上筛选 Price 小于 200 的行，保留两列和原单位，不从原CSV重新选品。', 'filter')
            prices(table(filtered), {'0MD5307L1830': '150.00'})
            previous_jobs = jobs(runtime)
            chart = run('把刚才筛选结果直接改为柱状图，横轴 Order No. 纵轴 Price，保持数据、口径和单位，不重算。', 'chart')
            assert any(a['kind'] == 'chart' for a in chart['artifacts'])
            assert jobs(runtime) == previous_jobs
            new = upload('verification_prices_D.csv',
                b'Order No.;Price\n0MD5307L1830;175.00\n0MD5307L0930;225.00\n0MD5307L1840;55.00\n0MD5307L0940;65.00\n', 'text/csv')
            receipt['documents'].append(new)
            run('后续报价只用 verification_prices_D.csv；产品说明继续用 Rondel PDF。只更新这两个用途规则，不计算。', 'new-price-rule')
            updated = run('更新最初的 3000 K、ON/OFF 产品报价比较（不是小于200的筛选表）：'
                '复用已验证的同一组选品证据，按新的报价用途查价。仍输出 Order No.、Price 两列和测试价格单位，'
                '点小数无缺失，编号精确连接。不再用旧价目表。', 'update')
            updated_table = table(updated)
            prices(updated_table, {'0MD5307L1830': '175.00', '0MD5307L0930': '225.00'})
            deps = {d['version_id'] for d in updated_table['scope']['documents']}
            assert new['document_id'] in deps and old['document_id'] not in deps and pdf['document_id'] in deps
            run('谢谢。这一轮无需分析文件，只确认你收到了。', 'ack')
            paused = run('下一步请先问我想按哪一列排序，等待我的回答；暂时不要执行排序。', 'clarify-sort', waiting=True)
            count_before = len(receipt['runs'])
            stop_process(server)
            server = start_server('server-restarted.log')
            healthy()
            reopened = call('GET', base + '/runs/' + paused['run_id'])
            assert reopened['status'] in ('waiting', 'stopped') and reopened['clarification']
            assert len(receipt['runs']) == count_before
            resumed = wait(call('POST', base + '/runs/' + paused['run_id'] + '/resume',
                               json={'reply': '按 Price 升序，针对更新后两行报价表，保持原列、原单位和全部行。'}))
            capture(resumed)
            assert resumed['status'] == 'completed'
            prices(table(resumed), {'0MD5307L1830': '175.00', '0MD5307L0930': '225.00'})
            final = run('我在最早一轮指定的项目代号是什么？这是我的交互偏好，不是文档事实；只回答代号。', 'long-memory')
            assert '蓝桥' in ' '.join(s['text'] for s in final['answer']['segments'])
            with closing(sqlite3.connect((runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
                summaries = db.execute('SELECT summary,through_message_id FROM conversation_summaries WHERE session_id=?', (sid,)).fetchall()
            assert summaries
            receipt['summaries'] = [{'summary': json.loads(s), 'through_message_id': mid} for s,mid in summaries]
            receipt['checks'].extend(['filter/chart use persisted complete results', 'new price purpose excludes C and preserves PDF dependency',
                'waiting clarification survives server restart and only explicit reply executes', 'more than six turns with persisted summary recalls initial preference'])
            receipt['status'] = 'passed'
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__)
    finally:
        if active and server and server.poll() is None:
            try:
                with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
                    client.post(active + '/stop')
            except httpx.HTTPError:
                pass
        stop_process(worker)
        try:
            cleanup_worker_containers(work)
        except Exception:
            receipt.update(status='failed', cleanup_failed=True)
        stop_process(server)
        for log in logs:
            log.close()
        receipt['original_unchanged'] = sha256(PDF.read_bytes()).hexdigest() == original_hash
        (target / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'receipt': str(target / 'receipt.json'), 'status': receipt['status']}, ensure_ascii=True))
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
