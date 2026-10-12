"""Trusted host controller; scripts run only in disposable, unprivileged Docker.

This is not an HTTP endpoint. Only the controller chooses input files and image.
No application environment, Docker socket, or writable host path enters a job.
"""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Thread, Lock
import time
from uuid import uuid4


PYTHON_IMAGE = 'python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e'


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    value: dict | None
    seconds: dict[str, float]
    cleaned_up: bool
    # Diagnostic channel only; callers must not relay script text to user events.
    diagnostic: str = field(default='', repr=False)


class PythonExecutor:
    def __init__(self, work_dir: Path, *, timeout=30.0, output_bytes=1_048_576):
        if timeout <= 0 or not 0 < output_bytes <= 16_777_216:
            raise ValueError('Invalid execution limits')
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.timeout, self.output_bytes = timeout, output_bytes

    def execute(self, script: str, inputs: dict[str, Path], *, cancel: Event | None = None):
        """Return bounded JSON, or an explicit failure; always remove the container.

        Docker availability/cleanup failures raise RuntimeError, never success.
        Input paths are trusted controller capabilities, not model-supplied paths.
        """
        cancel = cancel or Event()
        started = time.monotonic()
        timings = {}
        if cancel.is_set():
            return ExecutionResult('cancelled', None, {'total': 0.0}, True)
        name = 'siteco-python-' + uuid4().hex
        with TemporaryDirectory(prefix='job-', dir=self.work_dir) as directory:
            root = Path(directory)
            staged = root / 'inputs'
            staged.mkdir()
            for filename, source in inputs.items():
                if (not filename or filename in ('.', '..') or
                        any(char in filename for char in '/\\,:') or '\x00' in filename):
                    raise ValueError('Input names must be plain filenames')
                source = Path(source).resolve(strict=True)
                if not source.is_file():
                    raise ValueError('Input must be a regular file')
                shutil.copyfile(source, staged / filename)
            code = root / 'script.py'
            code.write_text(script, encoding='utf-8')
            # Docker --mount uses commas as syntax, so reject ambiguous host paths.
            if ',' in str(root):
                raise ValueError('Execution directory cannot contain commas')
            timings['staging'] = time.monotonic() - started
            args = ['docker', 'create', '--name', name, '--pull', 'never',
                    '--network', 'none', '--read-only', '--user', '65534:65534',
                    '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges=true',
                    '--memory', '256m', '--memory-swap', '256m', '--cpus', '1',
                    '--pids-limit', '64', '--ulimit', 'nofile=64:64',
                    '--log-driver', 'none',
                    '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=16777216,mode=1777',
                    '--mount', f'type=bind,source={staged},target=/inputs,readonly',
                    '--mount', f'type=bind,source={code},target=/script.py,readonly',
                    '--workdir', '/tmp', PYTHON_IMAGE, 'python', '-I', '-B', '/script.py']
            process = None
            try:
                before_create = time.monotonic()
                response = subprocess.run(args, capture_output=True, timeout=30)
                if response.returncode:
                    raise RuntimeError('Docker could not create the isolated Python job')
                timings['create'] = time.monotonic() - before_create
                execution_start = time.monotonic()
                process = subprocess.Popen(['docker', 'start', '--attach', name],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                buffers = [bytearray(), bytearray()]
                overflow = Event()
                guard = Lock()
                total_bytes = 0

                def read(pipe, buffer):
                    nonlocal total_bytes
                    while block := pipe.read(4096):
                        with guard:
                            available = max(0, self.output_bytes - total_bytes)
                            buffer.extend(block[:available])
                            total_bytes += len(block)
                            if total_bytes > self.output_bytes:
                                overflow.set()

                readers = [Thread(target=read, args=(pipe, buffer), daemon=True)
                           for pipe, buffer in zip((process.stdout, process.stderr), buffers)]
                for reader in readers:
                    reader.start()
                status = 'completed'
                while process.poll() is None:
                    if cancel.is_set():
                        status = 'cancelled'
                    elif overflow.is_set():
                        status = 'output_limit'
                    elif time.monotonic() - execution_start >= self.timeout:
                        status = 'timed_out'
                    else:
                        time.sleep(0.02)
                        continue
                    break
                if status != 'completed':
                    self._remove(name)
                process.wait(timeout=10)
                for reader in readers:
                    reader.join(timeout=5)
                if any(reader.is_alive() for reader in readers):
                    raise RuntimeError('Python output stream did not close')
                if status == 'completed' and overflow.is_set():
                    status = 'output_limit'
                timings['start_and_execute'] = time.monotonic() - execution_start
                value = None
                diagnostic = buffers[1].decode('utf-8', errors='replace')
                if status == 'completed':
                    if process.returncode:
                        status = 'failed'
                    else:
                        try:
                            value = json.loads(buffers[0], parse_constant=self._invalid_number,
                                               parse_float=self._finite_float)
                            if not isinstance(value, dict):
                                raise ValueError('Expected JSON object')
                        except (ValueError, UnicodeError):
                            status, value = 'invalid_output', None
            finally:
                try:
                    # A timed-out create can still have succeeded at the daemon.
                    # Query our preallocated name even if no response was received.
                    self._remove(name)
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=10)
                        for pipe in (process.stdout, process.stderr):
                            pipe.close()
            timings['total'] = time.monotonic() - started
            return ExecutionResult(status, value, timings, True, diagnostic)

    @staticmethod
    def _invalid_number(value):
        raise ValueError('Nonfinite JSON number')

    @staticmethod
    def _finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Nonfinite JSON number')
        return result

    @staticmethod
    def _remove(name):
        found = subprocess.run(['docker', 'container', 'ls', '-aq', '--filter', f'name=^/{name}$'],
                               capture_output=True, timeout=15)
        if found.returncode:
            raise RuntimeError(f'Cannot verify Python container {name}; manual cleanup required')
        if not found.stdout.strip():
            return
        response = subprocess.run(['docker', 'rm', '--force', name],
                                  capture_output=True, timeout=15)
        if response.returncode:
            raise RuntimeError(f'Cannot clean up Python container {name}; manual cleanup required')
