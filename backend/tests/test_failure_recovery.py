"""M3.4 failures remain execution failures across task publication and recovery."""
import time
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings
from app.generation import StructuredModel
from app.processing import DocumentProcessor
from test_app import settings_for
from test_question_tasks import Model, ready
from test_multi_document_tasks import finish
from test_csv_lifecycle import service


def terminal(client, identity):
    for _ in range(250):
        result = client.get('/api/questions/' + identity, params={'conversation_id':'a'})
        assert result.status_code == 200
        task = result.json()
        if task['status'] in ('completed','failed'):
            return task
        time.sleep(.02)
    pytest.fail('Task did not reach a terminal state')


@pytest.mark.parametrize('provider', ['gemini','groq'])
@pytest.mark.parametrize('failure,code', [
    (401,'generation_authentication_failed'), (429,'generation_rate_limited'),
    (503,'generation_provider_unavailable'), ('bad-json','generation_invalid_output'),
    ('timeout','generation_timeout')])
def test_sdk_failure_is_published_once_without_an_absence_of_evidence_answer(tmp_path, provider, failure, code):
    calls=[]
    def respond(request):
        calls.append(True)
        if failure == 'timeout':
            raise httpx.ReadTimeout('private-provider-detail',request=request)
        if isinstance(failure,int):
            return httpx.Response(failure,json={'error':{'code':failure,'message':'private-provider-detail'}})
        if provider == 'gemini':
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP',
                'content':{'parts':[{'text':'not JSON'}],'role':'model'}}]})
        return httpx.Response(200,json={'id':'t','object':'chat.completion','created':1,'model':'test',
            'choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'not JSON'}}]})
    model = StructuredModel(Settings(_env_file=None,data_dir=tmp_path,generation_provider=provider,
        gemini_api_key='fake',groq_api_key='fake'),transport=httpx.MockTransport(respond))
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=model)) as client:
        doc=ready(client)
        body={'conversation_id':'a','request_id':'r','question':'001','document_ids':[doc]}
        submitted=client.post('/api/questions',json=body)
        assert submitted.status_code == 202
        qid=submitted.json()['question_id']
        task=terminal(client,qid)
        assert task['status'] == task['stage'] == 'failed'
        assert task['error']['code'] == code and task['answer'] is None
        assert 'private-provider-detail' not in str(task)
        assert client.post('/api/questions',json=body).json()['question_id'] == qid
        assert terminal(client,qid) == task
        assert len(calls) == 1
        assert client.get('/api/documents/'+doc).json()['status'] == 'ready'


def test_expired_question_and_paging_are_unavailable_but_ready_document_survives(tmp_path, monkeypatch):
    clock=[1_800_000_000.0]
    monkeypatch.setattr('app.question_tasks.time.time',lambda:clock[0])
    model=Model()
    with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=model)) as client:
        doc=ready(client)
        body={'conversation_id':'a','request_id':'r','question':'001','document_ids':[doc]}
        task=finish(client,body)
        path='/api/questions/'+task['question_id']
        clock[0]+=86399
        assert client.get(path,params={'conversation_id':'a'}).status_code == 200
        clock[0]+=2
        assert client.get(path,params={'conversation_id':'a'}).status_code == 404
        assert client.get(path+'/csv/0',params={'conversation_id':'a'}).status_code == 404
        assert client.get('/api/documents/'+doc).json()['status'] == 'ready'
        assert model.calls == 2
        # Retention bounds idempotency; only an explicit new submission creates work again.
        renewed=finish(client,body)
        assert renewed['question_id'] != task['question_id']
        assert model.calls == 4


def test_restart_preserves_interrupted_tasks_without_reexecuting_them(tmp_path):
    entered,release=Event(),Event()
    class Blocked(Model):
        def generate(self,*args):
            entered.set()
            assert release.wait(10)
            return super().generate(*args)
    old=Blocked()
    try:
        with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=old)) as client:
            doc=ready(client)
            body={'conversation_id':'a','request_id':'running','question':'001','document_ids':[doc]}
            first=client.post('/api/questions',json=body).json()['question_id']
            assert entered.wait(2)
            queued={**body,'request_id':'queued'}
            second=client.post('/api/questions',json=queued).json()['question_id']
        new=Model()
        with TestClient(create_app(settings_for(tmp_path),processor=DocumentProcessor(),model=new)) as client:
            release.set()
            for qid,value in [(first,body),(second,queued)]:
                task=terminal(client,qid)
                assert task['error']['code'] == 'question_interrupted'
                assert task['answer'] is None
                assert client.post('/api/questions',json=value).json()['question_id'] == qid
            assert new.calls == 0
            # A new request proves the restarted worker is usable, not silently replaying old work.
            finish(client,{**body,'request_id':'explicit-new'})
            assert new.calls == 2
            for qid in [first,second]:
                assert terminal(client,qid)['error']['code'] == 'question_interrupted'
            assert client.get('/api/documents/'+doc).json()['status'] == 'ready'
    finally:
        release.set()


@pytest.mark.parametrize('phase', ['plan','answer'])
def test_queued_and_running_deadlines_remain_final_after_late_provider_returns(tmp_path, phase, service):
    from app.answers import AnswerService
    from app.questions import QuestionTools
    from app.question_tasks import QuestionTasks
    from test_csv_lifecycle import publish
    from test_csv_parsing import row
    documents=service
    doc=publish(documents,[row('001')])
    entered,release=Event(),Event()
    clock=[0.0]
    class Late(Model):
        def generate(self,system,payload,schema,budget):
            if payload['phase']==phase:
                entered.set()
                assert release.wait(10)
            return super().generate(system,payload,schema,budget)
    tasks=QuestionTasks(tmp_path/'tasks.sqlite3',AnswerService(QuestionTools(documents,None),Late()),
                        now=lambda:clock[0])
    body={'conversation_id':'a','request_id':'first','question':'001','document_ids':[doc]}
    try:
        first=tasks.submit(body)
        assert entered.wait(2)
        second=tasks.submit({**body,'request_id':'queued'})
        clock[0]=241
        frozen=[tasks.get(t['question_id'],'a') for t in [first,second]]
        assert all(t['error']['code']=='question_timeout' and t['answer'] is None for t in frozen)
        release.set()
        sentinel=tasks.submit({**body,'request_id':'after-timeout'})
        for _ in range(250):
            last=tasks.get(sentinel['question_id'],'a')
            if last['status'] in ('completed','failed'):
                break
            time.sleep(.02)
        assert last['status']=='completed'
        # The single worker passed both old jobs before this sentinel completed.
        assert [tasks.get(t['question_id'],'a') for t in [first,second]] == frozen
        assert documents.get(doc)['status']=='ready'
    finally:
        release.set()
        tasks.stop()
