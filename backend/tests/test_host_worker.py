from types import SimpleNamespace
from io import BytesIO

import pytest

from app.host_worker import HostWorker, WorkerClient
from app.python_executor import PYTHON_IMAGE
from app.python_executor import ExecutionResult, PythonExecutor
import sqlite3
import json


def test_worker_lock_excludes_second_controller_and_identity_survives_restart(tmp_path):
    first = HostWorker(tmp_path, None, PYTHON_IMAGE)
    second = HostWorker(tmp_path, None, PYTHON_IMAGE)
    assert first.owner == second.owner
    with first.exclusive():
        with pytest.raises(RuntimeError, match='Another worker'):
            with second.exclusive():
                pass
    with second.exclusive():
        pass


def test_recovery_removes_only_owned_containers_and_never_reexecutes(tmp_path, monkeypatch):
    worker = HostWorker(tmp_path, None, PYTHON_IMAGE)
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stdout=b'abc123\n' if 'ls' in args else b'')
    monkeypatch.setattr('app.host_worker.subprocess.run', run)
    with worker.exclusive():
        worker.recover()
    assert commands == [
        ['docker', 'container', 'ls', '-aq', '--filter', 'label=siteco.execution.owner=' + worker.owner],
        ['docker', 'rm', '--force', 'abc123']]


def test_worker_requires_private_local_http_or_tls_and_a_pinned_image(tmp_path):
    with pytest.raises(ValueError, match='HTTPS'):
        WorkerClient('http://example.org', 'token')
    with pytest.raises(ValueError, match='required'):
        WorkerClient('http://localhost:8000', '')
    with pytest.raises(ValueError, match='pinned'):
        HostWorker(tmp_path, None, 'python:latest')


def test_worker_retries_lost_completion_without_reexecuting_and_erases_result(tmp_path):
    calls = []
    attempts = []
    reports = []
    def post(path, payload):
        if path == '/claim':
            return {'job': {'job_id': 'j', 'lease_token': 't', 'lease_seconds': 15,
                            'script': 'code', 'inputs': {'a.csv': 'n\n5'}}}
        if path.endswith('/complete'):
            attempts.append(payload)
            if len(attempts) == 1:
                raise OSError('lost response')
            return {'accepted': True}
        if path.endswith('/timings'):
            reports.append(payload)
            raise OSError('timing transport unavailable')
        return {'continue': True}
    worker = HostWorker(tmp_path, SimpleNamespace(post=post), PYTHON_IMAGE)
    def execute(script, inputs, **kwargs):
        calls.append((script, inputs['a.csv'].read_text()))
        return ExecutionResult('completed', {'total': 5}, {}, True)
    worker.executor.execute = execute
    assert worker.run_once()
    assert calls == [('code', 'n\n5')]
    assert attempts[0] == attempts[1]
    assert attempts[0]['result']['seconds']['host_claim_and_input_transfer'] >= 0
    assert attempts[0]['result']['seconds']['host_input_write'] >= 0
    assert 'host_completion_report' not in attempts[0]['result']['seconds']
    assert len(reports) == 1
    assert reports[0]['seconds']['host_completion_report'] >= 0
    assert not list((tmp_path / 'inputs').iterdir())
    with sqlite3.connect(worker.database) as db:
        assert db.execute('SELECT status,result FROM jobs').fetchone() == ('acknowledged', None)


def test_recovery_replays_saved_result_but_interrupts_unfinished_work(tmp_path, monkeypatch):
    replies = []
    client = SimpleNamespace(post=lambda path, body: replies.append((path, body)))
    worker = HostWorker(tmp_path, client, PYTHON_IMAGE)
    completed = {'status': 'completed', 'value': {'total': 5}, 'seconds': {}, 'cleaned_up': True}
    with sqlite3.connect(worker.database) as db:
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', ('done', 't', 'old', 'finished', json.dumps(completed)))
        db.execute('INSERT INTO jobs VALUES (?,?,?,?,?)', ('running', 'u', 'other', 'running', None))
    monkeypatch.setattr('app.host_worker.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=b''))
    with worker.exclusive():
        worker.recover()
    assert replies[0][1]['result'] == completed
    assert replies[1][1]['result']['status'] == 'interrupted'
    with sqlite3.connect(worker.database) as db:
        assert db.execute('SELECT count(*) FROM jobs WHERE result IS NOT NULL').fetchone()[0] == 0


@pytest.mark.parametrize(('output', 'exit_code', 'status'), [
    (b'{"sum":5}', 0, 'completed'), (b'not json', 0, 'invalid_output'),
    (b'', 1, 'failed'),
])
def test_executor_reports_disjoint_phases_and_total_including_cleanup(
        tmp_path, monkeypatch, output, exit_code, status):
    # Docker is the external boundary; exercise executor staging, parsing and cleanup.
    monkeypatch.setattr('app.python_executor.subprocess.run',
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=b''))
    process = SimpleNamespace(stdout=BytesIO(output), stderr=BytesIO(b''),
                              returncode=exit_code, poll=lambda: exit_code,
                              wait=lambda **k: exit_code)
    monkeypatch.setattr('app.python_executor.subprocess.Popen', lambda *a, **k: process)
    result = PythonExecutor(tmp_path).execute('print(5)', {})
    assert result.status == status
    assert result.value == ({'sum': 5} if status == 'completed' else None)
    assert result.cleaned_up and not list(tmp_path.iterdir())
    phases = ('staging', 'create', 'start_and_execute', 'result_parse',
              'container_cleanup', 'staging_cleanup')
    assert all(result.seconds[phase] >= 0 for phase in phases)
    assert result.seconds['total'] >= sum(result.seconds[phase] for phase in phases)
