"""New session/run HTTP entry point through the real PDF specialist graph."""
from threading import Event
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.processing import DocumentProcessor
from test_csv_lifecycle import terminal
from test_parsing import pdf_file
from test_pdf_publication import Gateway


class Model:
    provider = 'controlled'
    model = 'graph-http-test'

    def __init__(self):
        self.calls = []
        self.entered = Event()
        self.block = False
        self.fail = False

    def generate(self, system, payload, schema, budget):
        self.calls.append(payload['phase'])
        if self.fail:
            raise RuntimeError('PRIVATE_PROVIDER_DIAGNOSTIC')
        if payload['phase'] == 'intent':
            if payload['question'] == 'Clarify first' and not payload['clarifications']:
                return {'route': 'clarification', 'objective': 'Read power', 'clarification': 'Which product?'}
            return {'route': 'pdf', 'objective': 'What is A power?'}
        if self.block:
            self.entered.set()
            deadline = time.monotonic() + 10
            while self.block and time.monotonic() < deadline:
                budget.check()
                time.sleep(.01)
        return {'outcome': 'answered', 'segments': [{'text': 'A power is 12.5 W.',
            'citation_ids': ['S1'], 'calculation_ids': []}], 'gaps': [], 'calculations': []}


def prepared(tmp_path, model):
    return create_app(Settings(data_dir=tmp_path / 'runtime'),
                      processor=DocumentProcessor(Gateway()), model=model)


def upload(client, tmp_path):
    sid = client.post('/api/sessions').json()['session_id']
    source = pdf_file(tmp_path, ['A power: 12.5 W'])
    response = client.post('/api/documents', params={'session_id': sid},
                           files={'file': ('A.pdf', source.read_bytes())})
    assert response.status_code == 202, response.text
    did = response.json()['document_id']
    assert terminal(client.app.state.documents, did)['status'] == 'ready'
    return sid, did


def submission(client, sid, *, request_id='q1', question='What is A power?'):
    session = client.get(f'/api/sessions/{sid}').json()
    return {'request_id': request_id, 'question': question,
            'expected_data_version': session['data_version'],
            'expected_rule_version': session['rule_version']}


def poll(client, sid, rid, statuses):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f'/api/sessions/{sid}/runs/{rid}')
        assert response.status_code == 200, response.text
        run = response.json()
        if run['status'] in statuses:
            return run
        time.sleep(.01)
    raise AssertionError(run)


def test_new_http_pdf_run_citations_idempotency_and_session_isolation(tmp_path):
    model = Model()
    with TestClient(prepared(tmp_path, model)) as client:
        sid, did = upload(client, tmp_path)
        body = submission(client, sid)
        response = client.post(f'/api/sessions/{sid}/runs', json=body)
        assert response.status_code == 202, response.text
        rid = response.json()['run_id']
        done = poll(client, sid, rid, {'completed', 'failed'})
        assert done['status'] == 'completed', done
        assert done['request_id'] == 'q1'
        citation = done['answer']['citations'][0]
        assert citation['document_id'] == did
        assert client.get(f"/api/documents/{did}/evidence/{citation['evidence_id']}/preview").status_code == 200
        calls = list(model.calls)
        duplicate = client.post(f'/api/sessions/{sid}/runs', json=body)
        assert duplicate.json()['run_id'] == rid
        assert duplicate.json()['status'] == 'completed'
        assert model.calls == calls
        assert len(client.get(f'/api/sessions/{sid}/runs').json()) == 1
        other = client.post('/api/sessions').json()['session_id']
        for suffix in ('', '/events'):
            assert client.get(f'/api/sessions/{other}/runs/{rid}{suffix}').status_code == 404
        assert client.post(f'/api/sessions/{other}/runs/{rid}/resume', json={}).status_code == 404


def test_restart_keeps_clarification_without_automatic_model_work(tmp_path):
    model = Model()
    with TestClient(prepared(tmp_path, model)) as client:
        sid, did = upload(client, tmp_path)
        run = client.post(f'/api/sessions/{sid}/runs', json=submission(client, sid, question='Clarify first')).json()
        rid = run['run_id']
        assert poll(client, sid, rid, {'waiting', 'failed'})['status'] == 'waiting'
    restarted_model = Model()
    with TestClient(prepared(tmp_path, restarted_model)) as client:
        assert client.get(f'/api/sessions/{sid}/runs/{rid}').json()['status'] == 'waiting'
        assert restarted_model.calls == []
        assert client.post(f'/api/sessions/{sid}/runs/{rid}/resume', json={}).status_code == 422
        assert client.post(f'/api/sessions/{sid}/runs/{rid}/resume', json={'reply': 'A'}).status_code == 202
        assert poll(client, sid, rid, {'completed', 'failed'})['status'] == 'completed'
        events = client.get(f'/api/sessions/{sid}/runs/{rid}/events').json()
        assert sum(event['kind'] == 'answer' for event in events) == 1


def test_stop_inflight_generation_then_explicit_resume(tmp_path):
    model = Model()
    model.block = True
    with TestClient(prepared(tmp_path, model)) as client:
        sid, did = upload(client, tmp_path)
        run = client.post(f'/api/sessions/{sid}/runs', json=submission(client, sid)).json()
        rid = run['run_id']
        assert model.entered.wait(5)
        assert client.post(f'/api/sessions/{sid}/runs/{rid}/stop').json()['status'] == 'stopped'
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = client.get(f'/api/developer/sessions/{sid}/runs/{rid}/events').json()
            if any(event['kind'] == 'error' for event in events):
                break
            time.sleep(.01)
        assert any(event['kind'] == 'error' for event in events)
        assert client.get(f'/api/sessions/{sid}/runs/{rid}').json()['answer'] is None
        model.block = False
        assert client.post(f'/api/sessions/{sid}/runs/{rid}/resume', json={}).status_code == 202
        assert poll(client, sid, rid, {'completed', 'failed'})['status'] == 'completed'


def test_user_events_never_contain_developer_error_payload(tmp_path):
    model = Model()
    model.fail = True
    with TestClient(prepared(tmp_path, model)) as client:
        sid, did = upload(client, tmp_path)
        run = client.post(f'/api/sessions/{sid}/runs', json=submission(client, sid)).json()
        rid = run['run_id']
        assert poll(client, sid, rid, {'failed'})['status'] == 'failed'
        public = client.get(f'/api/sessions/{sid}/runs/{rid}/events')
        technical = client.get(f'/api/developer/sessions/{sid}/runs/{rid}/events')
        assert all(event['channel'] == 'user' for event in public.json())
        assert all(event['channel'] == 'developer' for event in technical.json())
        assert 'RuntimeError' not in public.text
        assert 'PRIVATE_PROVIDER_DIAGNOSTIC' not in public.text + technical.text
        assert any(event['kind'] == 'error' for event in technical.json())
