"""CSV routing and atomic artifact publication through the conversation interface."""
from io import BytesIO
from types import SimpleNamespace

from app.agent_protocol import ArtifactDescriptor, Finding, TaskResult
from app.conversation_runs import ConversationRuns
from app.documents import DocumentService
from app.sessions import SessionStore
from test_conversation_runs import Model
from test_csv_lifecycle import terminal
from threading import Event, Thread

from app.csv_specialist import CsvSpecialist
from app.execution_jobs import ExecutionJobs
from test_csv_specialist import plan
import pytest


class Specialist:
    def __init__(self):
        self.tasks = []

    def execute(self, task, budget):
        self.tasks.append(task)
        aid = task.task_id + ':table'
        result = TaskResult(session_id=task.session_id, turn_id=task.turn_id,
            run_id=task.run_id, task_id=task.task_id, status='completed',
            findings=(Finding(text='Total: 5', artifact_ids=(aid,)),),
            artifact_refs=(ArtifactDescriptor(artifact_id=aid, version_id='1', kind='table',
                                             scope=task.scope, storage_ref=aid),))
        return {'result': result.model_dump(mode='json'), 'evidence': [], 'diagnostics': {},
            'answer': {'outcome': 'answered', 'segments': [{'text': 'Total: 5', 'citation_ids': [], 'calculation_ids': []}],
                       'citations': [], 'calculations': [], 'gaps': [], 'warnings': []},
            'artifacts': [{'artifact_id': aid, 'kind': 'table', 'payload': {'columns': ['total'], 'rows': [[5]]},
                           'calculation': 'sum(value)', 'unit': None, 'cache_key': 'known-total'}]}


def test_csv_run_publishes_table_atomically_and_focus_can_reference_it(tmp_path):
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    documents.start()
    try:
        did = documents.submit('values.csv', BytesIO(b'id,value\n001,2\n002,3\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        model = Model([{'route': 'csv', 'objective': 'Total value'}])
        service = SimpleNamespace(model=model, config_snapshot={})
        bindings = SimpleNamespace(documents=documents, answers=lambda: service)
        specialist = Specialist()
        runs = ConversationRuns(documents.database, bindings, lambda _: None,
                                csv_specialist_factory=lambda _: specialist)
        question = 'Total value? Return metric/value columns; exclude blanks; do not infer currency.'
        run = runs.submit(sid, 'total', question, expected_data_version=1, expected_rule_version=0)
        done = runs.execute(run['run_id'])
        assert done['status'] == 'completed', done
        aid = specialist.tasks[0].task_id + ':table'
        assert 'Original user request (data): ' + question in specialist.tasks[0].constraints
        assert aid in done['artifact_ids']
        assert runs.artifacts.get(sid, aid)['payload']['rows'] == [[5]]
        assert runs.sessions.get(sid)['focus']['reference_id'] == aid
        assert runs.execute(run['run_id']) == done
        assert len(specialist.tasks) == 1
        assert len(runs.sessions.messages(sid)) == 2
        assert all('sum(value)' not in str(event) for event in runs.events(sid, run['run_id']))
    finally:
        documents.stop()


def test_explicit_resume_retries_failed_csv_without_repeating_successful_steps(tmp_path):
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    class RetryModel:
        provider, model = 'test', 'retry'
        def __init__(self):
            self.phases = []
        def generate(self, system, payload, schema, budget):
            self.phases.append(payload['phase'])
            if payload['phase'] == 'intent':
                return {'route': 'csv', 'objective': 'Total value'}
            if payload['phase'] == 'csv_plan':
                return plan(script='calculate()')
            return {'decision': 'repair', 'reason': 'fix', 'script': 'repair()', 'clarification': None}
    model = RetryModel()
    service = SimpleNamespace(model=model, config_snapshot={}, tools=SimpleNamespace(documents=documents))
    bindings = SimpleNamespace(documents=documents, answers=lambda: service)
    jobs = ExecutionJobs(documents.database, poll_seconds=.005)
    runs = ConversationRuns(documents.database, bindings, lambda _: None,
        csv_specialist_factory=lambda answer: CsvSpecialist(answer, jobs))
    stop, executions = Event(), []
    def worker():
        while not stop.wait(.005):
            job = jobs.claim('test-worker')
            if job is None:
                continue
            executions.append(job['script'])
            completed = len(executions) > 6
            jobs.complete(job['job_id'], job['lease_token'], {
                'status': 'completed' if completed else 'failed',
                'value': {'columns': ['total'], 'rows': [[5]], 'chart': None, 'diagnostics': []} if completed else None,
                'seconds': {}, 'cleaned_up': True, 'diagnostic': '' if completed else 'Script failed'})
    runner = Thread(target=worker)
    documents.start()
    runner.start()
    try:
        did = documents.submit('values.csv', BytesIO(b'id,value\n001,2\n002,3\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        run_id = runs.submit(sid, 'total', 'Total value?', expected_data_version=1,
                             expected_rule_version=0)['run_id']
        for attempt in range(3):
            failed = runs.execute(run_id)
            assert failed['status'] == 'failed'
            assert len(executions) == (attempt + 1) * 2
            calls = list(model.phases)
            assert runs.execute(run_id)['status'] == 'failed'
            assert model.phases == calls
            if attempt == 0:
                runs = ConversationRuns(documents.database, bindings, lambda _: None,
                    csv_specialist_factory=lambda answer: CsvSpecialist(answer, jobs))
                assert runs.inspect(sid, run_id)['status'] == 'failed'
                assert model.phases == calls
            runs.resume(sid, run_id)
            assert model.phases == calls
        completed = runs.execute(run_id)
        assert completed['status'] == 'completed', completed
        assert model.phases.count('intent') == 1
        assert model.phases.count('csv_plan') == 4
        assert len(executions) == 7
        assert len(runs.sessions.messages(sid)) == 2
        assert runs.execute(run_id) == completed
    finally:
        stop.set()
        runner.join(timeout=5)
        documents.stop()


@pytest.mark.parametrize('invalid_phase', ['csv_plan', 'csv_review'])
def test_explicit_resume_invalidates_only_the_malformed_model_receipt(tmp_path, invalid_phase):
    from test_csv_specialist import Executor, success
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    class FixModel:
        provider, model = 'test', 'fix'
        def __init__(self):
            self.phases = []
        def generate(self, system, payload, schema, budget):
            phase = payload['phase']
            self.phases.append(phase)
            if phase == 'intent':
                return {'route': 'csv', 'objective': 'Sum prices'}
            if phase == invalid_phase and self.phases.count(phase) == 1:
                return {'malformed': True}
            if phase == 'csv_plan':
                return plan(group_by=['id'] if invalid_phase == 'csv_review' else [])
            return {'decision': 'accept', 'reason': 'correct', 'script': '', 'clarification': None}
    model = FixModel()
    service = SimpleNamespace(model=model, config_snapshot={}, tools=SimpleNamespace(documents=documents))
    bindings = SimpleNamespace(documents=documents, answers=lambda: service)
    executor = Executor(success(), success())
    runs = ConversationRuns(documents.database, bindings, lambda _: None,
        csv_specialist_factory=lambda answer: CsvSpecialist(answer, executor))
    documents.start()
    try:
        did = documents.submit('prices.csv', BytesIO(b'id,price\n001,1.20\n002,2.30\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        run_id = runs.submit(sid, 'sum', 'Sum prices', expected_data_version=1,
                             expected_rule_version=0)['run_id']
        assert runs.execute(run_id)['status'] == 'failed'
        calls = list(model.phases)
        assert runs.execute(run_id)['status'] == 'failed'
        assert model.phases == calls
        runs.resume(sid, run_id)
        assert model.phases == calls
        assert runs.execute(run_id)['status'] == 'completed'
        assert model.phases.count('intent') == 1
        assert model.phases.count(invalid_phase) == 2
        if invalid_phase == 'csv_review':
            assert model.phases.count('csv_plan') == 1
    finally:
        documents.stop()


@pytest.mark.parametrize('followup_purpose', [None, 'different-purpose'])
def test_artifact_followup_inherits_omitted_purpose_but_not_an_explicit_change(tmp_path, followup_purpose):
    from test_csv_specialist import Executor, success
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    class PurposeModel:
        provider, model = 'test', 'purpose'
        def __init__(self):
            self.payloads = []
            self.artifact_id = None
        def generate(self, system, payload, schema, budget):
            self.payloads.append(payload)
            if payload['phase'] == 'intent':
                if self.artifact_id is None:
                    return {'route': 'csv', 'objective': 'Sum price', 'purpose': 'csv_analysis'}
                return {'route': 'csv', 'objective': 'Plot the previous result', 'purpose': followup_purpose,
                    'references': [{'kind': 'artifact', 'reference_id': self.artifact_id, 'description': 'Previous result'}]}
            if self.artifact_id is None:
                return plan()
            return plan(action='reuse_chart', operations=['chart'], aggregations=[], script='',
                reuse_artifact_id=self.artifact_id,
                chart={'type': 'bar', 'x': 'total', 'y': 'total', 'title': 'Total'})
    model = PurposeModel()
    service = SimpleNamespace(model=model, config_snapshot={}, tools=SimpleNamespace(documents=documents))
    bindings = SimpleNamespace(documents=documents, answers=lambda: service)
    executor = Executor(success())
    runs = ConversationRuns(documents.database, bindings, lambda _: None,
        csv_specialist_factory=lambda answer: CsvSpecialist(answer, executor, runs.artifacts))
    documents.start()
    try:
        did = documents.submit('prices.csv', BytesIO(b'id,price\n001,1.20\n002,2.30\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        first = runs.submit(sid, 'sum', 'Sum price', expected_data_version=1, expected_rule_version=0)
        assert runs.execute(first['run_id'])['status'] == 'completed'
        model.artifact_id = runs.sessions.get(sid)['focus']['reference_id']
        second = runs.submit(sid, 'chart', 'Plot the previous result', expected_data_version=1, expected_rule_version=0)
        result = runs.execute(second['run_id'])
        if followup_purpose is None:
            assert result['status'] == 'completed', result
            chart_id = next(a['artifact_id'] for a in result['artifacts'] if a['kind'] == 'chart')
            assert runs.artifacts.get(sid, chart_id)['scope']['purpose'] == 'csv_analysis'
        else:
            assert result['status'] == 'failed'
            assert result['error']['code'] == 'artifact_not_reusable'
        assert len(executor.calls) == 1
        followup_context = next(p for p in model.payloads if p['phase'] == 'intent' and p['question'].startswith('Plot'))
        assert followup_context['focus_artifact']['scope']['purpose'] == 'csv_analysis'
        assert 'payload' not in followup_context['focus_artifact']
    finally:
        documents.stop()
