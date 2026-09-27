"""Question task behavior through HTTP with real storage and external model fake."""
import time
import csv
import gc
import sqlite3
import weakref
from io import StringIO
from threading import Event
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_csv_parsing import row, HEADERS
from test_csv_lifecycle import service, publish
from app.question_tasks import QuestionTasks
from app.answers import AnswerService
from app.questions import QuestionTools
from app.documents import DocumentError


def csv_bytes(rows):
    out = StringIO()
    csv.writer(out, delimiter=';').writerows([HEADERS, *rows])
    return out.getvalue().encode()


class Model:
    provider = 'test'
    model = 'controlled'
    def __init__(self):
        self.calls = 0
    def generate(self, system, payload, schema, budget):
        self.calls += 1
        if payload['phase'] == 'plan':
            return {'tools': [{'tool': 'lookup_orders', 'document_ids':
                [d['document_id'] for d in payload['documents']], 'order_ids': ['001']}]}
        return {'outcome': 'answered', 'segments': [{'text': '12,50', 'citation_ids': ['S1'],
                'calculation_ids': []}], 'gaps': [], 'calculations': []}


def ready(client):
    response = client.post('/api/documents', files={'file': ('prices.csv', csv_bytes([row('001', '12,50')]), 'text/csv')})
    identity = response.json()['document_id']
    for _ in range(100):
        if client.get('/api/documents/' + identity).json()['status'] == 'ready':
            return identity
        time.sleep(.02)
    raise AssertionError('Not ready')


def test_submit_poll_idempotency_and_conversation_scope(tmp_path):
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=Model())) as client:
        identity = ready(client)
        body = {'conversation_id': 'a', 'request_id': 'r1', 'question': 'Preis 001?', 'document_ids': [identity]}
        submitted = client.post('/api/questions', json=body)
        assert submitted.status_code == 202
        qid = submitted.json()['question_id']
        path = '/api/questions/' + qid + '?conversation_id=a'
        for _ in range(100):
            result = client.get(path).json()
            if result['status'] in ('completed', 'failed'):
                break
            time.sleep(.02)
        assert result['status'] == 'completed' and result['answer']['citations'][0]['locator']['record_number'] == 1
        assert client.post('/api/questions', json=body).json()['question_id'] == qid
        assert client.post('/api/questions', json={**body, 'question': 'different'}).status_code == 409
        assert client.get('/api/questions/' + qid + '?conversation_id=b').status_code == 404
        assert client.post('/api/questions', json={**body, 'request_id': 'r2', 'document_ids': ['missing']}).status_code == 404


def test_deadline_queue_bound_and_late_worker_cannot_publish(service, tmp_path):
    identity = publish(service, [row('001')])
    entered, release = Event(), Event()
    clock = [0.0]
    class Blocked(Model):
        def generate(self, *args):
            entered.set()
            release.wait(5)
            return super().generate(*args)
    tasks = QuestionTasks(tmp_path / 'app.sqlite3', AnswerService(QuestionTools(service, None), Blocked()),
                          now=lambda: clock[0], max_pending=1)
    body = {'conversation_id': 'a', 'request_id': 'one', 'question': '001', 'document_ids': [identity]}
    try:
        first = tasks.submit(body)
        assert entered.wait(2)
        second = tasks.submit({**body, 'request_id': 'two'})
        with pytest.raises(DocumentError) as error:
            tasks.submit({**body, 'request_id': 'three'})
        assert error.value.code == 'question_queue_full'
        clock[0] = 241
        for item in [first, second]:
            assert tasks.get(item['question_id'], 'a')['error']['code'] == 'question_timeout'
        release.set()
        time.sleep(.1)
        assert tasks.get(first['question_id'], 'a')['answer'] is None
        assert service.get(identity)['status'] == 'ready'
    finally:
        release.set()
        tasks.stop()


def test_restart_retains_results_and_csv_paging_never_calls_model(tmp_path):
    model = Model()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        identity = ready(client)
        body = {'conversation_id': 'a', 'request_id': 'r1', 'question': '001', 'document_ids': [identity]}
        qid = client.post('/api/questions', json=body).json()['question_id']
        path = '/api/questions/' + qid
        for _ in range(100):
            if client.get(path, params={'conversation_id': 'a'}).json()['status'] == 'completed':
                break
            time.sleep(.02)
    class Forbidden(Model):
        def generate(self, *args):
            raise AssertionError('Paging/restoration must not call a model')
    with TestClient(create_app(settings_for(tmp_path), model=Forbidden())) as client:
        restored = client.get(path, params={'conversation_id': 'a'}).json()
        assert restored['status'] == 'completed'
        page = client.get(path + '/csv/0', params={'conversation_id': 'a', 'limit': 1}).json()
        assert page['total'] == 1 and page['records'][0]['order_id'] == '001'
        assert client.get(path + '/csv/0', params={'conversation_id': 'other'}).status_code == 404
        assert client.get(path + '/csv/-1', params={'conversation_id': 'a'}).status_code == 404
        assert client.post('/api/questions', json=body).json()['question_id'] == qid


def test_shutdown_interrupts_pending_and_running_without_automatic_retry(service, tmp_path):
    identity = publish(service, [row('001')])
    entered, release = Event(), Event()
    class Blocked(Model):
        def generate(self, *args):
            entered.set()
            release.wait(5)
            return super().generate(*args)
    answers = AnswerService(QuestionTools(service, None), Blocked())
    tasks = QuestionTasks(tmp_path / 'app.sqlite3', answers)
    body = {'conversation_id': 'a', 'request_id': 'r1', 'question': '001', 'document_ids': [identity]}
    first = tasks.submit(body)
    assert entered.wait(2)
    second = tasks.submit({**body, 'request_id': 'r2'})
    tasks.stop()
    release.set()
    restored = QuestionTasks(tmp_path / 'app.sqlite3', answers)
    try:
        for item in [first, second]:
            result = restored.get(item['question_id'], 'a')
            assert result['status'] == 'failed' and result['error']['code'] == 'question_interrupted'
    finally:
        restored.stop()


def test_health_upload_and_poll_respond_while_provider_waits(tmp_path):
    entered, release = Event(), Event()
    class Blocked(Model):
        def generate(self, *args):
            entered.set()
            release.wait(5)
            return super().generate(*args)
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=Blocked())) as client:
        try:
            identity = ready(client)
            body = {'conversation_id': 'a', 'request_id': 'r1', 'question': '001', 'document_ids': [identity]}
            qid = client.post('/api/questions', json=body).json()['question_id']
            assert entered.wait(2)
            assert client.get('/api/health').status_code == 200
            assert ready(client) != identity
            assert client.get('/api/questions/' + qid, params={'conversation_id': 'a'}).json()['status'] == 'running'
        finally:
            release.set()


def test_entire_scope_and_schema_are_validated_before_model_calls(tmp_path):
    model = Model()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        identity = ready(client)
        body = {'conversation_id': 'a', 'request_id': 'r1', 'question': '001', 'document_ids': [identity]}
        for extra, status in [({'question':'  '},422), ({'document_ids':[identity,'unknown']},404),
                              ({'sql':'select *'},422), ({'document_ids':[]},422)]:
            assert client.post('/api/questions',json={**body,**extra}).status_code == status
        assert model.calls == 0


@pytest.mark.parametrize('failure_at', ['execute', 'commit'])
def test_failed_publication_recovers_and_releases_task_resources(service, tmp_path, monkeypatch, failure_at):
    identity = publish(service, [row('001')])
    publication_failed, recovery_failed = Event(), Event()
    allow_recovery = Event()
    references = []
    class TrackedAnswers(AnswerService):
        def answer(self, request, *, budget, **kwargs):
            references.append((weakref.ref(self), weakref.ref(budget)))
            return super().answer(request, budget=budget, **kwargs)
    answers = AnswerService(QuestionTools(service, None), Model())
    tasks = QuestionTasks(tmp_path / 'tasks.sqlite3', answers,
                          answer_factory=lambda: TrackedAnswers(answers.tools, Model()))
    connect = sqlite3.connect
    class InterruptedConnection(sqlite3.Connection):
        publishing = False
        recovering = False
        def execute(self, sql, parameters=()):
            if sql.startswith('UPDATE question_tasks SET status=?,stage=?'):
                self.publishing = True
                if failure_at == 'execute' and not publication_failed.is_set():
                    publication_failed.set()
                    raise sqlite3.OperationalError('synthetic publication failure')
            if publication_failed.is_set() and sql.startswith("UPDATE question_tasks SET status='failed',stage='failed',error=? WHERE id=?"):
                self.recovering = True
            return super().execute(sql, parameters)
        def __exit__(self, exc_type, exc, traceback):
            if exc_type is None:
                if self.publishing and failure_at == 'commit' and not publication_failed.is_set():
                    self.rollback()
                    publication_failed.set()
                    raise sqlite3.OperationalError('synthetic publication commit failure')
                if self.recovering and not allow_recovery.is_set():
                    self.rollback()
                    recovery_failed.set()
                    raise sqlite3.OperationalError('synthetic recovery commit failure')
            return super().__exit__(exc_type, exc, traceback)
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs:
                        connect(*args, **kwargs, factory=InterruptedConnection))
    body = {'conversation_id': 'a', 'request_id': 'one', 'question': '001', 'document_ids': [identity]}
    try:
        first = tasks.submit(body)
        assert publication_failed.wait(3)
        assert recovery_failed.wait(3)
        allow_recovery.set()
        for _ in range(150):
            result = tasks.get(first['question_id'], 'a')
            if result['status'] == 'failed':
                break
            time.sleep(.02)
        assert result['status'] == 'failed'
        assert result['answer'] is None
        assert result['error']['code'] == 'question_timeout'
        assert tasks.submit(body)['question_id'] == first['question_id']
        second = tasks.submit({**body, 'request_id': 'two'})
        for _ in range(150):
            result = tasks.get(second['question_id'], 'a')
            if result['status'] == 'completed':
                break
            time.sleep(.02)
        assert result['status'] == 'completed'
        # Weak references observe resource lifetime without inspecting task dictionaries.
        for _ in range(100):
            gc.collect()
            if all(ref() is None for ref in references[0]):
                break
            time.sleep(.02)
        assert all(ref() is None for ref in references[0])
    finally:
        allow_recovery.set()
        tasks.stop()
