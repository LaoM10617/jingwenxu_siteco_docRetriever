"""Small real Gemini -> pull worker -> pandas probe in an isolated runtime."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'test_data/leuchten_siteco_LPR_2026_06.csv'


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(10)


def jobs(runtime):
    with closing(sqlite3.connect((runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        return [{'job_id': row[0], 'run_id': row[1], 'status': row[2]}
                for row in db.execute('SELECT job_id,run_id,status FROM execution_jobs ORDER BY created_at')]


def cleanup_worker_containers(work_dir):
    database = work_dir / 'worker.sqlite3'
    if not database.exists():
        return
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        row = db.execute('SELECT owner FROM identity').fetchone()
    if row is None:
        return
    # Only this probe's persisted random worker identity can select containers.
    found = subprocess.run(['docker', 'container', 'ls', '-aq', '--filter',
        'label=siteco.execution.owner=' + row[0]], capture_output=True, timeout=20, check=True)
    for container in found.stdout.decode('ascii').split():
        subprocess.run(['docker', 'rm', '--force', container], capture_output=True, timeout=20, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Pinned pandas runner image ID or digest')
    parser.add_argument('--skip-chart', action='store_true', help='Skip chart reuse; still verify follow-up filtering')
    args = parser.parse_args()
    if not re.fullmatch(r'(?:[a-zA-Z0-9./:_-]+@)?sha256:[a-f0-9]{64}', args.image):
        parser.error('--image must be pinned to sha256')
    target = ROOT / 'data/stage-d' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    runtime, work_dir = target / 'runtime', target / 'worker'
    runtime.mkdir(parents=True)
    original_hash = sha256(SOURCE.read_bytes()).hexdigest()
    receipt = {'runtime': str(runtime), 'source_hash': original_hash, 'image': args.image,
               'runs': [], 'checks': [], 'status': 'started'}
    env = os.environ.copy()
    env.update(DATA_DIR=str(runtime), PYTHONPATH=str(ROOT / 'backend'),
               GENERATION_PROVIDER='gemini', VOYAGE_API_KEY='',
               EXECUTION_IMAGE=args.image, EXECUTION_WORKER_TOKEN=secrets.token_urlsafe(32))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    server = worker = None
    active_run = None
    logs = []
    failure = None

    def start(command, name):
        log = (target / name).open('w', encoding='utf-8')
        logs.append(log)
        return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    try:
        server = start([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory',
                        '--host', '127.0.0.1', '--port', str(port)], 'server.log')
        with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
            deadline = time.monotonic() + 45
            while True:
                try:
                    if client.get('/api/health').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('server_start_failed')
                time.sleep(.2)

            def call(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.is_error:
                    raise RuntimeError(f'http_{response.status_code}')
                return response.json()

            settings = call('GET', '/api/settings')
            receipt['provider'] = settings['generation']['provider']
            receipt['model'] = settings['generation']['profiles']['gemini']['model']
            if receipt['provider'] != 'gemini':
                raise RuntimeError('unexpected_provider')
            worker = start([sys.executable, str(ROOT / 'scripts/run_python_worker.py'),
                            '--backend', base_url, '--work-dir', str(work_dir), '--image', args.image], 'worker.log')
            sid = call('POST', '/api/sessions')['session_id']
            receipt['session_id'] = sid
            base = f'/api/sessions/{sid}'
            with SOURCE.open('rb') as source:
                document = call('POST', '/api/documents', params={'session_id': sid},
                                files={'file': (SOURCE.name, source, 'text/csv')})
            did = document['document_id']
            deadline = time.monotonic() + 60
            while document['status'] != 'ready':
                if document['status'] == 'failed' or time.monotonic() >= deadline:
                    raise RuntimeError('csv_import_failed')
                time.sleep(.2)
                document = call('GET', '/api/documents/' + did)
            receipt['document_id'] = did

            def run(question, request_id):
                nonlocal active_run
                state = call('GET', base)
                body = {'question': question, 'request_id': request_id,
                        'expected_data_version': state['data_version'], 'expected_rule_version': state['rule_version']}
                result = call('POST', base + '/runs', json=body)
                active_run = base + '/runs/' + result['run_id']
                assert call('POST', base + '/runs', json=body)['run_id'] == result['run_id']
                deadline = time.monotonic() + 300
                while result['status'] in ('queued', 'running'):
                    if worker.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('worker_or_run_timeout')
                    time.sleep(.5)
                    result = call('GET', active_run)
                events = call('GET', f'/api/developer/sessions/{sid}/runs/{result["run_id"]}/events')
                calls = [event['payload'] for event in events if event['kind'] == 'model_call']
                receipt['runs'].append({'run_id': result['run_id'], 'status': result['status'],
                    'error_code': (result.get('error') or {}).get('code'), 'model_call_count': len(calls),
                    'phases': [item['node'] for item in calls], 'artifact_ids': result.get('artifact_ids', [])})
                if result['status'] != 'completed':
                    raise RuntimeError('analysis_not_completed')
                active_run = None
                return [call('GET', base + '/artifacts/' + aid) for aid in result['artifact_ids']]

            artifacts = run('请分析当前 CSV 的完整数据，所有记录均计入，不去重、不抽样。Listenpreis 是德国格式金额，'
                '小数分隔符逗号、千位分隔符点，使用 Decimal 求合计。空价格不参与金额求和但记录仍计入总行数，'
                '遇到非空非法金额请报错。单位仅称原始价格单位，不推断货币或税。结果输出两列 metric、value，'
                '恰好两行：metric=records 的 value 为原始总行数；metric=total 的 value 为金额合计。先不要绘图。', 'full-total')
            table = next(item for item in artifacts if item['kind'] == 'table')
            previous_table = table
            payload = table['payload']
            receipt['table'] = {'artifact_id': table['artifact_id'], 'columns': payload['columns'], 'rows': payload['rows']}
            assert payload['columns'] == ['metric', 'value']
            values = dict(payload['rows'])
            assert Decimal(str(values['records'])) == 11386
            assert Decimal(str(values['total'])) == Decimal('9623342.01')
            receipt['checks'].append('real HTTP/Gemini/pull-worker/pandas full-table total matches independent expectation')
            previous_jobs = jobs(runtime)
            assert previous_jobs and any(item['status'] == 'completed' for item in previous_jobs)
            if not args.skip_chart:
                charts = run('请将刚才已有结果表改成柱状图，复用该表原值与口径，不重新计算，不筛选，不转换单位。'
                             '横轴 metric、纵轴 value，标题“CSV 核对结果”。', 'reuse-chart')
                chart = next(item for item in charts if item['kind'] == 'chart')
                chart_payload = chart['payload']
                assert chart_payload['type'] == 'bar'
                linked = call('GET', base + '/artifacts/' + chart_payload['table_artifact_id'])
                previous_table = linked
                assert linked['payload']['rows'] == payload['rows']
                assert jobs(runtime) == previous_jobs
                receipt['chart'] = {'artifact_id': chart['artifact_id'], 'payload': chart_payload}
                receipt['checks'].append('follow-up chart reuses persisted table without another execution job')
            filtered = run('仅在刚才已有结果表上继续筛选，保留 metric 严格等于 total 的行，'
                '仍输出 metric、value 两列，保留原 value 和原单位，不重新聚合原 CSV，不生成图表。', 'filter-prior-result')
            filtered_table = next(item for item in filtered if item['kind'] == 'table')
            filtered_payload = filtered_table['payload']
            assert filtered_payload['columns'] == ['metric', 'value']
            assert len(filtered_payload['rows']) == 1
            assert filtered_payload['rows'][0][0] == 'total'
            assert Decimal(str(filtered_payload['rows'][0][1])) == Decimal('9623342.01')
            calculation = json.loads(filtered_table['calculation'])
            assert any(item['artifact_id'] == previous_table['artifact_id'] for item in calculation['input_artifacts'])
            after_filter_jobs = jobs(runtime)
            old_ids = {item['job_id'] for item in previous_jobs}
            new_jobs = [item for item in after_filter_jobs if item['job_id'] not in old_ids]
            assert new_jobs and any(item['status'] == 'completed' for item in new_jobs)
            assert all(item['run_id'] == receipt['runs'][-1]['run_id'] for item in new_jobs)
            with closing(sqlite3.connect((runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
                for item in new_jobs:
                    job_payload = json.loads(db.execute('SELECT payload FROM execution_jobs WHERE job_id=?',
                        (item['job_id'],)).fetchone()[0])
                    prior_inputs = json.loads(job_payload['inputs']['artifacts.json'])
                    supplied = next(value for value in prior_inputs if value['artifact_id'] == previous_table['artifact_id'])
                    assert supplied['payload']['rows'] == previous_table['payload']['rows']
            receipt['filtered_table'] = {'artifact_id': filtered_table['artifact_id'],
                'columns': filtered_payload['columns'], 'rows': filtered_payload['rows'],
                'input_artifact_id': previous_table['artifact_id'], 'new_execution_jobs': len(new_jobs)}
            receipt['checks'].append('follow-up filtering executes against the complete persisted prior table and preserves total')
            receipt['execution_jobs'] = jobs(runtime)
            receipt['status'] = 'passed'
    except Exception as error:
        failure = type(error).__name__
        receipt['status'] = 'failed'
        receipt['error_type'] = failure
    finally:
        if active_run and server and server.poll() is None:
            try:
                with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
                    client.post(active_run + '/stop')
            except httpx.HTTPError:
                pass
        stop_process(worker)
        try:
            cleanup_worker_containers(work_dir)
        except Exception:
            receipt['cleanup_failed'] = True
            receipt['status'] = 'failed'
            failure = failure or 'WorkerCleanupError'
        finally:
            stop_process(server)
            for log in logs:
                log.close()
        receipt['original_unchanged'] = sha256(SOURCE.read_bytes()).hexdigest() == original_hash
        if not receipt['original_unchanged']:
            receipt['status'] = 'failed'
            failure = failure or 'OriginalChanged'
        (target / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'receipt': str(target / 'receipt.json'), 'status': receipt['status'],
                          'error_type': failure}, ensure_ascii=False))
    return 1 if failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
