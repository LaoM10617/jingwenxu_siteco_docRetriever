import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.agent_state import ProbeRequest, StateProbe


def test_clarification_survives_reopening_without_automatic_execution(tmp_path):
    request = ProbeRequest(session_id='s1', request_id='q1', prompt='Which unit?')
    first = StateProbe(tmp_path).submit(request)
    assert first.status == 'waiting'
    restarted = StateProbe(tmp_path)
    assert restarted.inspect(first.run_id).status == 'waiting'
    assert restarted.inspect(first.run_id).publications == []
    done = restarted.resume(first.run_id, 'EUR')
    assert done.status == 'completed'
    assert done.publications == [{'answer': 'EUR', 'prompt': 'Which unit?'}]
    assert restarted.submit(request) == done
    assert restarted.resume(first.run_id, 'EUR') == done


def child(code, root, *args):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    return subprocess.run([sys.executable, '-c', code, str(root), *args],
                          env=env, text=True, capture_output=True, timeout=30)


def test_real_process_exit_between_business_publish_and_checkpoint_is_replayed(tmp_path):
    first = child('''
import sys
from pathlib import Path
from app.agent_state import StateProbe, ProbeRequest
p = StateProbe(Path(sys.argv[1]))
print(p.submit(ProbeRequest(session_id='s', request_id='q', prompt='Unit?')).run_id)
''', tmp_path)
    assert first.returncode == 0, first.stderr
    run_id = first.stdout.strip()
    crash = child('''
import os, sys
from pathlib import Path
from app.agent_state import StateProbe
p = StateProbe(Path(sys.argv[1]), after_publish=lambda: os._exit(73))
p.resume(sys.argv[2], 'EUR')
''', tmp_path, run_id)
    assert crash.returncode == 73, crash.stderr
    restarted = StateProbe(tmp_path)
    before = restarted.inspect(run_id)
    assert before.status == 'recoverable'
    assert before.publications == [{'answer': 'EUR', 'prompt': 'Unit?'}]
    completed = restarted.resume(run_id)
    assert completed.status == 'completed'
    assert completed.publications == before.publications
    assert restarted.resume(run_id) == completed


def test_request_and_answer_reuse_cannot_change_existing_results(tmp_path):
    probe = StateProbe(tmp_path)
    run = probe.submit(ProbeRequest(session_id='s', request_id='q', prompt='Unit?'))
    with pytest.raises(ValueError, match='different payload'):
        probe.submit(ProbeRequest(session_id='s', request_id='q', prompt='Other?'))
    done = probe.resume(run.run_id, 'EUR')
    with pytest.raises(ValueError, match='differently'):
        probe.resume(run.run_id, 'USD')
    assert probe.inspect(run.run_id) == done
    another = probe.submit(ProbeRequest(session_id='s2', request_id='q', prompt='Other?'))
    assert another.run_id != run.run_id


def test_crash_after_answer_commit_recovers_without_asking_user_again(tmp_path):
    probe = StateProbe(tmp_path)
    run = probe.submit(ProbeRequest(session_id='s', request_id='q', prompt='Unit?'))
    crash = child('''
import os, sys
from pathlib import Path
from app.agent_state import StateProbe
p = StateProbe(Path(sys.argv[1]), after_answer=lambda: os._exit(74))
p.resume(sys.argv[2], 'EUR')
''', tmp_path, run.run_id)
    assert crash.returncode == 74, crash.stderr
    restarted = StateProbe(tmp_path)
    assert restarted.inspect(run.run_id).status == 'recoverable'
    assert restarted.inspect(run.run_id).publications == []
    done = restarted.resume(run.run_id)
    assert done.status == 'completed'
    assert done.publications == [{'answer': 'EUR', 'prompt': 'Unit?'}]


def test_startup_lists_recovery_candidates_without_resuming(tmp_path):
    probe = StateProbe(tmp_path)
    first = probe.submit(ProbeRequest(session_id='s', request_id='one', prompt='Unit?'))
    second = probe.submit(ProbeRequest(session_id='s', request_id='two', prompt='Year?'))
    probe.resume(first.run_id, 'EUR')
    reopened = StateProbe(tmp_path)
    assert reopened.recoverable() == [second]
    assert reopened.inspect(second.run_id).publications == []


def test_concurrent_same_request_has_one_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    probe = StateProbe(tmp_path)
    request = ProbeRequest(session_id='s', request_id='q', prompt='Unit?')
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda _: probe.submit(request), range(4)))
    assert len({run.run_id for run in runs}) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        done = list(pool.map(lambda _: probe.resume(runs[0].run_id, 'EUR'), range(4)))
    assert all(run.status == 'completed' and len(run.publications) == 1 for run in done)


def test_session_serialization_crosses_processes_without_blocking_other_sessions(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release = Event(), Event()

    def hold_publication():
        entered.set()
        assert release.wait(20)

    probe = StateProbe(tmp_path, after_publish=hold_publication)
    run = probe.submit(ProbeRequest(session_id='s1', request_id='q1', prompt='Unit?'))
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    code = '''
import sys
from pathlib import Path
from app.agent_state import StateProbe, ProbeRequest
p = StateProbe(Path(sys.argv[1]))
print('ready', flush=True)
p.submit(ProbeRequest(session_id='s1', request_id='q2', prompt='Unit?'))
print('done', flush=True)
'''
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(probe.resume, run.run_id, 'EUR')
        assert entered.wait(10)
        competing = subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], env=env,
                                     text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert competing.stdout.readline().strip() == 'ready'
            other = StateProbe(tmp_path)
            independent = other.submit(ProbeRequest(session_id='s2', request_id='q1', prompt='Currency?'))
            assert other.resume(independent.run_id, 'USD').status == 'completed'
            assert competing.poll() is None
        finally:
            release.set()
        assert first.result(timeout=10).status == 'completed'
        stdout, stderr = competing.communicate(timeout=15)
        assert competing.returncode == 0, stderr
        assert stdout.strip() == 'done'
