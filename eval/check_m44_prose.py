"""Bounded prose retrieval comparison. Requires explicit user authorization for live mode.

Uses a new isolated runtime, never an existing application's SQLite. No generation,
automatic retries, provider/model switching, or production configuration changes.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.answers import evidence_context
from app.documents import DocumentService
from app.embeddings import EmbeddingGateway, BudgetScheduler, EmbeddingError, PREFIXES
from app.parsing import parse_document, ParseLimits, PARSER_VERSION
from app.processing import DocumentProcessor
from app.questions import QuestionTools
from app.retrieval.pdf import PdfRetriever
from app.voyage import VoyageProvider, load_token_counter

CASES = ROOT / 'eval/cases/m44_prose_development.json'
PROTOCOL = ROOT / 'eval/m44_prose_protocol.md'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare(counter):
    spec = json.loads(CASES.read_text(encoding='utf-8'))
    assert spec['parser_version'] == PARSER_VERSION
    parsed, summary = {}, {}
    for name, material in spec['materials'].items():
        path = ROOT / material['path']
        assert sha256(path.read_bytes()).hexdigest() == material['sha256']
        document = parse_document(path, 'application/pdf', ParseLimits())
        parsed[name] = document
        batches, used, total = 1, 0, 0
        for e in document.evidence:
            n = counter(PREFIXES['document'] + (e.retrieval_text or e.text)) + 16
            assert n <= 4000
            if used+n > 4000:
                batches += 1
                used = 0
            used += n
            total += n
        summary[name] = {'pages': document.page_count, 'chunks': len(document.evidence),
                         'embedding_batches': batches, 'estimated_embedding_tokens': total,
                         'coverage': document.coverage}
    for case in spec['cases']:
        for gold in case['required']:
            matches = [e for e in parsed[gold['document']].evidence
                       if e.page_number == gold['page'] and ' '.join(gold['anchor'].split()).casefold()
                       in ' '.join((e.retrieval_text or e.text).split()).casefold()]
            assert len(matches) == 1 and matches[0].evidence_id == gold['current_evidence_id']
    assert len(spec['cases']) == 8
    assert sum(v['embedding_batches'] for v in summary.values()) <= 8
    return spec, summary


class Calls:
    def __init__(self, provider, out):
        self.provider, self.out = provider, out
        self.events, self.counts = [], {'document': 0, 'query': 0, 'rerank': 0}
        self.reserved_usd, self.next_at = 0.0, 0.0

    def call(self, kind, texts, operation, *, query=''):
        if self.counts[kind] >= 8:
            raise RuntimeError('Authorized call limit reached')
        # UTF-8 input bytes + overhead are a deliberately conservative token estimate.
        bound = sum(len(t.encode('utf-8'))+512 for t in texts)
        if kind == 'rerank':
            bound += (len(query.encode('utf-8'))+512)*len(texts)
        price = .02 if kind == 'rerank' else .12
        reserved = bound * price / 1_000_000
        if self.reserved_usd + reserved > .10:
            raise RuntimeError('Authorized cost reserve reached')
        waited = max(0, self.next_at-time.monotonic())
        if waited:
            print(json.dumps({'pacing_seconds': round(waited, 2), 'next': kind}), flush=True)
            time.sleep(waited)
        self.reserved_usd += reserved
        self.counts[kind] += 1
        event = {'kind': kind, 'attempt': self.counts[kind], 'items': len(texts),
                 'started_utc': datetime.now(timezone.utc).isoformat(),
                 'pacing_seconds': round(waited, 3), 'reserved_usd': reserved, 'status': 'started'}
        self.events.append(event)
        save(self.out/'calls.json', self.events)
        start = time.monotonic()
        try:
            result = operation()
            event.update(status='ok', usage_tokens=getattr(result, 'total_tokens', None))
            return result
        except Exception as exc:
            event.update(status='failed', error_code=getattr(exc, 'code', type(exc).__name__),
                         http_status=getattr(exc, 'http_status', None))
            # Never persist SDK exception bodies, request headers or key material.
            if isinstance(exc, EmbeddingError):
                raise EmbeddingError(exc.code, retryable=False) from None
            raise RuntimeError('Provider failed: ' + type(exc).__name__) from None
        finally:
            event['service_seconds'] = round(time.monotonic()-start, 3)
            self.next_at = time.monotonic()+20
            save(self.out/'calls.json', self.events)
            print(json.dumps(event, ensure_ascii=True), flush=True)

    def embed(self, texts, **options):
        return self.call(options['input_type'], texts, lambda: self.provider.embed(texts, **options))

    def rerank(self, question, records):
        texts = [r.get('retrieval_text') or r['text'] for r in records]
        return self.call('rerank', texts, lambda: self.provider.client.rerank(
            question, texts, model='rerank-2.5-lite', top_k=None, truncation=False), query=question)


def measured_context(service, request, full, selected):
    class Selected:
        def retrieve(self, *args, **kwargs):
            return {**deepcopy(full), 'records': deepcopy(selected)}
    bundle = QuestionTools(service, Selected()).prepare(request)
    return evidence_context(bundle)


def identities(records):
    return {(r['document_id'], r['evidence_id']) for r in records}


def run(args, spec, preparation):
    out = args.run.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(out/'cases.json', spec)
    (out/'protocol.md').write_bytes(PROTOCOL.read_bytes())
    meta = {'kind': spec['kind'], 'head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'case_sha256': sha256(CASES.read_bytes()).hexdigest(), 'protocol_sha256': sha256(PROTOCOL.read_bytes()).hexdigest(),
            'runner_sha256': sha256(Path(__file__).read_bytes()).hexdigest(), 'preparation': preparation,
            'started_utc': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'cases': []}
    save(out/'run.json', meta)
    service = DocumentService(out/'runtime')
    calls = Calls(VoyageProvider(args.key_file.read_text(encoding='utf-8-sig').strip()), out)
    gateway = EmbeddingGateway(service.database, calls, load_token_counter(args.tokenizer), BudgetScheduler(service.database))
    documents = {}
    try:
        service.start(DocumentProcessor(gateway))
        ingestion_start = time.monotonic()
        for name, material in spec['materials'].items():
            path = ROOT/material['path']
            doc = service.submit(path.name, BytesIO(path.read_bytes()))
            until = time.monotonic()+300
            while True:
                doc = service.get(doc['document_id'])
                if doc['status'] == 'ready':
                    break
                if doc['status'] == 'failed' or time.monotonic() >= until:
                    raise RuntimeError('Document did not become ready: '+name)
                time.sleep(.2)
            documents[name] = doc['document_id']
            print(json.dumps({'ready': name, 'chunks': preparation[name]['chunks']}), flush=True)
        meta['ingestion_seconds'] = round(time.monotonic()-ingestion_start, 3)
        meta['documents'] = documents
        save(out/'run.json', meta)
        retriever = PdfRetriever(service, service.lexical, gateway)
        for case in spec['cases']:
            request = {'conversation_id':'m44-prose', 'question':case['question'],
                       'document_ids':[documents[n] for n in case['documents']]}
            record = {'id':case['id'], 'request':request, 'status':'started'}
            save(out/(case['id']+'.json'), record)
            start = time.monotonic()
            full = retriever.retrieve(case['question'], request['document_ids'], top_k=40)
            records = full['records']
            record.update(candidate_result=full, retrieval_seconds=round(time.monotonic()-start,3))
            save(out/(case['id']+'.json'), record)
            expected = [(documents[g['document']], g['current_evidence_id']) for g in case['required']]
            context_base = measured_context(service, request, full, records[:8])
            record['baseline_context'] = context_base
            save(out/(case['id']+'.json'), record)
            start = time.monotonic()
            ranked = calls.rerank(case['question'], records)
            record['reranking_seconds_including_pacing'] = round(time.monotonic()-start,3)
            order = [r.index for r in ranked.results]
            assert sorted(order) == list(range(len(records))), 'Invalid reranker identity mapping'
            record['rerank_order'] = [{'index':r.index,'score':r.relevance_score} for r in ranked.results]
            reranked = [records[i] for i in order]
            context_ranked = measured_context(service, request, full, reranked[:8])
            record['reranked_context'] = context_ranked
            summary = {'id':case['id'],'required_units':len(expected),'candidate_count':len(records),
                       'candidate_hits':sum(i in identities(records) for i in expected)}
            for label, selected, context in [('baseline',records,context_base),('reranked',reranked,context_ranked)]:
                final_ids = identities(selected[:8])
                context_ids = identities([e['source'] for e in context['evidence']])
                summary[label] = {'final8_hits':sum(i in final_ids for i in expected),
                    'context_hits':sum(i in context_ids for i in expected),
                    'context_complete':all(i in context_ids for i in expected),
                    'context_items':len(context['evidence']), 'omitted':context['omitted_evidence_count'],
                    'required_ranks':[next((n for n,r in enumerate(selected,1) if (r['document_id'],r['evidence_id'])==i),None) for i in expected]}
            summary['rerank_service_seconds'] = calls.events[-1]['service_seconds']
            summary['rerank_pacing_seconds'] = calls.events[-1]['pacing_seconds']
            record.update(status='completed', summary=summary)
            save(out/(case['id']+'.json'), record)
            meta['cases'].append(summary)
            save(out/'run.json',meta)
            print(json.dumps(summary),flush=True)
        meta['status'] = 'completed'
    except Exception as exc:
        meta.update(status='stopped', error_type=type(exc).__name__)
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__}),flush=True)
    finally:
        service.stop()
        meta.update(counts=calls.counts,reserved_cost_usd=calls.reserved_usd,
                    finished_utc=datetime.now(timezone.utc).isoformat())
        save(out/'run.json',meta)
    return meta['status'] == 'completed'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--run',type=Path)
    parser.add_argument('--authorized',action='store_true')
    parser.add_argument('--key-file',type=Path)
    parser.add_argument('--tokenizer',type=Path,required=True)
    args = parser.parse_args()
    spec, preparation = prepare(load_token_counter(args.tokenizer))
    if args.prepare:
        print(json.dumps(preparation,indent=2))
    else:
        if not (args.authorized and args.run and args.key_file):
            parser.error('Live mode requires --authorized, --run (new directory), --key-file and prior user approval')
        sys.exit(0 if run(args,spec,preparation) else 1)
