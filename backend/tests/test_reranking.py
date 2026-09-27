from io import BytesIO
from types import SimpleNamespace
import pytest
from app.documents import DocumentService
from app.processing import DocumentProcessor
from app.retrieval.pdf import PdfRetriever
from test_pdf_publication import Gateway
from test_parsing import pdf_file
from test_lifecycle import wait_status

@pytest.fixture
def corpus(tmp_path):
    docs = DocumentService(tmp_path/'runtime')
    gateway = Gateway()
    docs.start(DocumentProcessor(gateway))
    identity = docs.submit('prose.pdf', BytesIO(pdf_file(tmp_path, [f'Clause {i} retention exception' for i in range(10)]).read_bytes()))['document_id']
    wait_status(docs, identity, 'ready')
    yield docs, gateway, identity
    docs.stop()


def test_rerank_uses_union_before_final8_and_preserves_sources(corpus):
    from app.reranking import Reranker
    docs, gateway, identity = corpus
    baseline = PdfRetriever(docs, docs.lexical, gateway).retrieve('retention', [identity], top_k=40)
    seen = []
    def provider(query, texts, timeout):
        seen.extend(texts)
        return list(reversed(range(len(texts))))
    result = PdfRetriever(docs, docs.lexical, gateway, reranker=Reranker(provider)).retrieve('retention', [identity])
    assert len(seen) == 10
    assert result['records'] == list(reversed(baseline['records']))[:8]
    assert result['routes']['rerank']['status'] == 'ok'

@pytest.mark.parametrize('failure', ['timeout', '429', 'authentication', 'duplicate', 'bool_index', 'outside'])
def test_failure_preserves_rrf_and_warns_question(corpus, failure):
    from app.reranking import Reranker
    from app.questions import QuestionTools
    docs, gateway, identity = corpus
    baseline = PdfRetriever(docs, docs.lexical, gateway).retrieve('retention', [identity])
    def provider(query, texts, timeout):
        if failure in ('timeout','429','authentication'):
            raise RuntimeError(failure)
        if failure == 'duplicate': return [0]*len(texts)
        if failure == 'bool_index': return [False]+list(range(1,len(texts)))
        return list(range(1,len(texts)+1))
    retriever = PdfRetriever(docs, docs.lexical, gateway, reranker=Reranker(provider))
    bundle = QuestionTools(docs, retriever).prepare({'conversation_id':'a','question':'retention','document_ids':[identity]})
    assert bundle['tools'][0]['result']['records'] == baseline['records']
    assert any(w['code']=='rerank_fallback' for w in bundle['warnings'])


def test_deadline_and_inflight_do_not_wait_or_issue_extra_calls(corpus):
    from app.reranking import Reranker
    from threading import Event
    import time
    docs, gateway, identity = corpus
    release = Event()
    calls = []
    def provider(query, texts, timeout):
        calls.append(timeout)
        release.wait(2)
        return list(range(len(texts)))
    ranker = Reranker(provider)
    retriever = PdfRetriever(docs, docs.lexical, gateway, reranker=ranker)
    class Budget:
        def is_set(self): return False
        def remaining(self): return .05
    try:
        start = time.monotonic()
        first = retriever.retrieve('retention',[identity],stop=Budget())
        assert time.monotonic()-start < .5
        second = retriever.retrieve('retention',[identity])
        assert first['routes']['rerank']['status']=='fallback'
        assert second['routes']['rerank']['reason']=='busy'
        assert len(calls)==1 and calls[0] <= .05
    finally:
        release.set()


def test_insufficient_budget_and_cooldown_skip_provider(corpus):
    from app.reranking import Reranker
    docs,gateway,identity=corpus
    calls=[]
    def provider(q,texts,timeout):
        calls.append(q)
        return list(range(len(texts)))
    retriever=PdfRetriever(docs,docs.lexical,gateway,reranker=Reranker(provider))
    class Empty:
        def is_set(self): return False
        def remaining(self): return 0
    assert retriever.retrieve('retention',[identity],stop=Empty())['routes']['rerank']['reason']=='budget'
    assert not calls
    assert retriever.retrieve('retention',[identity])['routes']['rerank']['status']=='ok'
    assert retriever.retrieve('retention',[identity])['routes']['rerank']['reason']=='rate_limit'
    assert len(calls)==1


def test_configuration_defaults_off_and_fixed_sdk_contract(corpus, monkeypatch):
    from app.config import Settings
    from app.reranking import configured_reranker
    import voyageai
    docs,gateway,identity=corpus
    assert configured_reranker(Settings(_env_file=None)) is None
    calls=[]
    class Client:
        def __init__(self,**kw):
            assert kw['max_retries']==0 and 0<kw['timeout']<=5
        def rerank(self,q,texts,**kw):
            calls.append(kw)
            return SimpleNamespace(results=[SimpleNamespace(index=i) for i in reversed(range(len(texts)))])
    monkeypatch.setattr(voyageai,'Client',Client)
    settings=Settings(_env_file=None,pdf_rerank_enabled=True,voyage_api_key='test-only')
    result=PdfRetriever(docs,docs.lexical,gateway,reranker=configured_reranker(settings)).retrieve('retention',[identity])
    assert result['routes']['rerank']['status']=='ok'
    assert calls==[{'model':'rerank-2.5-lite','top_k':None,'truncation':False}]
