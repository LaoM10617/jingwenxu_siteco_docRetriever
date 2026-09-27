import pytest
import socket

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original = socket.socket.connect
    def reject(sock, address):
        if isinstance(address, tuple) and address[0] in ('127.0.0.1', '::1'):
            return original(sock, address)
        raise AssertionError("No network permitted in settings tests")
    monkeypatch.setattr(socket.socket, "connect", reject)

from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings


def test_settings_atomic_clear_restore_and_revision(tmp_path):
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,gemini_api_key='environment-secret'))
    with TestClient(app) as client:
        r=client.get('/api/settings')
        assert r.status_code==200
        assert r.headers['cache-control']=='no-store'
        state=r.json(); assert 'environment-secret' not in r.text
        result=client.patch('/api/settings',json={'expected_revision':state['revision'],
            'generation':{'profiles':{'gemini':{'credential':{'action':'replace','value':'override-secret'}}}},
            'retrieval':{'top_k':20}})
        assert result.status_code==200 and 'override-secret' not in result.text
        assert result.json()['retrieval']['top_k']==20
        assert client.patch('/api/settings',json={'expected_revision':state['revision'],'retrieval':{'top_k':1}}).status_code==409
        state=result.json()
        bad=client.patch('/api/settings',json={'expected_revision':state['revision'],'retrieval':{'top_k':True}})
        assert bad.status_code==422
        state=client.post('/api/settings/clear',json={'expected_revision':state['revision'],'scope':'gemini','mode':'credentials'}).json()
        assert state['generation']['profiles']['gemini']['credential_status']=='disabled'
        state=client.post('/api/settings/clear',json={'expected_revision':state['revision'],'scope':'all','mode':'defaults'}).json()
        assert state['generation']['profiles']['gemini']['credential_source']=='environment'
        assert state['retrieval']['top_k']==8
        assert client.patch('/api/settings',headers={'Origin':'https://elsewhere.invalid'},json={'expected_revision':state['revision'],'retrieval':{'top_k':1}}).status_code==403


def test_task_freezes_configuration_and_idempotent_retry(tmp_path, monkeypatch):
    from threading import Event
    from app.processing import DocumentProcessor
    from test_question_tasks import Model, ready
    from app import generation
    release,entered=Event(),Event(); observed=[]
    class Controlled(Model):
        def __init__(self, config):
            super().__init__(); self.key=config.gemini_api_key.get_secret_value() if config.gemini_api_key else None
        def generate(self,*args):
            observed.append(self.key)
            if self.key=='old-secret':
                entered.set(); assert release.wait(3)
            return super().generate(*args)
    monkeypatch.setattr(generation,'StructuredModel',Controlled)
    monkeypatch.setattr('app.runtime_bindings.StructuredModel',Controlled)
    app=create_app(Settings(_env_file=None,data_dir=tmp_path,gemini_api_key='old-secret'),processor=DocumentProcessor())
    with TestClient(app) as client:
        doc=ready(client); body={'conversation_id':'a','request_id':'one','question':'001','document_ids':[doc]}
        try:
            first=client.post('/api/questions',json=body).json()
            assert entered.wait(2)
            state=client.get('/api/settings').json()
            client.patch('/api/settings',json={'expected_revision':state['revision'],'generation':{'profiles':{'gemini':{'credential':{'action':'replace','value':'new-secret'}}}},'retrieval':{'top_k':1}})
            assert client.post('/api/questions',json=body).json()['question_id']==first['question_id']
            second=client.post('/api/questions',json={**body,'request_id':'two'}).json()
            assert first['config_snapshot']['retrieval']['top_k']==8
            assert second['config_snapshot']['retrieval']['top_k']==1
        finally: release.set()
        import time
        for _ in range(100):
            result=client.get('/api/questions/'+second['question_id']+'?conversation_id=a').json()
            if result['status'] in ('completed','failed'):break
            time.sleep(.02)
        assert result['status']=='completed'
        assert observed==['old-secret','old-secret','new-secret','new-secret']
        assert b'old-secret' not in (tmp_path/'app.sqlite3').read_bytes()
        assert b'new-secret' not in (tmp_path/'app.sqlite3').read_bytes()


def test_probe_uses_fixed_payload_once_and_does_not_apply(tmp_path,monkeypatch):
    from app.generation import StructuredModel
    calls=[]
    def generate(self,system,payload,schema,budget):
        calls.append(payload)
        return {'ok':True}
    monkeypatch.setattr(StructuredModel,'generate',generate)
    with TestClient(create_app(Settings(_env_file=None,data_dir=tmp_path))) as client:
        state=client.get('/api/settings').json()
        body={'expected_revision':state['revision'],'target':'generation','explicit_probe':True}
        missing=client.post('/api/settings/test',json=body)
        assert missing.status_code==200 and missing.json()['code']=='missing_key'
        result=client.post('/api/settings/test',json={**body,'draft':{'generation':{'profiles':{'gemini':{'credential':{'action':'replace','value':'test-secret'}}}}}})
        assert result.json()['status']=='passed'
        assert len(calls)==1 and 'bundle' not in calls[0]
        assert 'test-secret' not in result.text
        assert client.get('/api/settings').json()==state


def test_upload_batches_keep_key_and_restart_restores_defaults(tmp_path,monkeypatch):
    import shutil,time
    from threading import Event
    from pathlib import Path
    import numpy as np
    from app.embeddings import EmbeddingResponse
    from app.voyage import VoyageProvider
    from test_parsing import pdf_file
    release,entered=Event(),Event(); used=[]
    class Provider:
        def __init__(self,key,**kw):self.key=key
        def embed(self,texts,**kw):
            used.append(self.key); entered.set(); assert release.wait(3)
            return EmbeddingResponse([[1.0]+[0.0]*1023 for _ in texts],len(texts))
    monkeypatch.setattr('app.voyage.VoyageProvider',Provider)
    monkeypatch.setattr('app.voyage.load_token_counter',lambda path:lambda text:3000)
    config=Settings(_env_file=None,data_dir=tmp_path/'runtime',voyage_api_key='old-key',embedding_min_interval=0,embedding_rpm=60,embedding_tpm=200000)
    with TestClient(create_app(config)) as client:
        try:
            response=client.post('/api/documents',files={'file':('pages.pdf',pdf_file(tmp_path,['First page','Second page']).read_bytes(),'application/pdf')})
            assert response.status_code==202 and entered.wait(2)
            state=client.get('/api/settings').json()
            changed=client.patch('/api/settings',json={'expected_revision':state['revision'],'embedding':{'credential':{'action':'replace','value':'new-key'}}}).json()
        finally:release.set()
        for _ in range(100):
            doc=client.get('/api/documents/'+response.json()['document_id']).json()
            if doc['status'] in ('ready','failed'):break
            time.sleep(.02)
        assert doc['status']=='ready' and used==['old-key','old-key']
    with TestClient(create_app(config)) as client:
        state=client.get('/api/settings').json()
        assert state['revision']!=changed['revision']
        assert state['embedding']['credential_source']=='environment'
        assert client.get('/api/documents/'+response.json()['document_id']).json()['status']=='ready'


@pytest.mark.parametrize('top_k',[1,8,20])
def test_pdf_diagnostic_counts_and_selected_top_k(corpus,top_k):
    from app.retrieval.pdf import PdfRetriever
    from app.questions import QuestionTools
    from app.answers import evidence_context
    docs,gateway,identity=corpus
    retriever=PdfRetriever(docs,docs.lexical,gateway,default_top_k=top_k)
    bundle=QuestionTools(docs,retriever).prepare({'conversation_id':'a','question':'retention','document_ids':[identity]})
    d=bundle['tools'][0]['result']['diagnostics']
    assert d['union_count']==10
    assert d['selected_count']==min(top_k,10) and d['requested_top_k']==top_k

from test_reranking import corpus


@pytest.mark.parametrize('local_wait', [True, False])
def test_probe_deadline_distinguishes_local_admission_and_inflight_timeout(tmp_path, monkeypatch, local_wait):
    from threading import Event
    from app import runtime_settings
    from app.embeddings import EmbeddingResponse
    # Shorten only the test deadline; exercise real admission and HTTP lifecycle.
    monkeypatch.setattr(runtime_settings, 'PROBE_TIMEOUT_SECONDS', .1, raising=False)
    monkeypatch.setattr('app.voyage.load_token_counter', lambda path: lambda text: 2)
    release, entered = Event(), Event()
    calls = []
    class Provider:
        def __init__(self, key, **kwargs):
            pass
        def embed(self, texts, **kwargs):
            calls.append(texts)
            entered.set()
            assert release.wait(3)
            return EmbeddingResponse([[1.0] + [0.0] * 1023], 2)
    monkeypatch.setattr('app.voyage.VoyageProvider', Provider)
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, voyage_api_key='fake-key'))
    with TestClient(app) as client:
        if local_wait:
            app.state.bindings.scheduler.defer(60)
        state = client.get('/api/settings').json()
        body = {'expected_revision': state['revision'], 'target': 'embedding', 'explicit_probe': True}
        try:
            response = client.post('/api/settings/test', json=body)
            assert response.status_code == 200
            assert response.json()['code'] == ('local_rate_limited' if local_wait else 'timeout')
            assert response.json()['elapsed_seconds'] < 1
            if local_wait:
                assert calls == []
            else:
                assert entered.is_set() and len(calls) == 1
                # A timed-out caller does not free the still-running provider slot.
                assert client.post('/api/settings/test', json=body).status_code == 409
            assert client.get('/api/settings').json() == state
        finally:
            release.set()
