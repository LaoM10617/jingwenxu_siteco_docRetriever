"""One entry point for the Docker frontend/backend, the CSV runner image and the host worker.

    python scripts/siteco.py up        build what changed, start everything, verify versions
    python scripts/siteco.py down      stop the worker, then the containers
    python scripts/siteco.py restart
    python scripts/siteco.py status
    python scripts/siteco.py logs
    python scripts/siteco.py check     run the CI checks locally before pushing

Configuration comes from `docker compose config`, so the launcher sees exactly the values
Compose gives the backend (.env plus shell overrides). The worker token is passed to the
worker process environment only: never on a command line, in launcher state or output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env'
RUNNER_TAG = 'siteco-csv-runner:local'
# Keep this directory stable: the worker identity (and the cleanup of its own sandbox
# containers after a crash) is bound to it.
WORK_DIR = ROOT / 'data' / 'demo-worker'
STATE_DIR = ROOT / 'data' / 'launcher'
WORKER_STATE = STATE_DIR / 'worker.json'
WORKER_LOG = STATE_DIR / 'worker.log'
STOP_FILE = STATE_DIR / 'worker.stop'
WORKER_SCRIPT = ROOT / 'scripts' / 'run_python_worker.py'

# Inputs of each built artifact. Over-inclusion only costs an extra restart; omission
# would let stale code keep running, which is the failure this launcher exists to prevent.
BACKEND_INPUTS = ('backend/app', 'pyproject.toml', 'uv.lock', 'backend/Dockerfile')
FRONTEND_INPUTS = ('frontend/src', 'frontend/public', 'frontend/index.html', 'frontend/package.json',
                   'frontend/package-lock.json', 'frontend/tsconfig.json', 'frontend/vite.config.ts',
                   'frontend/nginx.conf', 'frontend/Dockerfile')
# The worker imports from .venv, so a lock change must restart it after `uv sync`.
WORKER_INPUTS = ('backend/app', 'scripts/run_python_worker.py', 'uv.lock')
SKIP_DIRS = {'__pycache__', 'node_modules', 'dist', '.pytest_cache'}
SKIP_SUFFIXES = {'.pyc', '.pyo', '.tsbuildinfo'}


class LauncherError(Exception):
    pass


def run(command, *, capture=True, env=None, check=True, timeout=None):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=capture, timeout=timeout,
                            text=True, encoding='utf-8', errors='replace')
    if check and result.returncode:
        detail = (result.stderr or '').strip()[-2000:] if capture else ''
        raise LauncherError(f'{" ".join(command[:3])} failed (exit {result.returncode}). {detail}'.strip())
    return result


def fingerprint(paths, extra=(), root=ROOT):
    digest = hashlib.sha256()
    files = []
    for name in paths:
        path = root / name
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for directory, dirs, filenames in os.walk(path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                files.extend(Path(directory) / f for f in filenames if Path(f).suffix not in SKIP_SUFFIXES)
    for path in sorted(files, key=lambda p: p.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    for value in extra:
        digest.update(str(value).encode() + b'\0')
    return digest.hexdigest()[:16]


def set_env_value(path, key, value):
    """Replace one KEY=value line atomically; other lines and line endings stay untouched."""
    with open(path, encoding='utf-8', newline='') as source:  # keep \r\n visible
        text = source.read()
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(key + '='):
            lines[i] = f'{key}={value}'
            break
    else:
        lines.append(f'{key}={value}')
    temporary = path.with_name(path.name + '.launcher-tmp')
    temporary.write_text(newline.join(lines) + newline, encoding='utf-8', newline='')
    os.replace(temporary, path)


def parse_config(raw):
    services = raw['services']
    backend, frontend = services['backend'], services['frontend']
    environment = backend.get('environment') or {}
    bind = next(v for v in backend.get('volumes', []) if v.get('target') == '/app/runtime')
    return {'project': raw.get('name', ''),
            'backend_port': int(backend['ports'][0]['published']),
            'frontend_port': int(frontend['ports'][0]['published']),
            'data_dir': Path(bind['source']),
            'image': environment.get('EXECUTION_IMAGE') or '',
            'token': environment.get('EXECUTION_WORKER_TOKEN') or ''}


OVERRIDABLE = ('EXECUTION_IMAGE', 'EXECUTION_WORKER_TOKEN', 'HOST_DATA_DIR', 'HOST_PORT',
               'FRONTEND_PORT', 'COMPOSE_PROJECT_NAME')


def env_file_values(path=ENV_FILE):
    values = {}
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return values
    for line in lines:
        key, separator, value = line.partition('=')
        if separator and not key.lstrip().startswith('#'):
            values[key.strip()] = value.strip().strip('"\'')
    return values


def warn_env_overrides(environment=os.environ, file_values=None):
    """Compose prefers shell variables over .env; leftovers from a manual worker setup
    silently pin an old image or token. Names only, never values."""
    file_values = env_file_values() if file_values is None else file_values
    names = [name for name in OVERRIDABLE if name in environment and environment[name] != file_values.get(name)]
    if names:
        print(f'warning: this shell sets {", ".join(names)}, which override .env. '
              'Open a new terminal or remove them (e.g. Remove-Item Env:NAME).')
    return names


def read_config():
    # stdout contains secrets: parse it in memory, never print it.
    return parse_config(json.loads(run(['docker', 'compose', 'config', '--format', 'json']).stdout))


def http_build(url):
    try:
        with urlopen(url, timeout=3) as response:
            body = response.read(4096)
    except OSError:
        return None
    try:
        return json.loads(body).get('build') or 'unknown'
    except (ValueError, AttributeError):
        return 'unknown'  # reachable, but built before build fingerprints existed


def running_builds(config):
    return (http_build(f'http://127.0.0.1:{config["backend_port"]}/api/health'),
            http_build(f'http://127.0.0.1:{config["frontend_port"]}/version.json'))


def venv_python():
    for candidate in (ROOT / '.venv' / 'Scripts' / 'python.exe', ROOT / '.venv' / 'bin' / 'python'):
        if candidate.is_file():
            return candidate
    raise LauncherError('Project .venv not found. Create it as described in README "Prerequisites".')


def uv():
    path = shutil.which('uv')
    if path is None:
        raise LauncherError('uv not found on PATH. Install the version in pyproject.toml (README "Prerequisites").')
    return path


def sync_environment():
    """Make .venv match uv.lock exactly (ADR 0007: install only from the lock). A no-op when current."""
    run([uv(), 'sync', '--locked', '--quiet'], capture=False)


def worker_command(python, config, image):
    return [str(python), str(WORKER_SCRIPT), '--backend', f'http://127.0.0.1:{config["backend_port"]}',
            '--work-dir', str(WORK_DIR), '--image', image, '--stop-file', str(STOP_FILE)]


def worker_fingerprint(config):
    # The token only enters the digest, so a rotated token restarts the worker without
    # the state file ever holding the token or a direct hash of it.
    return fingerprint(WORKER_INPUTS, extra=(config['image'], config['token'], config['backend_port'], WORK_DIR))


def process_command_line(pid):
    if os.name == 'nt':
        result = run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                      f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'], check=False)
    else:
        result = run(['ps', '-o', 'args=', '-p', str(int(pid))], check=False)
    return result.stdout.strip() or None


def managed_worker(command_line=process_command_line):
    """The recorded worker, only if that PID still runs our worker script (PIDs are reused)."""
    try:
        state = json.loads(WORKER_STATE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    line = command_line(state.get('pid', 0)) or ''
    return state if WORKER_SCRIPT.name in line and str(WORK_DIR) in line else None


def worker_lock_held(work_dir=WORK_DIR):
    """True while any worker (managed or started by hand) owns the work directory."""
    lock = work_dir / 'worker-lock.sqlite3'
    if not lock.exists():
        return False
    connection = sqlite3.connect(lock, timeout=0)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.rollback()
        return False
    except sqlite3.OperationalError as error:
        if 'locked' not in str(error).lower():
            raise
        return True
    finally:
        connection.close()


def worker_owner(work_dir=WORK_DIR):
    database = work_dir / 'worker.sqlite3'
    if not database.exists():
        return None
    connection = sqlite3.connect(database, timeout=5)
    try:
        row = connection.execute('SELECT owner FROM identity').fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()


def active_sandboxes():
    owner = worker_owner()
    if owner is None:
        return []
    return run(['docker', 'container', 'ls', '-q', '--filter',
                'label=siteco.execution.owner=' + owner]).stdout.split()


def wait_until_idle(wait_seconds, force):
    deadline = time.monotonic() + wait_seconds
    busy = active_sandboxes()
    if busy:
        print(f'  worker is running {len(busy)} CSV computation(s); waiting up to {wait_seconds}s ...')
    while busy and time.monotonic() < deadline:
        time.sleep(3)
        busy = active_sandboxes()
    if busy and not force:
        raise LauncherError('A CSV computation is still running. Retry later, raise --wait, '
                            'or pass --force to interrupt it (the question can be resumed).')
    if busy:
        print('  --force: interrupting the running computation.')


def stop_worker(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text('stop', encoding='utf-8')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and managed_worker():
        time.sleep(1)
    if managed_worker():
        os.kill(state['pid'], signal.SIGTERM)
        print('  worker did not stop in 60s and was terminated; it cleans up leftovers on next start.')
    STOP_FILE.unlink(missing_ok=True)
    WORKER_STATE.unlink(missing_ok=True)


def start_worker(config, image, worker_fp):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FILE.unlink(missing_ok=True)
    environment = {**os.environ, 'EXECUTION_WORKER_TOKEN': config['token'], 'PYTHONUNBUFFERED': '1'}
    options = {}
    if os.name == 'nt':
        # Own hidden console: survives the launcher's terminal, and docker.exe children
        # inherit the hidden console instead of opening windows.
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = True
    with open(WORKER_LOG, 'ab') as log:
        log.write(f'\n=== {time.strftime("%Y-%m-%d %H:%M:%S")} worker start, image {image[:19]} ===\n'.encode())
        log.flush()
        process = subprocess.Popen(worker_command(venv_python(), config, image), cwd=ROOT, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **options)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and process.poll() is None and not worker_lock_held():
        time.sleep(0.5)
    time.sleep(2)  # an authentication or image rejection surfaces on the first claim
    if process.poll() is not None:
        raise LauncherError(f'Worker exited during startup. Last log lines:\n{tail(WORKER_LOG, 15)}')
    WORKER_STATE.write_text(json.dumps({'pid': process.pid, 'fingerprint': worker_fp, 'image': image,
                                        'work_dir': str(WORK_DIR), 'started_at': time.time()}), encoding='utf-8')


def tail(path, lines):
    try:
        return '\n'.join(path.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
    except OSError:
        return '(no log)'


def plan(*, app_current, runner_changed, worker_running, worker_current, unmanaged_worker):
    """Decide what `up` must touch; pure so the policy can be tested without Docker."""
    if unmanaged_worker:
        raise LauncherError('A worker not started by this launcher owns data/demo-worker. '
                            'Stop it (Ctrl+C in its terminal), then run up again.')
    restart_worker = worker_running and not worker_current
    disruptive = worker_running and (restart_worker or not app_current or runner_changed)
    return {'wait_for_idle': disruptive, 'stop_worker': restart_worker,
            'start_worker': restart_worker or not worker_running}


def check_docker():
    if run(['docker', 'info', '--format', '{{.ServerVersion}}'], check=False).returncode:
        raise LauncherError('Docker is not running. Start Docker Desktop and retry.')


def up(args):
    check_docker()
    venv_python()
    warn_env_overrides()
    config = read_config()
    if not config['data_dir'].is_dir():
        raise LauncherError(f'HOST_DATA_DIR {config["data_dir"]} does not exist. Create it (see deployment notes).')
    if not config['token']:
        raise LauncherError('EXECUTION_WORKER_TOKEN is empty in the Compose configuration (.env).')

    print('[1/5] CSV runner image')
    # Without --provenance=false BuildKit attaches a fresh attestation each time, so even an
    # unchanged runner gets a new image ID and every `up` would restart backend and worker.
    image = run(['docker', 'build', '-q', '--provenance=false', '-t', RUNNER_TAG,
                 '-f', 'runner/Dockerfile', '.']).stdout.strip()
    runner_changed = image != config['image']
    if runner_changed:
        set_env_value(ENV_FILE, 'EXECUTION_IMAGE', image)
        config = read_config()
        if config['image'] != image:
            raise LauncherError('EXECUTION_IMAGE is overridden by a shell environment variable; '
                                'remove it from the environment so .env is used.')
        print(f'  runner changed; .env EXECUTION_IMAGE = {image[:19]}...')
    else:
        print(f'  unchanged ({image[:19]}...)')

    builds = (fingerprint(BACKEND_INPUTS), fingerprint(FRONTEND_INPUTS))
    state = managed_worker()
    worker_fp = worker_fingerprint(config)
    steps = plan(app_current=running_builds(config) == builds, runner_changed=runner_changed,
                 worker_running=state is not None, worker_current=bool(state) and state['fingerprint'] == worker_fp,
                 unmanaged_worker=state is None and worker_lock_held())
    if steps['wait_for_idle']:
        wait_until_idle(args.wait, args.force)
    if steps['stop_worker']:
        print('[2/5] Stopping outdated worker')
        stop_worker(state)
    else:
        print('[2/5] Worker ' + ('up to date' if state else 'not running'))
    # After an outdated worker stopped: a changed uv.lock always makes it outdated, so no
    # running worker holds files that sync replaces.
    sync_environment()

    print('[3/5] Building and starting frontend/backend')
    compose_env = {**os.environ, 'BACKEND_FINGERPRINT': builds[0], 'FRONTEND_FINGERPRINT': builds[1]}
    run(['docker', 'compose', 'build'], capture=False, env=compose_env)
    if not (config['data_dir'] / 'tokenizers').is_dir():
        print('  preparing tokenizer (first start, needs network)')
        run(['docker', 'compose', 'run', '--rm', '--no-deps', 'backend', 'python', '-m',
             'app.prepare_tokenizer', '/app/runtime/tokenizers'], capture=False, env=compose_env)
    run(['docker', 'compose', 'up', '-d', '--wait', '--wait-timeout', '120'], capture=False, env=compose_env)

    print('[4/5] Verifying running versions')
    running = running_builds(config)
    if running != builds:
        raise LauncherError(f'Running builds {running} do not match source {builds}. '
                            'Check `docker compose ps` and `python scripts/siteco.py logs`.')
    print(f'  backend {builds[0]}  frontend {builds[1]}')

    if steps['start_worker']:
        print('[5/5] Starting worker')
        start_worker(config, image, worker_fp)
    else:
        print('[5/5] Worker already current')
    print(f'\nReady: http://127.0.0.1:{config["frontend_port"]}   (worker log: {WORKER_LOG})')


def down(args):
    state = managed_worker()
    if state:
        wait_until_idle(args.wait, args.force)
        print('Stopping worker')
        stop_worker(state)
    elif worker_lock_held():
        print('Note: a worker not started by this launcher is still running; stop it in its terminal.')
    print('Stopping containers')
    run(['docker', 'compose', 'down'], capture=False)


def status(args):
    warn_env_overrides()
    config = read_config()
    builds = (fingerprint(BACKEND_INPUTS), fingerprint(FRONTEND_INPUTS))
    running = running_builds(config)
    for name, port, local, live in (('frontend', config['frontend_port'], builds[1], running[1]),
                                    ('backend', config['backend_port'], builds[0], running[0])):
        verdict = 'not reachable' if live is None else 'current' if live == local else f'OUTDATED (running {live})'
        print(f'{name:9} http://127.0.0.1:{port}  {verdict}')
    image = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', RUNNER_TAG], check=False).stdout.strip()
    print(f'runner    {image[:19] or "not built"}  ' + ('matches .env' if image == config['image'] else 'DIFFERS from .env'))
    state = managed_worker()
    if state:
        current = state['fingerprint'] == worker_fingerprint(config)
        print(f'worker    pid {state["pid"]}  {"current" if current else "OUTDATED"}  '
              f'{len(active_sandboxes())} running computation(s)')
    else:
        print('worker    ' + ('running, NOT managed by launcher' if worker_lock_held() else 'stopped'))


CHECK_RUNNER_TAG = 'siteco-csv-runner:check'
# Same arguments as in CI; the export is a generated file and must match runner/uv.lock.
RUNNER_EXPORT = ('--frozen', '--no-dev', '--no-emit-project', '--no-header', '--format', 'requirements-txt', '--quiet')


def check(args):
    """Local mirror of .github/workflows/ci.yml, to run before a push. Leaves the running
    instance and the runner tag it uses alone; every step runs and the summary decides."""
    check_docker()
    python = venv_python()
    results = []

    def step(name, action):
        print(f'\n=== {name} ===', flush=True)
        try:
            action()
            results.append((name, 'passed'))
        except (LauncherError, subprocess.SubprocessError) as error:
            print(f'error: {error}', file=sys.stderr)
            results.append((name, 'FAILED'))

    def locks():
        run([uv(), 'lock', '--check'], capture=False)
        run([uv(), 'lock', '--check', '--directory', 'runner'], capture=False)
        exported = run([uv(), 'export', '--directory', 'runner', *RUNNER_EXPORT]).stdout
        committed = (ROOT / 'runner' / 'requirements.lock').read_text(encoding='utf-8')
        if exported.replace('\r\n', '\n') != committed.replace('\r\n', '\n'):
            raise LauncherError('runner/requirements.lock differs from runner/uv.lock; regenerate it '
                                f'with `uv export --directory runner {" ".join(RUNNER_EXPORT)} -o requirements.lock`.')
        sync_environment()

    def pytest():
        image = run(['docker', 'build', '-q', '--provenance=false', '-t', CHECK_RUNNER_TAG,
                     '-f', 'runner/Dockerfile', '.']).stdout.strip()
        environment = {**os.environ, 'SITECO_DOCKER_TESTS': '1', 'SITECO_RUNNER_IMAGE': image}
        run([str(python), '-m', 'pytest', '-q', '-p', 'no:cacheprovider'], capture=False, env=environment)

    def images():
        run(['docker', 'compose', 'config', '--quiet'])
        # Same build args as `up`, so a later `up` reuses these layers. The frontend
        # image build runs the TypeScript check and Vite build, so Node is not required.
        compose_env = {**os.environ, 'BACKEND_FINGERPRINT': fingerprint(BACKEND_INPUTS),
                       'FRONTEND_FINGERPRINT': fingerprint(FRONTEND_INPUTS)}
        run(['docker', 'compose', 'build'], capture=False, env=compose_env)

    step('Lock files and environment', locks)
    step('Backend tests incl. Docker isolation and launcher', pytest)
    step('Compose configuration, images and frontend build', images)
    print('\n=== Summary ===')
    for name, result in results:
        print(f'{result:7} {name}')
    if any(result != 'passed' for _, result in results):
        raise LauncherError('check failed')


def logs(args):
    run(['docker', 'compose', 'logs', '--tail', str(args.tail)], capture=False, check=False)
    print(f'\n--- worker ({WORKER_LOG}) ---\n{tail(WORKER_LOG, args.tail)}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('up', 'down', 'restart'):
        command = commands.add_parser(name)
        command.add_argument('--wait', type=int, default=300,
                             help='seconds to wait for a running CSV computation before giving up (default 300)')
        command.add_argument('--force', action='store_true', help='interrupt a running CSV computation')
    commands.add_parser('status')
    commands.add_parser('logs').add_argument('--tail', type=int, default=80)
    commands.add_parser('check', help='run the CI checks locally before pushing')
    args = parser.parse_args(argv)
    try:
        if args.command == 'restart':
            down(args)
            up(args)
        else:
            {'up': up, 'down': down, 'status': status, 'logs': logs, 'check': check}[args.command](args)
    except LauncherError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
