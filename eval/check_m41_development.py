"""Run the fixed M4.1 development cases serially through the existing task API.
Requires explicit outbound authorization; no POST retries or production changes.
"""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DOCS = {'terms': 'f1338ce4cdc44f7d82e1ce5232e590ef',
        'rondel': '7758b95074074557b8bd2a4b72ef4237',
        'prices': 'eeb7e731107d4759b3dd1d84f0c870ab'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--authorized', action='store_true', required=True)
    args = parser.parse_args()
    args.run.mkdir(parents=True, exist_ok=False)
    base = 'http://127.0.0.1:18094/api'
    docker = Path(os.environ['LOCALAPPDATA']) / 'Programs/DockerDesktop/resources/bin/docker.exe'
    case_file = ROOT / 'eval/cases/m41_development.json'
    raw = case_file.read_bytes()
    (args.run / 'cases.json').write_bytes(raw)
    metadata = {'kind': 'development_not_benchmark', 'case_sha256': sha256(raw).hexdigest(),
                'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'started_utc': datetime.now(timezone.utc).isoformat(),
                'ingestion': 'existing ready documents; no new ingestion measured',
                'poll_seconds': 1, 'document_ids': DOCS}
    (args.run / 'run.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')

    def get(path):
        with urllib.request.urlopen(base + path, timeout=15) as response:
            return json.load(response)

    documents = get('/documents')
    assert all(any(d['document_id'] == identity and d['status'] == 'ready' for d in documents)
               for identity in DOCS.values())
    (args.run / 'documents.json').write_text(json.dumps(documents, indent=2), encoding='utf-8')
    results = {}
    for case in json.loads(raw)['cases']:
        parent = results.get(case.get('parent'))
        if case.get('parent') and (not parent or parent.get('task', {}).get('status') != 'completed'):
            (args.run / (case['id'] + '.json')).write_text(json.dumps({'case': case, 'skipped': 'parent not completed'}), encoding='utf-8')
            continue
        body = {'conversation_id': parent['request']['conversation_id'] if parent else uuid4().hex,
                'request_id': uuid4().hex, 'question': case['question'],
                'document_ids': [DOCS[name] for name in case['documents']]}
        if parent:
            body['previous_question_id'] = parent['task']['question_id']
        record = {'case': case, 'request': body, 'started_utc': datetime.now(timezone.utc).isoformat(), 'observed_stages': []}
        output = args.run / (case['id'] + '.json')
        def save():
            output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        save()  # Preserve the exact request before the only POST attempt.
        start = time.monotonic()
        try:
            request = urllib.request.Request(base + '/questions', data=json.dumps(body).encode(),
                                             headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=20) as response:
                task = json.load(response)
            record['question_id'] = task['question_id']
            save()
            while True:
                elapsed = round(time.monotonic() - start, 3)
                if not record['observed_stages'] or record['observed_stages'][-1]['stage'] != task['stage']:
                    record['observed_stages'].append({'stage': task['stage'], 'observed_seconds': elapsed})
                if task['status'] in ('completed', 'failed'):
                    break
                if elapsed > 260:
                    raise TimeoutError('Observation exceeded 260s; do not POST again')
                time.sleep(1)
                task = get('/questions/' + task['question_id'] + '?conversation_id=' + body['conversation_id'])
            record.update(task=task, elapsed_seconds=elapsed)
        except Exception as exc:
            record['client_error'] = type(exc).__name__  # No potentially sensitive exception payload.
        record['ended_utc'] = datetime.now(timezone.utc).isoformat()
        logs = subprocess.run([str(docker), 'logs', '--timestamps', '--since', record['started_utc'],
                               '--until', record['ended_utc'], 'siteco-m28-smoke-backend-1'],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
        # Provider log statements contain metadata only; never dump environment or SDK payloads.
        record['provider_events'] = [line for line in (logs.stdout + logs.stderr).splitlines()
                                     if 'generation provider=' in line or 'embedding type=' in line]
        record['provider_log_exit_code'] = logs.returncode
        save()
        results[case['id']] = record
        answer = record.get('task', {}).get('answer') or {}
        print(json.dumps({'case': case['id'], 'seconds': record.get('elapsed_seconds'),
                          'status': record.get('task', {}).get('status'), 'outcome': answer.get('outcome'),
                          'client_error': record.get('client_error')}, ensure_ascii=True), flush=True)
        if record.get('client_error') or record.get('task', {}).get('status') == 'failed':
            break  # No automatic retry, quota loop, or provider switch.
        if case['id'] != 'M41-09-cache':
            time.sleep(20)


if __name__ == '__main__':
    main()
