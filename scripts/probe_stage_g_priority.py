"""Real HTTP/host-worker/Docker priority and cancellation probe; scripted model.

The model is deliberately controlled so a long computation is observable before
preemption. This proves runtime behavior, not real-provider planning quality.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from probe_stage_d_analysis import stop_process, cleanup_worker_containers
from probe_stage_d_worker_recovery import containers, running_container


def serve(port):
    import uvicorn
    from app.main import create_app

    class Model:
        provider, model = 'controlled', 'priority-probe'

        def generate(self, system, payload, schema, budget):
            phase = payload['phase']
            if phase == 'csv_candidates':
                return {'candidates': [{'title': 'Count all rows', 'objective': 'Count all rows including blanks; unit rows.'}]}
            if phase == 'csv_plan':
                return {'action': 'compute', 'clarification': None, 'operations': ['aggregate'],
                    'filters': [], 'group_by': [], 'aggregations': ['row count'], 'joins': [],
                    'null_policy': 'count all rows', 'numeric_formats': [], 'unit': 'rows',
                    'assumptions': [], 'reuse_artifact_id': None, 'chart': None,
                    'script': 'import time\nimport pandas as pd\nfrom siteco_analysis import load_tables, emit\ntime.sleep(20)\ntables = load_tables()\nemit(pd.DataFrame({"rows": [len(next(iter(tables.values())))]}))'}
            if phase == 'intent':
                return {'route': 'direct', 'objective': 'Acknowledge greeting', 'direct_answer': 'Hello.'}
            raise RuntimeError('unexpected_probe_phase')

    uvicorn.run(create_app(model=Model()), host='127.0.0.1', port=port)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image')
    parser.add_argument('--serve', type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve)
        return 0
    if not args.image:
        parser.error('--image is required')
    target = ROOT / 'data/stage-g' / ('priority-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    runtime, work_dir = target / 'runtime', target / 'worker'
    runtime.mkdir(parents=True)
    env = os.environ.copy()
    env.update(DATA_DIR=str(runtime), PYTHONPATH=str(ROOT / 'backend'),
        GEMINI_API_KEY='', GROQ_API_KEY='', VOYAGE_API_KEY='',
        EXECUTION_IMAGE=args.image, EXECUTION_WORKER_TOKEN=secrets.token_urlsafe(32))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    receipt = {'status': 'started', 'model': 'scripted; no provider calls', 'image': args.image, 'cases': []}
    processes, logs = [], []

    def start(command, name):
        log = (target / name).open('w', encoding='utf-8')
        logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        processes.append(process)
        return process

    def wait(check, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            time.sleep(.1)
        raise RuntimeError('priority_probe_timeout')

    try:
        start([sys.executable, __file__, '--serve', str(port)], 'server.log')
        with httpx.Client(base_url=url, timeout=10, trust_env=False) as client:
            def ready():
                try:
                    return client.get('/api/health').status_code == 200
                except httpx.TransportError:
                    return False
            wait(ready)
            start([sys.executable, str(ROOT / 'scripts/run_python_worker.py'),
                   '--backend', url, '--work-dir', str(work_dir), '--image', args.image], 'worker.log')
            def worker_owner():
                if not (work_dir / 'worker.sqlite3').exists():
                    return None
                with closing(sqlite3.connect((work_dir / 'worker.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
                    try:
                        row = db.execute('SELECT owner FROM identity').fetchone()
                    except sqlite3.OperationalError:
                        return None
                    return row[0] if row else None
            owner = wait(worker_owner)
            def call(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
            for action in ('foreground', 'stop', 'delete_source'):
                sid = call('POST', '/api/sessions')['session_id']
                base = f'/api/sessions/{sid}'
                doc = call('POST', '/api/documents', params={'session_id': sid},
                           files={'file': (f'{action}.csv', f'id,value\n001,{action}\n002,2\n'.encode(), 'text/csv')})
                item = wait(lambda: next(iter(call('GET', base + '/explorations')['items']), None))
                path = base + '/explorations/' + item['exploration_id']
                container = wait(lambda: running_container(owner))
                started = time.monotonic()
                if action == 'foreground':
                    state = call('GET', base)
                    run = call('POST', base + '/runs', json={'request_id': 'priority', 'question': 'Hello',
                        'expected_data_version': state['data_version'], 'expected_rule_version': state['rule_version']})
                    def foreground_done():
                        value = call('GET', base + '/runs/' + run['run_id'])
                        return value if value['status'] == 'completed' else None
                    done = wait(foreground_done, 10)
                    latency = time.monotonic() - started
                    assert latency < 10
                    assert done['answer'] is not None
                elif action == 'stop':
                    call('POST', path + '/stop')
                else:
                    call('POST', '/api/documents/' + doc['document_id'] + '/trash')
                    call('DELETE', '/api/documents/' + doc['document_id'])
                wait(lambda: not containers(owner), 15)
                state = call('GET', path)
                assert state['status'] == ('invalidated' if action == 'delete_source' else 'stopped')
                assert all(c['state'] != 'computed' for c in state['candidates'])
                if action != 'foreground':
                    assert call('GET', base + '/messages') == []
                receipt['cases'].append({'action': action, 'status': 'passed', 'container_confirmed_running': container,
                    'cleanup_seconds': time.monotonic()-started, 'exploration': state,
                    'foreground_seconds': latency if action == 'foreground' else None})
            receipt['status'] = 'passed'
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__)
    finally:
        for process in reversed(processes):
            stop_process(process)
        try:
            cleanup_worker_containers(work_dir)
        except Exception:
            receipt.update(status='failed', cleanup_failed=True)
        for log in logs:
            log.close()
        path = target / 'receipt.json'
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'receipt': str(path), 'status': receipt['status']}))
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
