"""M3.2 real HTTP and storage with controlled external waits."""
from threading import Event
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_multi_document_tasks import TaskGateway, ScopeModel, upload, finish
from test_parsing import pdf_file
from test_question_tasks import Model, ready, csv_bytes
from test_csv_parsing import row


def test_ingestion_wait_keeps_ready_answers_and_http_available(tmp_path):
    waiting, admitted, admit, complete = Event(), Event(), Event(), Event()
    class Waiting(TaskGateway):
        def embed(self, texts, *, input_type, stop=None, on_wait=None, on_start=None):
            if input_type == 'document' and 'waiting' in texts[0]:
                on_wait()
                waiting.set()
                assert admit.wait(10)
                if on_start:
                    on_start()
                admitted.set()
                assert complete.wait(10)
            return super().embed(texts, input_type=input_type, stop=stop,
                                 on_wait=on_wait, on_start=on_start)

    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(Waiting()), model=ScopeModel())) as client:
        try:
            old = upload(client, 'old.pdf', pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes())
            pending = client.post('/api/documents', files={'file': ('new.pdf',
                pdf_file(tmp_path, ['waiting lamp']).read_bytes())}).json()['document_id']
            assert waiting.wait(2)
            assert client.get('/api/documents/' + pending).json()['stage'] == 'waiting_rate_limit'
            task = finish(client, {'conversation_id':'a','request_id':'r',
                                  'question':'AB-123 power?', 'document_ids':[old]})
            assert task['answer']['citations'][0]['document_id'] == old
            assert client.get('/api/health').status_code == 200
            extra = client.post('/api/documents', files={'file':('prices.csv',csv_bytes([row('001')]))})
            assert extra.status_code == 202
            assert client.get('/api/documents/' + old).json()['status'] == 'ready'
            admit.set()
            assert admitted.wait(2)
            # Provider execution has begun; quota waiting is no longer the current stage.
            assert client.get('/api/documents/' + pending).json()['stage'] == 'embedding'
            complete.set()
            for _ in range(100):
                if client.get('/api/documents/' + pending).json()['status'] == 'ready':
                    break
                time.sleep(.02)
            assert client.get('/api/documents/' + pending).json()['status'] == 'ready'
        finally:
            admit.set()
            complete.set()


def test_default_queue_admits_eight_waiters_and_same_request_does_not_duplicate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    entered, release = Event(), Event()
    class Blocked(Model):
        def generate(self, *args):
            entered.set()
            assert release.wait(10)
            return super().generate(*args)
    model = Blocked()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        try:
            identity = ready(client)
            body = {'conversation_id':'a','request_id':'first','question':'001','document_ids':[identity]}
            first = client.post('/api/questions', json=body).json()
            assert entered.wait(2)
            def submit(n):
                value = {**body, 'request_id':str(n)}
                return value, client.post('/api/questions', json=value)
            with ThreadPoolExecutor(max_workers=12) as pool:
                responses = list(pool.map(submit, range(12)))
            accepted = [(b,r.json()) for b,r in responses if r.status_code == 202]
            rejected = [r for _,r in responses if r.status_code == 503]
            assert len(accepted) == 8
            assert len(rejected) == 4
            assert all(r.json()['error']['code'] == 'question_queue_full' for r in rejected)
            assert len({t['question_id'] for _,t in accepted}) == 8
            for value, task in [(body,first), *accepted]:
                same = client.post('/api/questions', json=value)
                assert same.status_code == 202
                assert same.json()['question_id'] == task['question_id']
                state = client.get('/api/questions/' + task['question_id'], params={'conversation_id':'a'}).json()
                assert state['status'] == ('running' if value == body else 'queued')
            assert client.post('/api/questions', json={**body,'question':'different'}).status_code == 409
            assert client.get('/api/health').status_code == 200
            assert ready(client) != identity
            release.set()
            for _,task in [(body,first), *accepted]:
                for _ in range(250):
                    state = client.get('/api/questions/' + task['question_id'], params={'conversation_id':'a'}).json()
                    if state['status'] in ('completed','failed'):
                        break
                    time.sleep(.02)
                assert state['status'] == 'completed', state.get('error')
            # Nine admitted questions each require one plan and one answer, despite resends.
            assert model.calls == 18
            finish(client, {**body,'request_id':'after-drain'})
            assert model.calls == 20
        finally:
            release.set()


def test_query_quota_stage_resumes_without_blocking_health_upload_or_poll(tmp_path):
    waiting, admit, started, complete = Event(), Event(), Event(), Event()
    class Waiting(TaskGateway):
        def embed(self, texts, *, input_type, stop=None, on_wait=None, on_start=None):
            if input_type == 'query':
                on_wait()
                waiting.set()
                assert admit.wait(10)
                on_start()
                started.set()
                assert complete.wait(10)
            return super().embed(texts, input_type=input_type, stop=stop, on_wait=on_wait)
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(Waiting()), model=ScopeModel())) as client:
        try:
            old = upload(client, 'old.pdf', pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes())
            body = {'conversation_id':'a','request_id':'r','question':'AB-123 power?','document_ids':[old]}
            qid = client.post('/api/questions',json=body).json()['question_id']
            path = '/api/questions/' + qid
            assert waiting.wait(2)
            state = client.get(path,params={'conversation_id':'a'}).json()
            assert (state['status'],state['stage'],state['answer']) == ('running','waiting_rate_limit',None)
            assert client.get('/api/health').status_code == 200
            assert ready(client) != old
            assert client.post('/api/questions',json=body).json()['question_id'] == qid
            admit.set()
            assert started.wait(2)
            assert client.get(path,params={'conversation_id':'a'}).json()['stage'] == 'retrieving'
            complete.set()
            task = finish(client, body)
            assert task['question_id'] == qid
            assert task['answer']['citations'][0]['document_id'] == old
        finally:
            admit.set()
            complete.set()
