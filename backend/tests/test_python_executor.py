"""Real Docker tests: explicitly enable with SITECO_DOCKER_TESTS=1."""
import os
from pathlib import Path

import pytest

from app.python_executor import PythonExecutor, PYTHON_IMAGE


pytestmark = pytest.mark.skipif(os.getenv('SITECO_DOCKER_TESTS') != '1',
                                reason='requires an explicitly enabled Docker daemon')


def executor(*args, **kwargs):
    kwargs.setdefault('image', os.getenv('SITECO_RUNNER_IMAGE', PYTHON_IMAGE))
    return PythonExecutor(*args, **kwargs)


def test_fixed_script_reads_only_supplied_input(tmp_path):
    source = tmp_path / 'numbers.csv'
    source.write_text('amount\n2\n3\n', encoding='utf-8')
    runner = executor(tmp_path / 'jobs')
    result = runner.execute('''import csv, json
with open('/inputs/data.csv') as stream:
    values = [int(row['amount']) for row in csv.DictReader(stream)]
print(json.dumps({'total': sum(values)}))
''', {'data.csv': source})
    assert result.status == 'completed'
    assert result.value == {'total': 5}
    assert result.cleaned_up
    assert not list((tmp_path / 'jobs').iterdir())


def test_application_secrets_mounts_network_and_writes_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'phase-a-canary-not-a-real-key')
    source = tmp_path / 'input.txt'
    source.write_text('unchanged', encoding='utf-8')
    result = executor(tmp_path / 'jobs').execute('''import json, os, socket
def denied(path):
    try:
        with open(path, 'w') as stream: stream.write('bad')
        return False
    except OSError: return True
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
    network_denied = False
except OSError:
    network_denied = True
print(json.dumps({
    'key_absent': 'GEMINI_API_KEY' not in os.environ,
    'app_absent': not os.path.exists('/app/.env'),
    'socket_absent': not os.path.exists('/var/run/docker.sock'),
    'input_readonly': denied('/inputs/input.txt'),
    'root_readonly': denied('/outside.txt'),
    'network_denied': network_denied,
    'nonroot': os.getuid() != 0,
}))
''', {'input.txt': source})
    assert result.status == 'completed'
    assert result.value and all(result.value.values())
    assert source.read_text() == 'unchanged'


@pytest.mark.parametrize(('script', 'expected'), [
    ('import time; time.sleep(60)', 'timed_out'),
    ("while True: print('x' * 4096, flush=True)", 'output_limit'),
    ("print('not JSON')", 'invalid_output'),
    ("print('{\"value\": NaN}')", 'invalid_output'),
    ("print('{\"value\": 1e999}')", 'invalid_output'),
    ("raise RuntimeError('expected probe failure')", 'failed'),
])
def test_failures_are_explicit_and_cleaned(tmp_path, script, expected):
    result = executor(tmp_path / 'jobs', timeout=2, output_bytes=8192).execute(script, {})
    assert result.status == expected
    assert result.value is None
    assert result.cleaned_up
    assert not list((tmp_path / 'jobs').iterdir())


def test_stop_terminates_active_container(tmp_path):
    from threading import Event, Timer
    cancel = Event()
    timer = Timer(1.5, cancel.set)
    timer.start()
    try:
        result = executor(tmp_path / 'jobs').execute('import time; time.sleep(60)', {}, cancel=cancel)
    finally:
        timer.cancel()
    assert result.status == 'cancelled'
    assert result.cleaned_up


def test_memory_limit_is_real(tmp_path):
    result = executor(tmp_path / 'jobs').execute('x = bytearray(512 * 1024 * 1024)', {})
    assert result.status == 'failed'
    assert result.cleaned_up


def test_uncertain_create_response_still_cleans_container(tmp_path, monkeypatch):
    import subprocess
    original = subprocess.run
    names = []

    def lose_create_response(args, **kwargs):
        response = original(args, **kwargs)
        if args[:2] == ['docker', 'create']:
            assert response.returncode == 0
            names.append(args[args.index('--name') + 1])
            raise subprocess.TimeoutExpired(args, 30)
        return response

    monkeypatch.setattr(subprocess, 'run', lose_create_response)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            executor(tmp_path / 'jobs').execute("print('{}')", {})
        inspection = original(['docker', 'container', 'ls', '-aq', '--filter', f'name=^/{names[0]}$'],
                              capture_output=True, check=True)
        assert inspection.stdout.strip() == b''
    finally:
        for name in names:
            original(['docker', 'rm', '-f', name], capture_output=True)
