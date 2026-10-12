"""Real HTTP + Docker restart validation on a prepared runtime copy, without keys."""
import argparse
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True, timeout=60).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runtime', type=Path)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if not runtime.is_relative_to(ROOT / 'data/stage-b') or not (runtime / 'app.sqlite3').is_file():
        raise ValueError('Use a prepared phase B runtime copy')
    name = 'siteco-stage-b-' + uuid4().hex
    checks = []
    try:
        docker('run', '-d', '--name', name, '--pull', 'never', '-p', '127.0.0.1::8000',
               '--mount', f'type=bind,source={runtime},target=/app/runtime',
               'siteco-phase-b-tests', 'python', '-m', 'uvicorn', 'app.main:create_app',
               '--factory', '--app-dir', '/app/backend', '--host', '0.0.0.0', '--port', '8000')
        port = docker('port', name, '8000/tcp').rsplit(':', 1)[1]
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=20) as client:
            def ready():
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    try:
                        if client.get('/api/health').status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    time.sleep(.2)
                raise AssertionError('Probe backend did not become healthy')

            def request(method, path, **kwargs):
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()

            ready()
            migrated = request('GET', '/api/documents')
            manifest = json.loads((runtime.parent / 'backup-receipt.json').read_text(encoding='utf-8'))
            assert len(migrated) + len(request('GET', '/api/trash')) == manifest['original_count']
            assert request('GET', '/api/sessions') == []
            checks.append('old runtime opens; no automatic cross-session association')
            sid = request('POST', '/api/sessions')['session_id']
            other = request('POST', '/api/sessions')['session_id']
            base = f'/api/sessions/{sid}'

            def upload(logical=None):
                params = {'session_id': sid}
                if logical:
                    params['logical_document_id'] = logical
                doc = request('POST', '/api/documents', params=params, files={
                    'file': ('prices.csv', (ROOT / 'test_data/leuchten_siteco_LPR_2026_06.csv').read_bytes())})
                for _ in range(100):
                    status = request('GET', '/api/documents/' + doc['document_id'])
                    if status['status'] in ('ready', 'failed'):
                        break
                    time.sleep(.1)
                assert status['status'] == 'ready', status['error']
                return doc

            first = upload()
            second = upload(first['logical_document_id'])
            source = {'document_id': first['logical_document_id'], 'version_id': first['version_id']}
            assert len(request('GET', base)['sources']) == 2
            state = request('PUT', base + '/rules', json={'expected_rule_version': 0, 'default_sources': [source]})
            snap = request('POST', base + '/snapshots', json={'request_id': 'q1',
                'expected_rule_version': state['rule_version'], 'expected_data_version': state['data_version'],
                'explicit_sources': [source, source]})
            assert snap['scope']['documents'] == [source]
            request('POST', base + '/messages', json={'message_id': 'user-1', 'content': 'Keep this history'})
            assert request('GET', f'/api/sessions/{other}')['sources'] == []
            request('POST', f'/api/sessions/{other}/sources', json={'source': source, 'expected_data_version': 0})
            checks.append('full CSV upload, explicit version lineage, source isolation and duplicate normalization')
            # Trusted graph-side interfaces have no client publication endpoint.
            docker('exec', name, 'python', '-c', '''
import sys
from app.artifacts import ArtifactStore
from app.sessions import SessionStore
from app.agent_protocol import ScopeSnapshot
db='/app/runtime/app.sqlite3'
s=SessionStore(db)
scope=ScopeSnapshot.model_validate(s.read_snapshot(sys.argv[1],sys.argv[2])['scope'], strict=False)
s.append_message(sys.argv[1], 'answer-1', 'assistant', 'Historical answer', scope.documents)
ArtifactStore(db).publish(sys.argv[1], 'table-1', sys.argv[2], kind='table', payload={'rows': [[11386]]}, cache_key='row-count')
''', sid, snap['snapshot_id'])
            docker('restart', name)
            # Docker may reassign an ephemeral host port when restarting.
            port = docker('port', name, '8000/tcp').rsplit(':', 1)[1]
            client.base_url = f'http://127.0.0.1:{port}'
            ready()
            assert len(request('GET', base + '/messages')) == 2
            assert request('GET', base + '/snapshots/' + snap['snapshot_id']) == snap
            assert request('GET', base + '/artifacts/table-1')['source_available']
            checks.append('real container restart preserves session, messages, snapshot and artifact')
            state = request('GET', base)
            request('POST', base + '/sources/remove', json={'source': source, 'expected_data_version': state['data_version']})
            assert request('GET', f'/api/sessions/{other}')['sources'][0]['available']
            assert not request('GET', base + '/artifacts/table-1')['source_available']
            request('POST', '/api/documents/' + first['document_id'] + '/trash')
            assert not request('GET', f'/api/sessions/{other}')['sources'][0]['available']
            request('POST', '/api/documents/' + first['document_id'] + '/restore')
            assert request('GET', f'/api/sessions/{other}')['sources'][0]['available']
            request('POST', '/api/documents/' + first['document_id'] + '/trash')
            request('DELETE', '/api/documents/' + first['document_id'])
            result = request('GET', base + '/artifacts/table-1')
            assert result['invalidated'] and result['payload'] is None
            history = request('GET', base + '/messages')
            assert history[-1]['content'] == 'Historical answer' and not history[-1]['source_available']
            assert not (runtime / 'uploads' / first['document_id']).exists()
            assert request('GET', '/api/documents/' + second['document_id'])['status'] == 'ready'
            checks.append('remove/trash/restore/permanent delete and derived invalidation; old answer retained')
        receipt = {'passed': checks, 'runtime': str(runtime), 'real_models_called': False}
        (runtime.parent / 'http-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt, indent=2))
    finally:
        subprocess.run(['docker', 'rm', '-f', name], check=True, capture_output=True, timeout=30)


if __name__ == '__main__':
    main()
