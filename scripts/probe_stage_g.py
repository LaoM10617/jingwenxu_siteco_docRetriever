"""Small real HTTP/Gemini/background/pull-worker/pandas acceptance probe.

Uses a new runtime and session. The receipt retains exact output for independent
semantic review; structural assertions are not a proof of arbitrary model code.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time

import httpx

from probe_stage_d_analysis import stop_process, cleanup_worker_containers, jobs

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'test_data/leuchten_siteco_LPR_2026_06.csv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'(?:[a-zA-Z0-9./:_-]+@)?sha256:[a-f0-9]{64}', args.image):
        parser.error('--image must be pinned to sha256')
    target = ROOT / 'data/stage-g' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    runtime, work_dir = target / 'runtime', target / 'worker'
    runtime.mkdir(parents=True)
    original_hash = sha256(SOURCE.read_bytes()).hexdigest()
    receipt = {'status': 'started', 'runtime': str(runtime), 'source_sha256': original_hash,
               'image': args.image, 'checks': [], 'validation': 'real providers and Docker; not a mock'}
    env = os.environ.copy()
    env.update(DATA_DIR=str(runtime), PYTHONPATH=str(ROOT / 'backend'),
               GENERATION_PROVIDER='gemini', VOYAGE_API_KEY='',
               EXECUTION_IMAGE=args.image, EXECUTION_WORKER_TOKEN=secrets.token_urlsafe(32))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    server = worker = None
    logs = []
    active_path = None

    def start(command, name):
        log = (target / name).open('w', encoding='utf-8')
        logs.append(log)
        return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def start_server(name):
        return start([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory',
                      '--host', '127.0.0.1', '--port', str(port)], name)

    def wait_for(check, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = check()
            if value:
                return value
            time.sleep(.25)
        raise RuntimeError('probe_condition_timeout')

    try:
        server = start_server('server.log')
        with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
            def ready():
                try:
                    return client.get('/api/health').status_code == 200
                except httpx.TransportError:
                    return False

            def call(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.is_error:
                    raise RuntimeError(f'http_{response.status_code}_{path}')
                return response.json()

            wait_for(ready)
            settings = call('GET', '/api/settings')
            receipt['provider'] = settings['generation']['provider']
            receipt['model'] = settings['generation']['profiles']['gemini']['model']
            assert receipt['provider'] == 'gemini'
            worker = start([sys.executable, str(ROOT / 'scripts/run_python_worker.py'),
                '--backend', base_url, '--work-dir', str(work_dir), '--image', args.image], 'worker.log')
            sid = call('POST', '/api/sessions')['session_id']
            receipt['session_id'] = sid
            base = f'/api/sessions/{sid}'
            xp = base + '/explorations'
            call('PUT', xp + '/settings', json={'enabled': False})
            with SOURCE.open('rb') as source:
                document = call('POST', '/api/documents', params={'session_id': sid},
                                files={'file': (SOURCE.name, source, 'text/csv')})
            did = document['document_id']
            receipt['source'] = {'document_id': document['logical_document_id'], 'version_id': did}
            def imported():
                state = call('GET', '/api/documents/' + did)
                if state['status'] == 'failed':
                    raise RuntimeError('csv_import_failed')
                return state if state['status'] == 'ready' else None
            imported_document = wait_for(imported)
            assert imported_document['parsing']['record_count'] == 11386
            item = wait_for(lambda: next(iter(call('GET', xp)['items']), None))
            identity = item['exploration_id']
            active_path = xp + '/' + identity
            assert item['status'] == 'disabled' and item['model_calls'] == 0
            assert item['overview']['row_count'] == 11386
            assert len(item['overview']['columns']) == 18
            assert call('GET', base + '/messages') == []
            assert call('GET', base + '/runs') == []
            receipt['disabled_overview'] = item
            receipt['checks'].append('disabled import produces full 11386-row/18-column overview with zero model calls and no chat')
            call('PUT', xp + '/settings', json={'enabled': True})
            def finished():
                value = call('GET', active_path)
                return value if value['status'] not in ('queued', 'running', 'disabled') else None
            item = wait_for(finished, 300)
            receipt['exploration'] = item
            receipt['developer'] = call('GET', f'/api/developer/sessions/{sid}/explorations/{identity}')
            assert item['status'] in ('completed', 'partial'), item['status']
            computed = [c for c in item['candidates'] if c['state'] == 'computed']
            assert len(computed) == 1 and len(item['candidates']) <= 3
            assert 1 <= item['model_calls'] <= 3 and 1 <= item['execution_calls'] <= 2
            assert all(c['state'] == 'suggested' for c in item['candidates'][1:])
            artifacts = [call('GET', base + '/artifacts/' + aid) for aid in computed[0]['artifact_ids']]
            receipt['artifacts'] = artifacts
            table = next(a for a in artifacts if a['kind'] == 'table')
            assert call('GET', base + '/messages') == []
            assert call('GET', base + '/runs') == []
            assert call('GET', base)['focus'] is None
            receipt['checks'].append('one bounded real precomputation with suggestions separate; no automatic chat or focus publication')
            before_jobs = jobs(runtime)
            assert before_jobs and any(j['status'] == 'completed' for j in before_jobs)
            # Selection changes focus only. The existing artifact cache checks the
            # exact accepted version/scope before returning the persisted data.
            receipt['selection'] = call('POST', active_path + '/select', json={'artifact_id': table['artifact_id']})
            assert receipt['selection']['focus']['reference_id'] == table['artifact_id']
            session = call('GET', base)
            snapshot = call('POST', base + '/snapshots', json={
                'request_id': 'probe-exact-reuse', 'expected_data_version': session['data_version'],
                'expected_rule_version': session['rule_version'], 'explicit_sources': [receipt['source']]})
            reused = call('POST', base + '/artifacts/' + table['artifact_id'] + '/reuse',
                          json={'snapshot_id': snapshot['snapshot_id']})
            assert reused['payload'] == table['payload']
            call('POST', active_path + '/resume')
            assert jobs(runtime) == before_jobs
            assert call('GET', base + '/messages') == []
            receipt['checks'].append('selection and exact-scope persisted artifact reuse add no chat, model call or computation')
            other = call('POST', '/api/sessions')['session_id']
            other_base = f'/api/sessions/{other}'
            call('PUT', other_base + '/explorations/settings', json={'enabled': False})
            assert client.get(other_base + '/explorations/' + identity).status_code == 404
            assert client.get(other_base + '/artifacts/' + table['artifact_id']).status_code == 404
            receipt['checks'].append('cross-session exploration and artifact identity access denied')
            # Restart the API using the SAME directory; completed work stays idle.
            stop_process(server)
            server = start_server('server-restart.log')
            wait_for(ready)
            restarted = call('GET', active_path)
            assert restarted['model_calls'] == item['model_calls']
            assert restarted['execution_calls'] == item['execution_calls']
            assert restarted['candidates'] == item['candidates']
            assert jobs(runtime) == before_jobs
            receipt['checks'].append('API process restart preserves completed results and lifetime budgets without rerunning')
            # Remove just this association, then verify invalidated publication.
            session = call('GET', base)
            call('POST', base + '/sources/remove', json={
                'source': receipt['source'], 'expected_data_version': session['data_version']})
            invalidated = call('GET', active_path)
            assert invalidated['status'] == 'invalidated'
            assert invalidated['candidates'] == []
            assert client.post(active_path + '/select', json={'artifact_id': table['artifact_id']}).status_code == 409
            stale = call('GET', base + '/artifacts/' + table['artifact_id'])
            assert stale['invalidated'] and stale['payload'] is None
            receipt['invalidation'] = invalidated
            receipt['checks'].append('session source removal invalidates exploration and clears cached payload; selection denied')
            receipt['execution_jobs_before_invalidation'] = before_jobs
            receipt['status'] = 'passed'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['error_type'] = type(error).__name__
        # Our own labels are safe; provider/script exception text is not echoed.
        if isinstance(error, RuntimeError):
            receipt['probe_error'] = str(error)
    finally:
        if active_path and server and server.poll() is None:
            try:
                with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
                    client.post(active_path + '/stop')
            except httpx.HTTPError:
                pass
        stop_process(worker)
        try:
            cleanup_worker_containers(work_dir)
        except Exception:
            receipt['cleanup_failed'] = True
            receipt['status'] = 'failed'
        finally:
            stop_process(server)
            for log in logs:
                log.close()
        receipt['original_unchanged'] = sha256(SOURCE.read_bytes()).hexdigest() == original_hash
        if not receipt['original_unchanged']:
            receipt['status'] = 'failed'
        (target / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'receipt': str(target / 'receipt.json'), 'status': receipt['status'],
                          'error_type': receipt.get('error_type')}, ensure_ascii=False))
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
