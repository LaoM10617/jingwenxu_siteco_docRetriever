"""Launcher policy and file handling; Docker and the worker process are verified manually."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('siteco_launcher', Path(__file__).resolve().parents[1] / 'scripts' / 'siteco.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_set_env_value_replaces_only_the_key_and_keeps_crlf(tmp_path):
    env = tmp_path / '.env'
    env.write_bytes(b'# comment\r\nEXECUTION_IMAGE=sha256:old\r\nEXECUTION_WORKER_TOKEN=secret=x\r\n')
    launcher.set_env_value(env, 'EXECUTION_IMAGE', 'sha256:new')
    assert env.read_bytes() == b'# comment\r\nEXECUTION_IMAGE=sha256:new\r\nEXECUTION_WORKER_TOKEN=secret=x\r\n'
    assert not list(tmp_path.glob('*.launcher-tmp'))


def test_set_env_value_appends_missing_key_without_touching_similar_names(tmp_path):
    env = tmp_path / '.env'
    env.write_text('EXECUTION_IMAGE_OLD=a\n', encoding='utf-8')
    launcher.set_env_value(env, 'EXECUTION_IMAGE', 'sha256:new')
    assert env.read_text(encoding='utf-8') == 'EXECUTION_IMAGE_OLD=a\nEXECUTION_IMAGE=sha256:new\n'


def test_fingerprint_tracks_content_and_names_but_ignores_caches(tmp_path):
    (tmp_path / 'app' / '__pycache__').mkdir(parents=True)
    (tmp_path / 'app' / 'a.py').write_text('x = 1')
    base = launcher.fingerprint(['app'], root=tmp_path)
    (tmp_path / 'app' / '__pycache__' / 'a.cpython-312.pyc').write_bytes(b'cache')
    (tmp_path / 'app' / 'b.pyc').write_bytes(b'cache')
    assert launcher.fingerprint(['app'], root=tmp_path) == base
    (tmp_path / 'app' / 'a.py').write_text('x = 2')
    changed = launcher.fingerprint(['app'], root=tmp_path)
    assert changed != base
    (tmp_path / 'app' / 'a.py').rename(tmp_path / 'app' / 'c.py')
    assert launcher.fingerprint(['app'], root=tmp_path) != changed
    assert launcher.fingerprint(['app'], extra=['image-a'], root=tmp_path) != launcher.fingerprint(
        ['app'], extra=['image-b'], root=tmp_path)


def test_worker_token_reaches_only_the_environment():
    config = {'backend_port': 8000, 'token': 'TOKEN-VALUE'}
    command = launcher.worker_command(Path('python'), config, 'sha256:abc')
    assert 'TOKEN-VALUE' not in ' '.join(command)
    assert command[command.index('--image') + 1] == 'sha256:abc'
    assert '--stop-file' in command


def test_env_override_warning_names_variables_without_values(capsys):
    file_values = {'EXECUTION_IMAGE': 'sha256:new', 'HOST_PORT': '8000'}
    shell = {'EXECUTION_IMAGE': 'sha256:old', 'HOST_PORT': '8000', 'PATH': 'x'}
    assert launcher.warn_env_overrides(shell, file_values) == ['EXECUTION_IMAGE']
    output = capsys.readouterr().out
    assert 'EXECUTION_IMAGE' in output and 'sha256:old' not in output and 'HOST_PORT' not in output
    assert launcher.warn_env_overrides({}, file_values) == []


def test_env_file_values_ignores_comments_and_quotes(tmp_path):
    env = tmp_path / '.env'
    env.write_text('# HOST_PORT=1\nHOST_PORT="8000"\nTOKEN=a=b\n', encoding='utf-8')
    assert launcher.env_file_values(env) == {'HOST_PORT': '8000', 'TOKEN': 'a=b'}


def test_parse_config_reads_compose_values():
    raw = {'name': 'document-chat', 'services': {
        'backend': {'ports': [{'published': '8001', 'target': 8000}],
                    'volumes': [{'type': 'bind', 'source': '/data/x', 'target': '/app/runtime'}],
                    'environment': {'EXECUTION_IMAGE': 'sha256:abc', 'EXECUTION_WORKER_TOKEN': 't'}},
        'frontend': {'ports': [{'published': '8081', 'target': 8080}]}}}
    config = launcher.parse_config(raw)
    assert (config['backend_port'], config['frontend_port'], config['data_dir']) == (8001, 8081, Path('/data/x'))
    assert (config['image'], config['token']) == ('sha256:abc', 't')


def test_lock_probe_sees_a_worker_holding_the_directory(tmp_path):
    assert launcher.worker_lock_held(tmp_path) is False
    holder = sqlite3.connect(tmp_path / 'worker-lock.sqlite3', timeout=0)
    holder.execute('BEGIN IMMEDIATE')
    try:
        assert launcher.worker_lock_held(tmp_path) is True
    finally:
        holder.close()
    assert launcher.worker_lock_held(tmp_path) is False


def test_managed_worker_rejects_a_reused_pid(tmp_path, monkeypatch):
    state = tmp_path / 'worker.json'
    state.write_text(json.dumps({'pid': 42, 'fingerprint': 'f'}))
    monkeypatch.setattr(launcher, 'WORKER_STATE', state)
    ours = f'python {launcher.WORKER_SCRIPT} --work-dir {launcher.WORK_DIR}'
    assert launcher.managed_worker(lambda pid: ours)['pid'] == 42
    assert launcher.managed_worker(lambda pid: 'notepad.exe') is None
    assert launcher.managed_worker(lambda pid: None) is None


@pytest.mark.parametrize('case, expected', [
    # nothing running yet: start worker, nothing to wait for
    (dict(app_current=False, runner_changed=False, worker_running=False, worker_current=False),
     dict(wait_for_idle=False, stop_worker=False, start_worker=True)),
    # only the frontend changed: keep the worker, but the rebuild may restart the backend
    (dict(app_current=False, runner_changed=False, worker_running=True, worker_current=True),
     dict(wait_for_idle=True, stop_worker=False, start_worker=False)),
    # everything current: touch nothing
    (dict(app_current=True, runner_changed=False, worker_running=True, worker_current=True),
     dict(wait_for_idle=False, stop_worker=False, start_worker=False)),
    # worker code or runner image changed: wait, then replace the worker
    (dict(app_current=True, runner_changed=True, worker_running=True, worker_current=False),
     dict(wait_for_idle=True, stop_worker=True, start_worker=True)),
])
def test_plan(case, expected):
    assert launcher.plan(unmanaged_worker=False, **case) == expected


def test_plan_refuses_to_start_beside_a_manual_worker():
    with pytest.raises(launcher.LauncherError, match='not started by this launcher'):
        launcher.plan(app_current=True, runner_changed=False, worker_running=False,
                      worker_current=False, unmanaged_worker=True)
