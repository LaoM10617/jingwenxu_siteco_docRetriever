"""Instance-wide memory settings. Never serialize credentials into public state."""
from copy import deepcopy
from threading import RLock, Lock
from typing import Literal, Annotated
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse
from pydantic import Field, SecretStr, StringConstraints, model_validator
from app.questions import StrictModel
from app.documents import DocumentError

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
class Credential(StrictModel):
    action: Literal['keep','replace','clear','default']
    value: Annotated[str, StringConstraints(min_length=1, max_length=4096)] | None = None
    @model_validator(mode='after')
    def check(self):
        if (self.action=='replace' and (self.value is None or not self.value.strip())) or (self.action!='replace' and self.value is not None):
            raise ValueError('Invalid credential action')
        return self
class Profile(StrictModel):
    model: Name | None = None
    credential: Credential | None = None
class Profiles(StrictModel):
    gemini: Profile | None = None
    groq: Profile | None = None
class Generation(StrictModel):
    provider: Literal['gemini','groq'] | None = None
    profiles: Profiles | None = None
class Retrieval(StrictModel):
    top_k: Annotated[int, Field(ge=1, le=20)] | None = None
    rerank_enabled: bool | None = None
class Embedding(StrictModel):
    credential: Credential | None = None
class Draft(StrictModel):
    generation: Generation | None = None
    retrieval: Retrieval | None = None
    embedding: Embedding | None = None
class Apply(Draft):
    expected_revision: Name
class Clear(StrictModel):
    expected_revision: Name
    scope: Literal['gemini','groq','voyage','all']
    mode: Literal['credentials','defaults']


class MemorySettings:
    def __init__(self, defaults):
        self.defaults = defaults.model_copy(deep=True)
        self.lock = RLock()
        self.probe_lock = Lock()
        self.current = defaults.model_copy(deep=True)
        self.top_k = 8
        self.sources = dict.fromkeys(('gemini','groq','voyage'), 'environment')
        self.revision = uuid4().hex

    def snapshot(self):
        with self.lock:
            return self.current.model_copy(deep=True), self.top_k, self.revision, dict(self.sources)

    def public(self, snapshot=None):
        config, top_k, revision, sources = snapshot or self.snapshot()
        def credential(provider):
            present = getattr(config, provider+'_api_key') is not None
            mode = sources[provider]
            return {'credential_status':'configured' if present else ('disabled' if mode=='disabled' else 'missing'),
                    'credential_source':mode if present else 'none'}
        return {'revision':revision,
            'generation':{'provider':config.generation_provider, 'profiles':{
                p:{'model':getattr(config,p+'_generation_model'), **credential(p)} for p in ('gemini','groq')}},
            'retrieval':{'top_k':top_k,'rerank_enabled':config.pdf_rerank_enabled,
                'lexical_candidates':20,'semantic_candidates':20,'rrf_k':60,'context_char_budget':28000,
                'rerank_model':'rerank-2.5-lite','rerank_budget_seconds':5},
            'embedding':{'provider':'voyage','model':config.embedding_model, **credential('voyage'),
                'model_editable':False,'account_limits_verified':False,
                'local_limits':{'rpm':config.embedding_rpm,'tpm':config.embedding_tpm,
                    'min_interval':config.embedding_min_interval,'rerank_min_interval':config.rerank_min_interval,
                    'source':'startup_configuration'}},
            'lifecycle':{'scope':'instance','persistence':'memory','restart':'environment_defaults'}}

    def candidate(self, expected, draft):
        with self.lock:
            if expected != self.revision:
                raise DocumentError('settings_conflict','Configuration changed. Reload Settings.',409)
            config, top_k, revision, sources = self.snapshot()
            def credential(provider, update):
                action=update.get('action','keep')
                if action=='keep': return
                key=provider+'_api_key'
                setattr(config,key, SecretStr(update['value'].strip()) if action=='replace' else
                        getattr(self.defaults,key) if action=='default' else None)
                sources[provider]={'replace':'override','default':'environment','clear':'disabled'}[action]
            generation=draft.get('generation',{})
            if 'provider' in generation: config.generation_provider=generation['provider']
            for provider, profile in generation.get('profiles',{}).items():
                if 'model' in profile: setattr(config,provider+'_generation_model',profile['model'])
                if 'credential' in profile: credential(provider,profile['credential'])
            retrieval=draft.get('retrieval',{})
            top_k=retrieval.get('top_k',top_k)
            config.pdf_rerank_enabled=retrieval.get('rerank_enabled',config.pdf_rerank_enabled)
            if 'credential' in draft.get('embedding',{}): credential('voyage',draft['embedding']['credential'])
            return config,top_k,revision,sources

    def apply(self, body):
        draft=body.model_dump(exclude_none=True,exclude={'expected_revision'})
        if not draft: raise DocumentError('invalid_settings','Provide settings to change.',422)
        with self.lock:
            config,top_k,_,sources=self.candidate(body.expected_revision,draft)
            self.current,self.top_k,self.sources=config,top_k,sources
            self.revision=uuid4().hex
            return self.public()

    def clear(self, body):
        with self.lock:
            self.candidate(body.expected_revision,{})
            providers=('gemini','groq','voyage') if body.scope=='all' else (body.scope,)
            for p in providers:
                setattr(self.current,p+'_api_key',getattr(self.defaults,p+'_api_key') if body.mode=='defaults' else None)
                self.sources[p]='environment' if body.mode=='defaults' else 'disabled'
                if body.mode=='defaults' and p!='voyage':
                    setattr(self.current,p+'_generation_model',getattr(self.defaults,p+'_generation_model'))
            if body.scope=='all' and body.mode=='defaults':
                self.current=self.defaults.model_copy(deep=True)
                self.top_k=8
            self.revision=uuid4().hex
            return self.public()


def secure_request(request):
    if request.headers.get('content-type','').split(';')[0].strip()!='application/json':
        raise DocumentError('invalid_request','Use application/json.',415)
    origin=request.headers.get('origin')
    if origin and (urlsplit(origin).scheme != request.url.scheme or urlsplit(origin).netloc!=request.headers.get('host')):
        raise DocumentError('settings_origin_rejected','Use Settings from this application.',403)

router=APIRouter()
@router.get('/api/settings')
def read_settings(request: Request):
    return JSONResponse(request.app.state.memory_settings.public(),headers={'Cache-Control':'no-store'})
@router.patch('/api/settings')
def apply_settings(body: Apply, request: Request):
    secure_request(request)
    return JSONResponse(request.app.state.memory_settings.apply(body),headers={'Cache-Control':'no-store'})
@router.post('/api/settings/clear')
def clear_settings(body: Clear, request: Request):
    secure_request(request)
    return JSONResponse(request.app.state.memory_settings.clear(body),headers={'Cache-Control':'no-store'})

class Probe(StrictModel):
    expected_revision: Name
    target: Literal['generation','embedding']
    draft: Draft | None = None
    explicit_probe: Literal[True]
class ProbeOutput(StrictModel):
    ok: Literal[True]


@router.post('/api/settings/test')
def test_settings(body: Probe, request: Request):
    from threading import Event, Thread
    import time
    from app.questions import QuestionBudget
    from app.generation import StructuredModel
    from app.voyage import VoyageProvider, load_token_counter
    from app.embeddings import EmbeddingGateway, EmbeddingError, PREFIXES
    secure_request(request)
    manager=request.app.state.memory_settings
    snapshot=manager.candidate(body.expected_revision, body.draft.model_dump(exclude_none=True) if body.draft else {})
    config=snapshot[0]
    if not manager.probe_lock.acquire(blocking=False):
        raise DocumentError('test_in_progress','Another connection test is running.',409)
    start=time.monotonic(); budget=QuestionBudget(); budget.deadline=start+20
    result={'target':body.target,'tested_revision':snapshot[2],'tested_public_config':manager.public(snapshot)}
    done=Event()
    def work():
        code='passed'
        try:
            key=config.voyage_api_key if body.target=='embedding' else getattr(config,config.generation_provider+'_api_key')
            if key is None:
                code='missing_key'
            elif body.target=='generation':
                raw=StructuredModel(config).generate('Return exactly the JSON object {"ok":true}.',
                    {'phase':'configuration_test','text':'Connection and structured output test.'},
                    ProbeOutput.model_json_schema(),budget)
                try: ProbeOutput.model_validate(raw)
                except Exception: code='invalid_output'
            else:
                text='Connection test.'
                counter=load_token_counter(config.data_dir/'tokenizers/voyage-4-tokenizer.json')
                tokens=counter(PREFIXES['query']+text)+16
                sent=[False]
                def call():
                    budget.check(); sent[0]=True
                    return VoyageProvider(key.get_secret_value(),timeout=min(20,budget.remaining())).embed(
                        [text],model=config.embedding_model,input_type='query',output_dimension=1024,
                        output_dtype='float',truncation=False)
                try:
                    response=request.app.state.bindings.scheduler.run(call,tokens,'query',budget,None)
                    EmbeddingGateway._vectors(response.vectors,1)
                except EmbeddingError as exc:
                    if not sent[0] and exc.code in ('embedding_interrupted','embedding_wait_timeout'):
                        code='local_rate_limited'
                    elif exc.code=='embedding_invalid_vectors': code='dimension_mismatch'
                    else: raise
        except (DocumentError,EmbeddingError) as exc:
            code={'generation_authentication_failed':'authentication_failed','embedding_authentication_failed':'authentication_failed',
                'generation_rate_limited':'provider_rate_limited','embedding_rate_limited':'provider_rate_limited',
                'generation_timeout':'timeout','question_timeout':'timeout','generation_invalid_output':'invalid_output',
                'generation_provider_unavailable':'provider_unavailable','embedding_provider_unavailable':'provider_unavailable',
                'generation_model_unavailable':'model_unavailable','generation_structured_output_unsupported':'structured_output_unsupported'}.get(exc.code,'provider_error')
        except Exception:
            code='provider_error'
        finally:
            result.update(status='passed' if code=='passed' else 'failed',code=code,
                          message='Test passed; full question capability is not guaranteed.' if code=='passed' else 'Test failed: '+code+'.',
                          elapsed_seconds=round(time.monotonic()-start,3))
            manager.probe_lock.release(); done.set()
    Thread(target=work,name='settings-probe',daemon=True).start()
    if not done.wait(max(0,budget.remaining())):
        # Do not release probe lock while an underlying request still runs.
        result={**result,'status':'failed','code':'timeout','message':'Connection test timed out.',
                'elapsed_seconds':round(time.monotonic()-start,3)}
    return JSONResponse(result,headers={'Cache-Control':'no-store'})
