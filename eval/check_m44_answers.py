"""Authorized P03 paired generation from frozen retrieval records; no retrieval API calls."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.answers import AnswerService, ANSWER, Draft, evidence_context
from app.documents import DocumentService
from app.generation import StructuredModel
from app.questions import QuestionTools


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main(args):
    source = args.source
    original = source.read_bytes()
    record = json.loads(original)
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    save(out/'protocol.json', {'source_sha256': sha256(original).hexdigest(),
         'script_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
         'prompt_sha256': sha256(ANSWER.encode()).hexdigest(),
         'model': 'gemini-3.5-flash-lite', 'order': [args.arm],
         'max_calls': 1, 'retries': 0, 'retrieval_calls': 0,
         'checks': ['two months and legitimate-interest/AGG exception', 'onlyfy up to six months',
                    'separate sections, no invented section number', 'citation semantic support'],
         'scope': 'One paired development check, no production adoption or benchmark'})
    documents = DocumentService(source.parent/'runtime')
    documents.start()  # Restore local published evidence before citation validation.
    model = StructuredModel(SimpleNamespace(generation_provider='gemini',
        gemini_generation_model='gemini-3.5-flash-lite',
        gemini_api_key=SecretStr(args.key_file.read_text(encoding='utf-8-sig').strip())))
    full = record['candidate_result']
    results = []
    try:
        for arm in (args.arm,):
            rows = full['records']
            if arm == 'reranked':
                rows = [rows[r['index']] for r in record['rerank_order']]
            class Selected:
                def retrieve(self, *a, **kw):
                    return {**deepcopy(full), 'records': deepcopy(rows[:8])}
            tools = QuestionTools(documents, Selected())
            expected = record[arm+'_context']
            assert evidence_context(tools.prepare(record['request'])) == expected
            for e in expected['evidence']:
                src = e['source']
                current = documents.read_evidence_id(src['document_id'], src['evidence_id'])
                assert all(current.get(k) == src.get(k) for k in ('text', 'locator', 'raw_values', 'context', 'source_spans'))
            state = {'arm': arm, 'status': 'prepared', 'calls': 0}
            save(out/(arm+'.json'), state)
            class Once:
                provider, model = 'gemini', 'gemini-3.5-flash-lite'
                def generate(self, system, payload, schema, budget):
                    assert state['calls'] == 0, 'No additional calls authorized'
                    assert system == ANSWER and schema == Draft.model_json_schema()
                    assert payload == {'phase': 'answer', 'bundle': expected}
                    state.update(calls=1, status='started')
                    save(out/(arm+'.json'), state)
                    start = time.monotonic()
                    try:
                        raw = model.generate(system, payload, schema, budget)
                        state['raw'] = raw
                        return raw
                    finally:
                        state['generation_seconds'] = round(time.monotonic()-start, 3)
                        save(out/(arm+'.json'), state)
            answer = AnswerService(tools, Once()).answer(record['request'])
            state.update(status='completed', answer=answer)
            save(out/(arm+'.json'), state)
            results.append({'arm': arm, 'seconds': state['generation_seconds'],
                            'outcome': answer['outcome'], 'validation': answer['validation']})
            print(json.dumps(results[-1]), flush=True)
        save(out/'result.json', {'status': 'completed', 'results': results})
    except Exception as exc:
        save(out/'result.json', {'status': 'stopped', 'results': results,
             'error_code': getattr(exc, 'code', type(exc).__name__)})
        print(json.dumps({'status': 'stopped', 'error_code': getattr(exc, 'code', type(exc).__name__)}), flush=True)
        return 1
    finally:
        documents.stop()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--authorized', action='store_true')
    parser.add_argument('--arm', choices=['baseline', 'reranked'], required=True)
    args = parser.parse_args()
    if not args.authorized:
        parser.error('Explicit user authorization is required')
    sys.exit(main(args))
