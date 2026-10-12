"""Two small real-provider PDF runs in a new runtime; never modifies source PDFs."""
from base64 import b64decode
import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import shutil
import sqlite3
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / 'test_data/Brochures/Indoor Lightening' / name for name in (
    'SIT_Teaser_Flyer_Apollon_21_V_25-386_EN_RZ_web.pdf',
    'SIT_Teaser-Flyer_Silica_21_Prismatic_EN.pdf')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-runtime', type=Path,
                        help='Read-only copy of an existing Stage E probe runtime to avoid repeating embeddings')
    parser.add_argument('--topic-only', action='store_true', help='Only repeat the comparison after a synthesis fix')
    args = parser.parse_args()
    target = ROOT / 'data/stage-e' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    runtime = target / 'runtime'
    runtime.mkdir(parents=True)
    if args.reuse_runtime:
        source_runtime = args.reuse_runtime.resolve()
        if not source_runtime.is_relative_to((ROOT / 'data/stage-e').resolve()):
            parser.error('--reuse-runtime must be inside data/stage-e')
        with closing(sqlite3.connect((source_runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as source_db:
            stored_sources = source_db.execute('SELECT stored_name,content_hash FROM documents').fetchall()
            with closing(sqlite3.connect(runtime / 'app.sqlite3')) as destination_db:
                source_db.backup(destination_db)
        shutil.copytree(source_runtime / 'uploads', runtime / 'uploads')
        for name, expected in stored_sources:
            copy = (runtime / 'uploads' / name).resolve()
            assert copy.parent == (runtime / 'uploads').resolve()
            assert sha256(copy.read_bytes()).hexdigest() == expected
    # Reuse only pinned public infrastructure, never the old runtime's documents/state.
    tokenizer = (ROOT / 'data/docker-e2e/tokenizers/voyage-4-tokenizer.json').read_bytes()
    assert sha256(tokenizer).hexdigest() == 'c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539'
    (runtime / 'tokenizers').mkdir()
    (runtime / 'tokenizers/voyage-4-tokenizer.json').write_bytes(tokenizer)
    hashes = {str(path): sha256(path.read_bytes()).hexdigest() for path in SOURCES}
    receipt = {'runtime': str(runtime), 'source_hashes': hashes, 'runs': [], 'status': 'started',
               'independent_expectations': {'Apollon page 4': 'up to 180 lm/W; 100,000 h L80; IP54 version 165 lm/W',
                    'Silica page 4': 'up to 180 lm/W; up to 100,000 h L85 at Tmax'}}
    receipt['reused_index_runtime'] = str(args.reuse_runtime) if args.reuse_runtime else None
    env = os.environ.copy()
    env.update(DATA_DIR=str(runtime), PYTHONPATH=str(ROOT / 'backend'), GENERATION_PROVIDER='gemini')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    log = (target / 'server.log').open('w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:create_app', '--factory',
        '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    active = None
    try:
        with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
            deadline = time.monotonic() + 45
            while True:
                try:
                    if client.get('/api/health').status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if process.poll() is not None or time.monotonic() >= deadline:
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
            receipt['embedding'] = settings['embedding']['model']
            assert receipt['provider'] == 'gemini'
            sid = call('POST', '/api/sessions')['session_id']
            receipt['session_id'] = sid
            base = f'/api/sessions/{sid}'
            documents = []

            def upload(path):
                if args.reuse_runtime:
                    document = next(d for d in call('GET', '/api/documents')
                                    if d['original_filename'] == path.name and d['status'] == 'ready')
                    version = call('GET', '/api/document-versions/' + document['document_id'])
                    state = call('GET', base)
                    call('POST', base + '/sources', json={
                        'source': {k: version[k] for k in ('document_id', 'version_id')},
                        'expected_data_version': state['data_version']})
                    documents.append(document)
                    receipt['documents'] = documents
                    return
                with path.open('rb') as source:
                    document = call('POST', '/api/documents', params={'session_id': sid},
                                    files={'file': (path.name, source, 'application/pdf')})
                did = document['document_id']
                deadline = time.monotonic() + 180
                while document['status'] != 'ready':
                    if document['status'] == 'failed' or time.monotonic() >= deadline:
                        raise RuntimeError('ingestion_failed_or_timeout')
                    time.sleep(.5)
                    document = call('GET', '/api/documents/' + did)
                documents.append(document)
                receipt['documents'] = documents

            def run(question, request_id, expected_mode):
                nonlocal active
                state = call('GET', base)
                body = {'question': question, 'request_id': request_id,
                        'expected_data_version': state['data_version'], 'expected_rule_version': state['rule_version']}
                result = call('POST', base + '/runs', json=body)
                active = base + '/runs/' + result['run_id']
                assert call('POST', base + '/runs', json=body)['run_id'] == result['run_id']
                deadline = time.monotonic() + 300
                while result['status'] in ('queued', 'running'):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('run_timeout')
                    time.sleep(.5)
                    result = call('GET', active)
                events = call('GET', f'/api/developer/sessions/{sid}/runs/{result["run_id"]}/events')
                calls = [event['payload'] for event in events if event['kind'] == 'model_call']
                with closing(sqlite3.connect((runtime / 'app.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
                    tasks = [{'task': json.loads(t), 'result': json.loads(r)} for t, r in db.execute(
                        'SELECT task,result FROM conversation_tasks WHERE run_id=?', (result['run_id'],))]
                item = {'run': result, 'model_calls': calls, 'tasks': tasks, 'previews': []}
                receipt['runs'].append(item)
                assert len(calls) <= 6
                assert result['status'] in ('completed', 'partial'), result['status']
                assert tasks and all(t['task'].get('pdf_mode') == expected_mode for t in tasks)
                coverage = [c for t in tasks for c in t['result']['coverage']]
                assert {c['source']['version_id'] for c in coverage} == {d['document_id'] for d in documents}
                assert any(c['processed'] for c in coverage)
                for task in tasks:
                    if any(c['omitted'] for c in task['result']['coverage']):
                        assert task['result']['status'] == 'partial'
                        assert task['result']['gaps']
                citations = result['answer']['citations']
                assert citations
                assert {c['document_id'] for c in citations} == {d['document_id'] for d in documents}
                seen = set()
                for citation in citations:
                    did, page = citation['document_id'], citation['locator']['page_number']
                    assert 1 <= page <= 4
                    if (did, page) in seen:
                        continue
                    seen.add((did, page))
                    preview = call('GET', f'/api/documents/{did}/evidence/{citation["evidence_id"]}/preview')
                    assert preview['page_number'] == page and preview['kind'] == 'pdf'
                    image = target / f'{request_id}-{did}-page{page}.png'
                    image.write_bytes(b64decode(preview['image'].split(',', 1)[1]))
                    item['previews'].append({'document_id': did, 'page': page, 'path': str(image),
                                             'regions': preview['regions'], 'notice': preview['notice']})
                active = None

            upload(SOURCES[0])
            if not args.topic_only:
                run('Read the complete Apollon 21 PDF, not just search matches. Summarize every page in English, '
                    'covering product concept, mounting, variants and technical specifications. Cite original pages; '
                    'explicitly report any unread pages or insufficient coverage.', 'full-summary', 'coverage')
            upload(SOURCES[1])
            run('Compare BOTH complete Apollon 21 and Silica 21 Prismatic PDFs on luminous efficacy and service life. '
                'Keep product variants and lifetime L80/L85/CLO/Tmax qualifications distinct. Cite both documents '
                'and their original pages. State topic coverage and any unreviewed material; do not assume equal '
                'service-life definitions merely because the hour figures match.', 'topic-comparison', 'topic')
            assert sum(len(item['model_calls']) for item in receipt['runs']) <= (5 if args.topic_only else 9)
            receipt['status'] = 'passed_automated_checks_pending_visual_and_semantic_review'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['error_type'] = type(error).__name__
        # Our RuntimeError messages are local fixed codes, not provider diagnostics.
        if isinstance(error, RuntimeError):
            receipt['error_code'] = str(error)
    finally:
        if active and process.poll() is None:
            try:
                with httpx.Client(base_url=base_url, timeout=10, trust_env=False) as client:
                    client.post(active + '/stop')
            except httpx.HTTPError:
                pass
        process.terminate()
        try:
            process.wait(15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(10)
        log.close()
        receipt['originals_unchanged'] = all(sha256(Path(path).read_bytes()).hexdigest() == value
                                           for path, value in hashes.items())
        if not receipt['originals_unchanged']:
            receipt['status'] = 'failed_original_hash'
        (target / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'receipt': str(target / 'receipt.json'), 'status': receipt['status']}))
    return 1 if receipt['status'].startswith('failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
