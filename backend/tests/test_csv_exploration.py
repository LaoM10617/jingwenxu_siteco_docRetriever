from io import BytesIO
from types import SimpleNamespace
from app.documents import DocumentService
from app.sessions import SessionStore
from app.conversation_runs import ConversationRuns
from app.csv_exploration import CsvExploration
from test_csv_lifecycle import terminal


def test_disabled_exploration_still_profiles_full_table_once_without_chat(tmp_path):
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    bindings = SimpleNamespace(documents=documents, answers=lambda: None)
    runs = ConversationRuns(documents.database, bindings, lambda _: None)
    exploration = CsvExploration(runs)
    exploration.configure(sid, False)
    documents.start()
    try:
        did = documents.submit('values.csv', BytesIO(b'id,value\n001,2\n002,\n003,2\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        exploration.discover()
        items = exploration.list(sid)['items']
        assert len(items) == 1
        assert items[0]['overview']['row_count'] == 3
        assert items[0]['overview']['columns'][1]['blank_count'] == 1
        assert items[0]['status'] == 'disabled'
        exploration.discover()
        assert exploration.list(sid)['items'] == items
        assert runs.list(sid) == []
        assert runs.sessions.messages(sid) == []
    finally:
        documents.stop()


def test_exploration_publishes_one_result_without_chat_and_replay_is_free(tmp_path):
    from app.csv_specialist import CsvSpecialist
    from app.execution_jobs import ExecutionJobs
    from test_csv_specialist import Model, plan
    from threading import Event, Thread
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    model = Model({'candidates': [{'title': 'Sum value', 'objective': 'Sum value excluding blanks, unit count'}]}, plan())
    service = SimpleNamespace(model=model, config_snapshot={}, tools=SimpleNamespace(documents=documents))
    bindings = SimpleNamespace(documents=documents, answers=lambda: service)
    jobs = ExecutionJobs(documents.database, poll_seconds=.005)
    runs = ConversationRuns(documents.database, bindings, lambda _: None,
        csv_specialist_factory=lambda service: CsvSpecialist(service, jobs))
    exploration = CsvExploration(runs)
    stop = Event()
    def worker():
        while not stop.wait(.005):
            job = jobs.claim('worker')
            if job:
                jobs.complete(job['job_id'], job['lease_token'], {'status': 'completed',
                    'value': {'columns': ['sum'], 'rows': [[4]], 'chart': None, 'diagnostics': []},
                    'seconds': {}, 'cleaned_up': True, 'diagnostic': ''})
    runner = Thread(target=worker)
    documents.start()
    runner.start()
    try:
        did = documents.submit('values.csv', BytesIO(b'id,value\n001,2\n002,2\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        exploration.discover()
        identity = exploration.list(sid)['items'][0]['exploration_id']
        exploration.execute(identity)
        done = exploration.get(sid, identity)
        assert done['status'] == 'completed', done
        assert done['candidates'][0]['state'] == 'computed'
        assert done['model_calls'] == 2
        aid = done['candidates'][0]['artifact_ids'][0]
        assert runs.artifacts.get(sid, aid)['payload']['rows'] == [[4]]
        assert runs.list(sid) == []
        assert runs.sessions.messages(sid) == []
        assert runs.sessions.get(sid)['focus'] is None
        exploration.execute(identity)
        assert len(model.calls) == 2
        exploration.select(sid, identity, aid)
        assert runs.sessions.get(sid)['focus']['reference_id'] == aid
        other = runs.sessions.create()['session_id']
        import pytest
        from app.documents import DocumentError
        with pytest.raises(DocumentError):
            exploration.get(other, identity)
        with pytest.raises(DocumentError):
            runs.inspect(sid, identity)
    finally:
        stop.set()
        runner.join(5)
        documents.stop()

import pytest
from app.documents import DocumentError
from test_csv_specialist import Model, Executor, plan, success
from app.csv_specialist import CsvSpecialist
from threading import Event, Thread


@pytest.fixture
def prepared(tmp_path):
    documents = DocumentService(tmp_path)
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    model = Model({'candidates': [{'title': 'Count', 'objective': 'Count all rows'}]}, plan())
    executor = Executor(success())
    service = SimpleNamespace(model=model, config_snapshot={}, tools=SimpleNamespace(documents=documents))
    runs = ConversationRuns(documents.database, SimpleNamespace(documents=documents, answers=lambda: service), lambda _: None,
                            csv_specialist_factory=lambda answer: CsvSpecialist(answer, executor))
    exploration = CsvExploration(runs)
    documents.start()
    did = documents.submit('values.csv', BytesIO(b'id,value\n001,2\n002,2\n'), session_id=sid)['document_id']
    assert terminal(documents, did)['status'] == 'ready'
    exploration.discover()
    identity = exploration.list(sid)['items'][0]['exploration_id']
    yield exploration, runs, sid, identity, model, executor
    documents.stop()


def test_reboot_and_replay_never_reset_paid_budget(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    exploration.execute(identity)
    restarted = CsvExploration(runs)
    assert restarted.get(sid, identity)['model_calls'] == 2
    restarted.execute(identity)
    assert len(model.calls) == 2
    assert runs.context.assemble(sid)['artifact_references'] == []


def test_stop_before_admission_and_reboot_queued_need_explicit_resume(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    restarted = CsvExploration(runs)
    assert restarted.get(sid, identity)['status'] == 'stopped'
    restarted.execute(identity)
    assert model.calls == []
    restarted.resume(sid, identity)
    restarted.stop(sid, identity)
    restarted.execute(identity)
    assert model.calls == []
    restarted.resume(sid, identity)
    restarted.execute(identity)
    assert restarted.get(sid, identity)['status'] == 'completed'


def test_late_provider_response_after_foreground_preemption_is_not_published(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    entered, release = Event(), Event()
    original = model.generate
    def blocked(*args):
        entered.set()
        release.wait(5)
        return original(*args)
    model.generate = blocked
    thread = Thread(target=exploration.execute, args=(identity,))
    thread.start()
    assert entered.wait(3)
    try:
        other = runs.sessions.create()['session_id']
        foreground = runs.submit(other, 'fg', 'hello', expected_data_version=0, expected_rule_version=0)
        assert foreground['status'] == 'queued'
        assert exploration.get(sid, identity)['status'] == 'stopped'
    finally:
        release.set()
        thread.join(5)
    assert exploration.get(sid, identity)['candidates'] == []
    assert exploration.get(sid, identity)['model_calls'] == 1
    assert runs.sessions.messages(sid) == []
    assert runs.list(sid) == []


@pytest.mark.parametrize('action', ['wrong_session', 'completed_resume', 'completed_replay', 'valid_resume'])
def test_only_admitted_foreground_work_preempts_exploration(prepared, action):
    exploration, runs, sid, identity, model, _ = prepared
    foreground = runs.submit(sid, 'prior', 'hello', expected_data_version=1, expected_rule_version=0)
    run_id = foreground['run_id']
    runs.stop(sid, run_id)
    runs._accepted.discard(run_id)
    if action.startswith('completed'):
        with runs._db() as db:
            db.execute("UPDATE conversation_runs SET status='completed' WHERE run_id=?", (run_id,))
    entered, release = Event(), Event()
    original = model.generate
    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    model.generate = blocked
    thread = Thread(target=exploration.execute, args=(identity,))
    thread.start()
    try:
        assert entered.wait(3)
        if action == 'wrong_session':
            other = runs.sessions.create()['session_id']
            with pytest.raises(DocumentError) as error:
                runs.resume(other, run_id)
            assert error.value.status_code == 404
        elif action == 'completed_replay':
            runs.submit(sid, 'prior', 'hello', expected_data_version=1, expected_rule_version=0)
        else:
            runs.resume(sid, run_id)
        assert exploration.get(sid, identity)['status'] == ('stopped' if action == 'valid_resume' else 'running')
    finally:
        release.set()
        thread.join(5)


def test_rules_change_during_model_call_invalidates_and_discards_late_result(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    original = model.generate
    def change(*args):
        runs.sessions.set_rules(sid, (), {}, expected_rule_version=0)
        return original(*args)
    model.generate = change
    exploration.execute(identity)
    item = exploration.get(sid, identity)
    assert item['status'] == 'invalidated'
    assert item['overview'] == {}
    assert item['candidates'] == []
    with pytest.raises(DocumentError):
        exploration.resume(sid, identity)


def test_immediate_resume_does_not_publish_inflight_candidate_or_reset_budget(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    entered, release = Event(), Event()
    original = model.generate
    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    model.generate = delayed
    thread = Thread(target=exploration.execute, args=(identity,))
    thread.start()
    try:
        assert entered.wait(5)
        exploration.stop(sid, identity)
        exploration.resume(sid, identity)
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()
    item = exploration.get(sid, identity)
    assert item['status'] == 'queued'
    assert item['candidates'] == []
    assert item['model_calls'] == 1
    exploration.execute(identity)
    assert len(model.calls) == 1
    assert exploration.get(sid, identity)['model_calls'] == 1
    assert runs.sessions.messages(sid) == []


def test_failed_candidate_call_cannot_be_bought_again_by_resume(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    model.values = [{'candidates': [{'title': 'bad'}]}]
    exploration.execute(identity)
    assert exploration.get(sid, identity)['status'] == 'failed'
    exploration.resume(sid, identity)
    exploration.execute(identity)
    assert len(model.calls) == 1
    assert exploration.get(sid, identity)['model_calls'] == 1


def test_three_call_budget_preserves_unreviewed_result_as_partial(prepared):
    exploration, runs, sid, identity, model, executor = prepared
    model.values = [model.values[0], plan(group_by=['id']),
                    {'decision': 'repair', 'reason': 'fix', 'script': 'fixed()', 'clarification': None}]
    executor.values = [success(), success()]
    exploration.execute(identity)
    item = exploration.get(sid, identity)
    assert item['status'] == 'partial', item
    assert item['model_calls'] == 3
    assert item['candidates'][0]['state'] == 'computed'
    assert item['candidates'][0]['result_status'] == 'partial'
    assert len(executor.calls) == 2
    exploration.resume(sid, identity)
    exploration.execute(identity)
    assert len(model.calls) == 3


def test_removing_source_invalidates_background_cache_and_selection(prepared):
    from app.agent_protocol import DocumentVersion
    exploration, runs, sid, identity, model, _ = prepared
    exploration.execute(identity)
    item = exploration.get(sid, identity)
    aid = item['candidates'][0]['artifact_ids'][0]
    exploration.select(sid, identity, aid)
    assert runs.context.assemble(sid)['artifact_references']
    runs.sessions.remove(sid, DocumentVersion(document_id=item['document_id'], version_id=item['version_id']), expected_data_version=1)
    assert exploration.get(sid, identity)['status'] == 'invalidated'
    assert runs.artifacts.get(sid, aid)['invalidated']
    with pytest.raises(DocumentError):
        exploration.select(sid, identity, aid)


def test_disable_during_provider_call_discards_candidates_and_requires_explicit_resume(prepared):
    exploration, runs, sid, identity, model, _ = prepared
    original = model.generate
    def disable(*args):
        exploration.configure(sid, False)
        return original(*args)
    model.generate = disable
    exploration.execute(identity)
    exploration.configure(sid, True)
    assert exploration.get(sid, identity)['status'] == 'stopped'
    assert exploration.get(sid, identity)['candidates'] == []
    assert len(model.calls) == 1



def test_http_exploration_has_separate_controls_and_hides_internal_runs(tmp_path):
    import time
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    model = Model()
    with TestClient(create_app(Settings(data_dir=tmp_path), model=model)) as client:
        sid = client.post('/api/sessions').json()['session_id']
        assert client.put(f'/api/sessions/{sid}/explorations/settings', json={'enabled': False}).status_code == 200
        documents = client.app.state.documents
        did = documents.submit('values.csv', BytesIO(b'id,value\n001,2\n'), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        deadline = time.monotonic()+5
        items = []
        while time.monotonic() < deadline:
            items = client.get(f'/api/sessions/{sid}/explorations').json()['items']
            if items:
                break
            time.sleep(.05)
        assert items[0]['overview']['row_count'] == 1
        identity = items[0]['exploration_id']
        assert 'diagnostics' not in items[0]
        assert 'timings' in client.get(f'/api/developer/sessions/{sid}/explorations/{identity}').json()
        assert client.post(f'/api/sessions/{sid}/explorations/{identity}/resume').status_code == 409
        assert client.get(f'/api/sessions/{sid}/runs/{identity}').status_code == 404
        assert client.get(f'/api/sessions/{sid}/runs/{identity}/events').status_code == 404
        assert client.post(f'/api/sessions/{sid}/runs/{identity}/resume', json={}).status_code == 404
        assert client.post(f'/api/sessions/{sid}/runs/{identity}/stop').status_code == 404
        assert model.calls == []


def test_two_isolated_execution_attempts_are_lifetime_limit(prepared):
    from app.execution_jobs import ExecutionJobs
    exploration, runs, sid, identity, model, executor = prepared
    jobs = ExecutionJobs(runs.database, poll_seconds=.005)
    runs.csv_specialist_factory = lambda answer: CsvSpecialist(answer, jobs)
    model.values = [model.values[0], plan(), {'decision': 'repair', 'reason': 'retry', 'script': 'fixed()', 'clarification': None}]
    stop = Event()
    claims = []
    def worker():
        while not stop.wait(.005):
            job = jobs.claim('worker')
            if job:
                claims.append(job)
                jobs.complete(job['job_id'], job['lease_token'], {'status': 'failed', 'value': None,
                    'seconds': {'total': .01}, 'cleaned_up': True, 'diagnostic': 'failed script'})
    thread = Thread(target=worker)
    thread.start()
    try:
        exploration.execute(identity)
        item = exploration.get(sid, identity)
        assert item['status'] == 'failed'
        assert item['execution_calls'] == 2
        assert item['model_calls'] == 3
        assert exploration.get(sid, identity, developer=True)['timings']['compute_seconds'] == pytest.approx(.02)
        exploration.resume(sid, identity)
        exploration.execute(identity)
        assert len(claims) == 2
        assert len(model.calls) == 3
        assert exploration.get(sid, identity)['execution_calls'] == 2
        timings = exploration.get(sid, identity, developer=True)['timings']
        assert timings['compute_seconds'] == pytest.approx(.02)
        assert timings['model_cache_hits'] == 2
        assert timings['execution_cache_hits'] == 2
    finally:
        stop.set()
        thread.join(5)


@pytest.mark.parametrize('phase', ['prepare', 'candidates', 'precompute'])
def test_failure_diagnostics_preserve_stage_and_type_without_exception_text(prepared, phase):
    exploration, runs, sid, identity, model, executor = prepared
    def fail(*args, **kwargs):
        raise RuntimeError('sensitive-provider-token')
    if phase == 'prepare':
        runs.bindings.answers = fail
    elif phase == 'candidates':
        model.generate = fail
    else:
        executor.execute = fail
    exploration.execute(identity)
    public = exploration.get(sid, identity)
    assert public['status'] == 'failed'
    assert 'diagnostics' not in public
    diagnostic = exploration.get(sid, identity, developer=True)
    assert diagnostic['diagnostics']['failure'] == {
        'phase': phase, 'type': 'RuntimeError', 'code': 'exploration_failed'}
    assert 'sensitive-provider-token' not in str(diagnostic)
    assert runs.sessions.messages(sid) == []


def test_scheduler_failure_logs_stage_and_type_without_exception_text(prepared, monkeypatch, caplog):
    exploration, _, _, _, _, _ = prepared
    original = exploration.discover
    failed = Event()
    def fail_scan(*, automatic=True):
        if not automatic:
            return original(automatic=False)
        failed.set()
        raise OSError('sensitive-storage-path')
    monkeypatch.setattr(exploration, 'discover', fail_scan)
    exploration.start()
    try:
        assert failed.wait(3)
    finally:
        exploration.shutdown()
    assert 'phase=discover type=OSError' in caplog.text
    assert 'sensitive-storage-path' not in caplog.text
