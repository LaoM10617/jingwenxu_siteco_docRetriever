"""M5.0 A+B runner. Live mode is opt-in; runtime and results must be new directories."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from threading import Lock
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
LIMITS = {'generation':32, 'document':72, 'query':42, 'rerank':7}
CASE_LIMITS = dict(zip([f'E{i:02}' for i in range(1,13)], [2,2,2,3,4,3,3,3,3,2,2,3]))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def append(path, value):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False)+'\n')


class LimitReached(RuntimeError):
    pass


class Ledger:
    def __init__(self, out):
        self.out, self.case = out, 'ingestion'
        self.counts = {k:0 for k in LIMITS}
        self.per_case, self.batches = {}, {'document':{}, 'query':{}}
        self.reserve, self.halted, self.lock = 0., False, Lock()

    def call(self, kind, tokens, operation, *, signature=None):
        cap = 50000 if kind == 'generation' else 160000 if kind == 'rerank' else 4000
        cost = (tokens*.30+6000*2.50)/1e6 if kind == 'generation' else tokens*(.02 if kind=='rerank' else .06)/1e6
        with self.lock:
            if kind not in LIMITS or self.halted or tokens>cap or tokens<0 or self.counts[kind]>=LIMITS[kind] or self.reserve+cost>2:
                self.halted=True
                raise LimitReached('Approved request/input/cost limit')
            if kind == 'generation' and self.per_case.get(self.case,0)>=CASE_LIMITS.get(self.case,0):
                self.halted=True
                raise LimitReached('Approved per-case generation limit')
            if kind in self.batches:
                seen=self.batches[kind]; maximum=24 if kind=='document' else 14
                if signature is None or (signature not in seen and len(seen)>=maximum) or seen.get(signature,0)>=3:
                    self.halted=True
                    raise LimitReached('Approved logical batch/attempt limit')
                seen[signature]=seen.get(signature,0)+1
            self.counts[kind]+=1
            if kind=='generation': self.per_case[self.case]=self.per_case.get(self.case,0)+1
            self.reserve+=cost
            event={'case':self.case,'kind':kind,'attempt':self.counts[kind], 'started_utc':datetime.now(timezone.utc).isoformat(),
                   'input_token_bound':tokens,'reserved_usd':cost,'status':'started'}
            append(self.out/'attempts.jsonl',event)
        start=time.monotonic()
        try:
            result=operation()
            event.update(status='ok', usage_tokens=getattr(result,'total_tokens',None))
            return result
        except Exception as exc:
            code=getattr(exc,'code',type(exc).__name__)
            event.update(status='failed',error_code=code)
            if 'authentication' in str(code).lower() or type(exc).__name__=='AuthenticationError': self.halted=True
            raise
        finally:
            event['seconds']=round(time.monotonic()-start,4)
            with self.lock: append(self.out/'attempts.jsonl',event)
            print(json.dumps({k:event[k] for k in ['case','kind','attempt','status','seconds']}),flush=True)


def prepare(args):
    from app.parsing import parse_document, ParseLimits, PARSER_VERSION
    from app.embeddings import PREFIXES
    from app.voyage import load_token_counter
    spec=json.loads((ROOT/'eval/cases/m50_protocol.json').read_text('utf-8'))
    counter=load_token_counter(args.tokenizer)
    subprocess.run(['git','diff','--exit-code',spec['product_commit'],'--','backend/app','backend/requirements.lock.txt'],cwd=ROOT,check=True,capture_output=True)
    summary={}
    for name,material in spec['materials'].items():
        path=ROOT/material['path']
        if sha256(path.read_bytes()).hexdigest()!=material['sha256']: raise ValueError('Material hash mismatch: '+name)
        if path.suffix=='.csv':
            import csv
            with path.open(encoding='utf-8-sig',newline='') as stream: count=sum(1 for _ in csv.DictReader(stream,delimiter=';'))
            assert count==11386
            summary[name]={'records':count}; continue
        parsed=parse_document(path,'application/pdf',ParseLimits())
        batches,used,total=0,0,0
        unique=list(dict.fromkeys(e.retrieval_text or e.text for e in parsed.evidence))
        for text in unique:
            n=counter(PREFIXES['document']+text)+16
            if n>4000: raise ValueError('Oversized embedding chunk')
            if used and used+n>4000: batches+=1; used=0
            used+=n; total+=n
        batches+=bool(used)
        summary[name]={'pages':parsed.page_count,'chunks':len(parsed.evidence),'batches':batches,'tokens':total,'coverage':parsed.coverage}
    if sum(x.get('batches',0) for x in summary.values())>24: raise LimitReached('Document batches exceed approval')
    return spec,counter,summary


class ObservedEmbedding:
    def __init__(self, provider, ledger, counter):
        self.provider,self.ledger,self.counter=provider,ledger,counter
    def embed(self,texts,**options):
        from app.embeddings import PREFIXES
        kind=options['input_type']
        tokens=sum(self.counter(PREFIXES[kind]+t)+16 for t in texts)
        signature=sha256(json.dumps([kind,texts],ensure_ascii=False).encode()).hexdigest()
        return self.ledger.call(kind,tokens,lambda:self.provider.embed(texts,**options),signature=signature)


class ObservedModel:
    provider,model='gemini','gemini-3.5-flash-lite'
    def __init__(self,settings,ledger): self.settings,self.ledger=settings,ledger
    def generate(self,system,payload,schema,budget):
        import httpx
        from app.generation import StructuredModel,wire_schema
        request={'system':system,'payload':payload,'schema':wire_schema(schema)}
        bound=len(json.dumps(request,ensure_ascii=False).encode('utf-8'))+2048
        ledger=self.ledger
        record={'case':ledger.case,**request,'input_bound_method':'utf8_bytes_plus_2048','input_bound':bound}
        usage={}
        class Capture(httpx.HTTPTransport):
            def handle_request(self,req):
                response=super().handle_request(req)
                response.read()
                try: usage.update(response.json().get('usageMetadata') or {})
                except (ValueError,TypeError): pass
                return response
        def operation():
            append(ledger.out/'generation.jsonl',{'event':'request',**record})
            result=StructuredModel(self.settings,transport=Capture()).generate(system,payload,schema,budget)
            append(ledger.out/'generation.jsonl',{'event':'response','case':ledger.case,'phase':payload['phase'],'raw':result,'usage':usage or None})
            return result
        return ledger.call('generation',bound,operation)


class ObservedRetriever:
    def __init__(self,retriever,ledger): self.retriever,self.ledger=retriever,ledger
    def retrieve(self,question,document_ids,**kwargs):
        start=time.monotonic(); before=self.ledger.counts['query']
        result=self.retriever.retrieve(question,document_ids,**kwargs)
        append(self.ledger.out/'retrieval.jsonl',{'case':self.ledger.case,'arm':'end_to_end','query':question,'result':result,
               'seconds':time.monotonic()-start,'embedding_attempts':self.ledger.counts['query']-before,
               'cache':'hit' if before==self.ledger.counts['query'] else 'miss'})
        return result


def context_for(service,query,ids,result,rows):
    from app.questions import QuestionTools
    from app.answers import evidence_context
    class Selected:
        def retrieve(self,*a,**kw): return {**deepcopy(result),'records':deepcopy(rows)}
    return evidence_context(QuestionTools(service,Selected()).prepare({'conversation_id':'isolated-retrieval','question':query,'document_ids':ids}))


def run(args,spec,counter,preparation):
    from pydantic import SecretStr
    from app.answers import AnswerService,ANSWER,PLAN
    from app.memory import RESOLVE
    from app.documents import DocumentService
    from app.processing import DocumentProcessor
    from app.embeddings import EmbeddingGateway,BudgetScheduler
    from app.voyage import VoyageProvider
    from app.retrieval.pdf import PdfRetriever
    from app.questions import QuestionTools
    from app.question_tasks import QuestionTasks
    from app.reranking import Reranker
    out=args.output.resolve(); runtime=args.runtime.resolve()
    if out.exists() or runtime.exists(): raise ValueError('Use new output and runtime paths; no overwrite/resume')
    out.mkdir(parents=True); runtime.mkdir(parents=True)
    ledger=Ledger(out); service=DocumentService(runtime); tasks=None
    save(out/'cases.json',spec)
    (out/'protocol.md').write_bytes((ROOT/'docs/m50-evaluation-protocol.md').read_bytes())
    meta={'status':'running','started_utc':datetime.now(timezone.utc).isoformat(),'product_commit':spec['product_commit'],
          'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'runner_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'case_sha256':sha256((ROOT/'eval/cases/m50_protocol.json').read_bytes()).hexdigest(),
          'protocol_sha256':sha256((out/'protocol.md').read_bytes()).hexdigest(),'preparation':preparation,'blocks':['A','B'],'C':'not_authorized',
          'config':{'generation':'gemini-3.5-flash-lite','embedding':'voyage-4','dimensions':1024,'top_k':8,'rrf_k':60,'candidates_per_route':20,
          'evidence_chars':28000,'embedding_rpm':60,'embedding_tpm':200000,'embedding_min_interval':1,'rerank_min_interval':1,
          'reranker':'rerank-2.5-lite','rerank_budget_seconds':5,'generation_output_limit':6000,'temperature':'provider_default','seed':'not_set'},
          'prompt_hashes':{k:sha256(v.encode()).hexdigest() for k,v in [('ANSWER',ANSWER),('PLAN',PLAN),('RESOLVE',RESOLVE)]},
          'measurement_scope':'frozen backend service/task chain; not HTTP/browser latency', 'runtime_reused':False}
    save(out/'manifest.json',meta)
    try:
        provider=VoyageProvider(args.voyage_key.read_text('utf-8-sig').strip())
        gateway=EmbeddingGateway(service.database,ObservedEmbedding(provider,ledger,counter),counter,
                                 BudgetScheduler(service.database,rpm=60,tpm=200000,min_interval=1))
        service.start(DocumentProcessor(gateway)); documents={}
        for name,material in spec['materials'].items():
            ledger.case='ingest:'+name; start=time.monotonic(); path=ROOT/material['path']
            doc=service.submit(path.name,BytesIO(path.read_bytes()))
            while doc['status'] not in ('ready','failed'):
                if time.monotonic()-start>600: raise TimeoutError('Ingestion deadline')
                time.sleep(.1); doc=service.get(doc['document_id'])
            append(out/'ingestion.jsonl',{'material':name,'document':doc,'seconds':time.monotonic()-start})
            if doc['status']!='ready' or ledger.halted: raise RuntimeError('Ingestion failed')
            documents[name]=doc['document_id']; print(json.dumps({'ready':name}),flush=True)
        meta['documents']=documents; save(out/'manifest.json',meta)
        retriever=PdfRetriever(service,service.lexical,gateway)
        fixed={}
        for case in spec['cases']:
            if not case['pdf_evidence_units']: continue
            ledger.case=case['id']; query=case['question']
            if case['id']=='E04': query+='\nResolved conversational subjects (not evidence): 0MD5307L0940'
            ids=[documents[n] for n in case['allowed_documents'] if n!='prices']
            start=time.monotonic(); full=retriever.retrieve(query,ids,top_k=40)
            candidates=full['records']
            arms={'lexical':sorted([r for r in candidates if r['lexical_rank']],key=lambda r:r['lexical_rank'])[:8],
                  'vector':sorted([r for r in candidates if r['semantic_rank']],key=lambda r:r['semantic_rank'])[:8], 'rrf':candidates[:8]}
            entry={'case':case['id'],'query':query,'scope':ids,'candidate_result':full,'seconds':time.monotonic()-start,
                   'arms':{arm:{'records':rows,'context':context_for(service,query,ids,full,rows)} for arm,rows in arms.items()}}
            fixed[case['id']]=entry; append(out/'retrieval.jsonl',{'arm':'fixed',**entry})
        settings=SimpleNamespace(generation_provider='gemini',gemini_generation_model='gemini-3.5-flash-lite',
                 gemini_api_key=SecretStr(args.gemini_key.read_text('utf-8-sig').strip()))
        answers=AnswerService(QuestionTools(service,ObservedRetriever(retriever,ledger)),ObservedModel(settings,ledger))
        answers.config_snapshot=meta['config']
        tasks=QuestionTasks(service.database,answers); results={}
        for case in spec['cases']:
            ledger.case=case['id']; parent=results.get(case['parent'])
            if case['parent'] and (not parent or parent['status']!='completed'):
                append(out/'answers.jsonl',{'case':case['id'],'status':'dependent_blocked'}); continue
            request={'conversation_id':parent['conversation_id'] if parent else 'm50-'+case['id'],
                     'request_id':case['id'],'question':case['question'],'document_ids':[documents[n] for n in case['allowed_documents']]}
            if parent: request['previous_question_id']=parent['question_id']
            start=time.monotonic(); stages=[]; task=tasks.submit(request)
            while True:
                if not stages or stages[-1]['stage']!=task['stage']: stages.append({'stage':task['stage'],'observed_seconds':time.monotonic()-start})
                if task['status'] in ('completed','failed'): break
                if time.monotonic()-start>250: raise TimeoutError('Question observation deadline')
                time.sleep(.1); task=tasks.get(task['question_id'],request['conversation_id'])
            results[case['id']]=task
            append(out/'answers.jsonl',{'case':case['id'],'request':request,'task':task,'seconds':time.monotonic()-start,'stages':stages})
            print(json.dumps({'case':case['id'],'status':task['status'],'outcome':(task.get('answer') or {}).get('outcome')}),flush=True)
            if ledger.halted: raise LimitReached('Provider halted')
        tasks.stop(); tasks=None
        def rank_call(question,texts,timeout):
            import voyageai
            tokens=counter(question)*len(texts)+sum(counter(t) for t in texts)
            def operation():
                client=voyageai.Client(api_key=args.voyage_key.read_text('utf-8-sig').strip(),max_retries=0,timeout=timeout)
                return client.rerank(question,texts,model='rerank-2.5-lite',top_k=None,truncation=False)
            response=ledger.call('rerank',tokens,operation)
            return [r.index for r in response.results]
        reranker=Reranker(rank_call,min_interval=1)
        for case_id,entry in fixed.items():
            ledger.case=case_id; full=entry['candidate_result']; rows,info=reranker.rank(entry['query'],full['records'])
            append(out/'retrieval.jsonl',{'case':case_id,'arm':'rerank','info':info,
                   'candidate_sha256':sha256(json.dumps(full['records'],sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
                   'records':rows[:8],'context':context_for(service,entry['query'],entry['scope'],full,rows[:8])})
            if ledger.halted: raise LimitReached('Provider halted')
            time.sleep(1.1)
        meta['status']='completed'
    except Exception as exc:
        meta.update(status='stopped',error_code=getattr(exc,'code',type(exc).__name__))
        print(json.dumps({'status':'stopped','error_code':meta['error_code']}),flush=True)
    finally:
        if tasks is not None: tasks.stop()
        service.stop()
        meta.update(finished_utc=datetime.now(timezone.utc).isoformat(),counts=ledger.counts,
                    logical_batches={k:len(v) for k,v in ledger.batches.items()},reserved_cost_usd=ledger.reserve,
                    actual_cost_usd=None,cost_note='conservative reserve; not invoice; usage where available in generation/attempt logs')
        save(out/'manifest.json',meta)
    return 0 if meta['status']=='completed' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--authorized-a-b',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--tokenizer',type=Path,required=True)
    parser.add_argument('--gemini-key',type=Path,default=ROOT/'Gemini_API_KEY.txt')
    parser.add_argument('--voyage-key',type=Path,default=ROOT/'voyage.txt')
    args=parser.parse_args()
    spec,counter,preparation=prepare(args)
    if args.prepare: print(json.dumps(preparation,indent=2))
    else:
        if not (args.authorized_a_b and args.output and args.runtime): parser.error('Live mode needs authorization, new output and runtime directories')
        sys.exit(run(args,spec,counter,preparation))
