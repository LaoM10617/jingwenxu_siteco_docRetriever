import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.agent_protocol import TaskPackage, ScopeSnapshot
from app.execution_jobs import ExecutionJobs
from app.questions import QuestionBudget
from app.timing import capture, span
import pytest
from app.documents import DocumentError


def test_pull_execution_is_durable_and_replay_does_not_execute_twice(tmp_path):
    database = tmp_path / 'app.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE conversation_runs(run_id TEXT PRIMARY KEY, stop_requested INTEGER, kind TEXT DEFAULT 'foreground')")
        db.execute("INSERT INTO conversation_runs(run_id,stop_requested) VALUES ('r', 0)")
    jobs = ExecutionJobs(database, poll_seconds=.01)
    task = TaskPackage(session_id='s', turn_id='t', run_id='r', task_id='task',
                       objective='sum', specialist='csv', scope=ScopeSnapshot(documents=()))
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {'a.csv': 'n\n1'}, QuestionBudget())
        for _ in range(100):
            claim = jobs.claim('worker')
            if claim:
                break
            time.sleep(.01)
        assert claim['inputs'] == {'a.csv': 'n\n1'}
        result = {'status': 'completed', 'value': {'sum': 1}, 'seconds': {'total': .1},
                  'cleaned_up': True, 'diagnostic': ''}
        assert jobs.complete(claim['job_id'], claim['lease_token'], result)
        assert jobs.complete(claim['job_id'], claim['lease_token'], result)
        assert future.result(timeout=2).value == {'sum': 1}
    assert not list((tmp_path / 'execution_payloads').iterdir())
    restarted = ExecutionJobs(database)
    assert restarted.claim('worker') is None
    assert restarted.execute(task, 'print(1)', {'a.csv': 'n\n1'}, QuestionBudget()).value == {'sum': 1}


@pytest.fixture
def execution(tmp_path):
    database = tmp_path / 'app.sqlite3'
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE conversation_runs(run_id TEXT PRIMARY KEY, stop_requested INTEGER, kind TEXT DEFAULT 'foreground')")
        db.execute("INSERT INTO conversation_runs(run_id,stop_requested) VALUES ('r', 0)")
    task = TaskPackage(session_id='s', turn_id='t', run_id='r', task_id='task',
                       objective='sum', specialist='csv', scope=ScopeSnapshot(documents=()))
    return ExecutionJobs(database, poll_seconds=.01, lease_seconds=.1), task


def claim_eventually(jobs):
    for _ in range(100):
        claim = jobs.claim('worker')
        if claim:
            return claim
        time.sleep(.01)
    raise AssertionError('No claim')


def test_expired_lease_is_not_requeued_and_late_result_is_rejected(execution):
    jobs, task = execution
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {}, QuestionBudget())
        claim = claim_eventually(jobs)
        assert future.result(timeout=2).status == 'interrupted'
    assert jobs.claim('other') is None
    assert not jobs.heartbeat(claim['job_id'], claim['lease_token'])
    assert not jobs.complete(claim['job_id'], claim['lease_token'],
        {'status': 'completed', 'value': {}, 'seconds': {}, 'cleaned_up': True})
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {}, QuestionBudget())
        retry = claim_eventually(jobs)
        assert retry['job_id'] == claim['job_id']
        assert retry['lease_token'] != claim['lease_token']
        assert not jobs.heartbeat(claim['job_id'], claim['lease_token'])
        assert jobs.complete(retry['job_id'], retry['lease_token'],
            {'status': 'completed', 'value': {}, 'seconds': {}, 'cleaned_up': True})
        assert future.result(timeout=2).status == 'completed'


def test_stop_revokes_worker_before_result_publication(execution):
    jobs, task = execution
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {}, QuestionBudget())
        claim = claim_eventually(jobs)
        with sqlite3.connect(jobs.database) as db:
            db.execute('UPDATE conversation_runs SET stop_requested=1')
        assert not jobs.heartbeat(claim['job_id'], claim['lease_token'])
        with pytest.raises(DocumentError):
            future.result(timeout=2)


def test_new_backend_process_cannot_claim_or_extend_old_jobs(execution):
    jobs, task = execution
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {}, QuestionBudget())
        claim = claim_eventually(jobs)
        restarted = ExecutionJobs(jobs.database)
        assert restarted.claim('other') is None
        assert not restarted.heartbeat(claim['job_id'], claim['lease_token'])
        assert future.result(timeout=2).status == 'interrupted'


@pytest.mark.parametrize('name', ['../secret', 'a/b', 'C:\\secret', '.', 'a,b'])
def test_execution_rejects_host_paths(execution, name):
    jobs, task = execution
    with pytest.raises(ValueError):
        jobs.execute(task, 'print(1)', {name: 'bad'}, QuestionBudget())


def test_image_mismatch_cannot_take_a_job(execution):
    jobs, task = execution
    jobs.expected_image = 'sha256:' + 'a' * 64
    with pytest.raises(DocumentError) as error:
        jobs.claim('worker', 'sha256:' + 'b' * 64)
    assert error.value.code == 'execution_image_mismatch'


def test_deleted_run_cascades_execution_inputs_and_revokes_lease(execution):
    jobs, task = execution
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {'raw.csv': 'private'}, QuestionBudget())
        claim = claim_eventually(jobs)
        with sqlite3.connect(jobs.database) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('DELETE FROM conversation_runs')
        assert not jobs.heartbeat(claim['job_id'], claim['lease_token'])
        with pytest.raises(DocumentError):
            future.result(timeout=2)


def test_explicit_resume_reruns_cancelled_result(execution):
    jobs, task = execution
    with ThreadPoolExecutor() as pool:
        for status in ('cancelled', 'completed'):
            future = pool.submit(jobs.execute, task, 'print(1)', {}, QuestionBudget())
            claim = claim_eventually(jobs)
            assert jobs.complete(claim['job_id'], claim['lease_token'],
                {'status': status, 'value': {} if status == 'completed' else None,
                 'seconds': {}, 'cleaned_up': True})
            assert future.result(timeout=2).status == status


def test_job_timings_separate_host_phases_from_execution_cache_hits(execution):
    jobs, task = execution
    def measured():
        with capture('r', 't') as recorder:
            with span('csv.execute_attempt', task_id='task'):
                result = jobs.execute(task, 'print(1)', {}, QuestionBudget())
            return result, recorder.entries
    with ThreadPoolExecutor() as pool:
        future = pool.submit(measured)
        claim = claim_eventually(jobs)
        assert jobs.complete(claim['job_id'], claim['lease_token'],
            {'status': 'completed', 'value': {}, 'cleaned_up': True,
             'seconds': {'create': .25, 'start_and_execute': 1.5, 'total': 2.0}})
        result, fresh = future.result(timeout=2)
    attempt = next(e for e in fresh if e['stage'] == 'csv.execute_attempt')
    job = next(e for e in fresh if e['stage'] == 'execution.job')
    assert job['cache_hit'] is False and job['job_id'] == claim['job_id']
    assert job['parent_span_id'] == attempt['span_id'] and job['task_id'] == 'task'
    host = {e['stage']: e for e in fresh if e['clock_domain'] == 'host'}
    assert {stage: e['duration_ms'] for stage, e in host.items()} == {
        'execution.host.create': 250, 'execution.host.start_and_execute': 1500, 'execution.host.total': 2000}
    assert all(e['parent_span_id'] == job['span_id'] and e['job_id'] == claim['job_id'] for e in host.values())
    # A reused result ran in an earlier attempt: its host phases must not be counted again.
    _, replay = measured()
    assert [(e['stage'], e['cache_hit']) for e in replay if e['stage'].startswith('execution.')] == [
        ('execution.job', True)]


def test_completion_report_is_recorded_once_and_only_for_its_lease(execution):
    jobs, task = execution
    with sqlite3.connect(jobs.database) as db:
        db.execute('CREATE TABLE conversation_events (event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, '
                   'channel TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
    report = str(uuid4())
    with ThreadPoolExecutor() as pool:
        future = pool.submit(jobs.execute, task, 'print(1)', {}, QuestionBudget())
        claim = claim_eventually(jobs)
        # Not yet accepted: no completion exists that the report could describe.
        assert not jobs.record_worker_timing(claim['job_id'], claim['lease_token'], report,
                                             {'host_completion_report': .5})
        assert jobs.complete(claim['job_id'], claim['lease_token'],
            {'status': 'completed', 'value': {}, 'seconds': {}, 'cleaned_up': True})
        future.result(timeout=2)
    assert not jobs.record_worker_timing(claim['job_id'], 'x' * 32, report, {'host_completion_report': .5})
    assert not jobs.record_worker_timing('missing', claim['lease_token'], report, {'host_completion_report': .5})
    for _ in range(2):
        assert jobs.record_worker_timing(claim['job_id'], claim['lease_token'], report,
                                         {'host_completion_report': .5})
    with sqlite3.connect(jobs.database) as db:
        rows = db.execute('SELECT run_id,channel,kind,payload FROM conversation_events').fetchall()
    assert [(run_id, channel, kind) for run_id, channel, kind, _ in rows] == [('r', 'developer', 'timing')]
    event = json.loads(rows[0][3])
    assert (event['stage'], event['clock_domain'], event['duration_ms'], event['job_id'], event['task_id'],
            event['turn_id']) == ('execution.host_completion_report', 'host', 500, claim['job_id'], 'task', 't')
    assert claim['lease_token'] not in rows[0][3]


def test_legacy_inline_payload_table_keeps_only_finished_results(tmp_path):
    database = tmp_path / 'app.sqlite3'
    task = TaskPackage(session_id='s', turn_id='t', run_id='r', task_id='task',
                       objective='sum', specialist='csv', scope=ScopeSnapshot(documents=()))
    task_dict = task.model_dump(mode='json')
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE conversation_runs(run_id TEXT PRIMARY KEY, stop_requested INTEGER, kind TEXT DEFAULT 'foreground')")
        db.execute("INSERT INTO conversation_runs(run_id,stop_requested) VALUES ('r', 0)")
        db.execute('''CREATE TABLE execution_jobs (job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
            run_id TEXT NOT NULL REFERENCES conversation_runs(run_id) ON DELETE CASCADE,
            task_id TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL,
            status TEXT NOT NULL, lease_token TEXT, worker_id TEXT, lease_until REAL,
            result TEXT, created_at REAL NOT NULL)''')
        payload = json.dumps({'task': task_dict, 'script': 'x', 'inputs': {}, 'image': None})
        result = json.dumps({'status': 'completed', 'value': {'sum': 1}, 'seconds': {}, 'cleaned_up': True})
        db.execute("INSERT INTO execution_jobs VALUES ('done','s','r','task','h',?,'completed',NULL,NULL,NULL,?,1)", (payload, result))
        db.execute("INSERT INTO execution_jobs VALUES ('open','s','r','task','h',?,'leased','t','w',9,NULL,2)", (payload,))
    (tmp_path / 'execution_payloads').mkdir()
    (tmp_path / 'execution_payloads' / 'crash.json.tmp').write_text('{}')
    ExecutionJobs(database)
    ExecutionJobs(database)  # a second start must not migrate again
    with sqlite3.connect(database) as db:
        assert 'payload' not in {row[1] for row in db.execute('PRAGMA table_info(execution_jobs)')}
        rows = db.execute('SELECT job_id,task_json,result FROM execution_jobs').fetchall()
    assert [(job_id, json.loads(task_json), res) for job_id, task_json, res in rows] == [('done', task_dict, result)]
    assert not list((tmp_path / 'execution_payloads').iterdir())
