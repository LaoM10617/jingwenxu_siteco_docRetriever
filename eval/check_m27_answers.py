"""Opt-in, serial development-only generation; owns an isolated runtime database."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from app.answers import AnswerService
from app.config import Settings
from app.documents import DocumentError, DocumentService
from app.embeddings import EmbeddingError
from app.generation import StructuredModel
from app.processing import DocumentProcessor
from app.questions import QuestionTools
from app.retrieval.pdf import PdfRetriever
from app.voyage import configured_gateway


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=['gemini', 'groq'], required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--voyage-key-file', type=Path)
    parser.add_argument('--tokenizer', type=Path)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=['D01', 'D06', 'D09'], required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    # Never point this helper at a serving runtime or open its SQLite externally.
    # Each acceptance invocation gets a new directory; cached restore is a separate test.
    if runtime.exists():
        raise SystemExit('Use a new isolated runtime directory.')
    runtime.mkdir(parents=True)
    if args.tokenizer:
        (runtime / 'tokenizers').mkdir()
        shutil.copyfile(args.tokenizer, runtime / 'tokenizers/voyage-4-tokenizer.json')
    settings = Settings(_env_file=None, data_dir=runtime, generation_provider=args.provider,
        **{args.provider + '_api_key': args.key_file.read_text(encoding='utf-8-sig').strip()},
        voyage_api_key=args.voyage_key_file.read_text(encoding='utf-8-sig').strip() if args.voyage_key_file else None)
    events = []
    class RecordedModel(StructuredModel):
        def generate(self, system, payload, schema, budget):
            start = time.monotonic()
            event = {'phase': payload['phase'], 'started': start}
            try:
                result = super().generate(system, payload, schema, budget)
                event['status'] = 'ok'
                event['response'] = result
                return result
            except DocumentError as exc:
                event['status'] = exc.code
                raise
            finally:
                event['seconds'] = round(time.monotonic() - start, 3)
                events.append(event)
    gateway = configured_gateway(settings)
    embedding_calls = []
    if gateway:
        original = gateway.provider.embed
        def embed(*values, **options):
            start = time.monotonic()
            event = {'started': start, 'input_type': options['input_type']}
            try:
                response = original(*values, **options)
                event.update(status='ok', tokens=response.total_tokens)
                return response
            except EmbeddingError as exc:
                event.update(status=exc.code, retry_after=exc.retry_after)
                raise
            finally:
                event['seconds'] = round(time.monotonic() - start, 3)
                embedding_calls.append(event)
        gateway.provider.embed = embed
    model = RecordedModel(settings)
    service = DocumentService(runtime)
    service.start(DocumentProcessor(gateway))
    records = []
    try:
        manifest = json.loads((ROOT / 'eval/material_manifest.json').read_text(encoding='utf-8'))
        cases = {c['id']: c for c in json.loads((ROOT / 'eval/cases/m1_questions.json').read_text(encoding='utf-8'))
                 if c['id'] in args.cases and c['split'] == 'development'}
        for case_id in args.cases:
            case = cases[case_id]
            start = time.monotonic()
            selected = []
            for name in case['allowed_documents']:
                entry = manifest[name]
                path = ROOT / entry['path']
                raw = path.read_bytes()
                if sha256(raw).hexdigest() != entry['sha256']:
                    raise RuntimeError('Material hash mismatch')
                document_id = service.submit(path.name, BytesIO(raw))['document_id']
                deadline = time.monotonic() + 240
                last_state = None
                while time.monotonic() < deadline:
                    document = service.get(document_id)
                    state = (document['status'], document.get('stage'))
                    if state != last_state:
                        print(json.dumps({'case': case_id, 'document_state': state}), flush=True)
                        last_state = state
                    if document['status'] in ('ready', 'failed'):
                        break
                    time.sleep(.1)
                if document['status'] != 'ready':
                    records.append({'case': case_id, 'error': 'acceptance_ingestion_failed',
                                    'document_error': document.get('error'), 'last_state': last_state})
                    raise DocumentError('acceptance_ingestion_failed', 'Development document did not become ready.', 503)
                selected.append(document_id)
            ready_seconds = time.monotonic() - start
            question_start = time.monotonic()
            try:
                answer = AnswerService(QuestionTools(service, PdfRetriever(service, service.lexical, gateway)), model).answer(
                    {'conversation_id': 'development-' + case_id, 'question': case['question'], 'document_ids': selected},
                    on_wait=lambda: print(json.dumps({'case': case_id, 'stage': 'waiting_rate_limit'}), flush=True))
                records.append({'case': case_id, 'question': case['question'], 'answer': answer,
                                'upload_to_ready_seconds': round(ready_seconds, 3),
                                'answer_seconds': round(time.monotonic() - question_start, 3)})
                print(json.dumps({'case': case_id, 'outcome': answer['outcome'], 'segments': answer['segments'],
                                  'gaps': answer['gaps']}, ensure_ascii=True), flush=True)
            except DocumentError as exc:
                records.append({'case': case_id, 'error': exc.code})
                print(json.dumps({'case': case_id, 'error': exc.code}), flush=True)
                break  # No quota/error loop or silent provider switch.
    finally:
        service.stop()
        report = {'provider': model.provider, 'model': model.model, 'cases': records,
                  'generation_calls': events, 'embedding_calls': embedding_calls}
        (runtime / 'answer-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if len(records) == len(args.cases) and all(
        r.get('answer', {}).get('outcome') in ('answered', 'partial')
        and r['answer']['segments'] and r['answer']['citations'] for r in records) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (DocumentError, OSError, ValueError, RuntimeError) as exc:
        print('Acceptance failed: ' + (exc.code if isinstance(exc, DocumentError) else type(exc).__name__))
        raise SystemExit(1) from None
