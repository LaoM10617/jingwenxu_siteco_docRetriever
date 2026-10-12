"""Independent trusted host process. The application never owns the Docker socket."""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from threading import Event, Thread
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from urllib.parse import urlparse
from uuid import uuid4

from app.python_executor import ExecutionResult, PythonExecutor


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WorkerClient:
    def __init__(self, base_url, token):
        parsed = urlparse(base_url)
        if (parsed.scheme not in ('http', 'https') or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError('Invalid backend URL')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote workers require HTTPS')
        if not token:
            raise ValueError('Worker token is required')
        self.base_url = base_url.rstrip('/') + '/api/execution-worker'
        self.token = token

    def post(self, path, payload):
        request = Request(self.base_url + path, data=json.dumps(payload, allow_nan=False).encode(),
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
                          method='POST')
        with build_opener(_NoRedirect).open(request, timeout=10) as response:
            value = response.read(70 * 1024 * 1024 + 1)
        if len(value) > 70 * 1024 * 1024:
            raise ValueError('Worker response exceeds input limit')
        return json.loads(value)


class HostWorker:
    def __init__(self, work_dir, client, image):
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.stop = Event()
        self.database = self.work_dir / 'worker.sqlite3'
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS identity (owner TEXT NOT NULL)')
            row = db.execute('SELECT owner FROM identity').fetchone()
            self.owner = row[0] if row else uuid4().hex
            if not row:
                db.execute('INSERT INTO identity VALUES (?)', (self.owner,))
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, lease_token TEXT NOT NULL, container_name TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT)''')
        self.executor = PythonExecutor(self.work_dir / 'staging', image=image, owner=self.owner,
                                       output_bytes=16_777_216)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database)
        db.execute('PRAGMA secure_delete=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def exclusive(self):
        connection = sqlite3.connect(self.work_dir / 'worker-lock.sqlite3', timeout=0)
        try:
            try:
                connection.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError as error:
                raise RuntimeError('Another worker owns this directory') from error
            yield
        finally:
            connection.close()

    def recover(self):
        """Remove only this persisted worker's containers; never rerun old jobs."""
        found = subprocess.run(['docker', 'container', 'ls', '-aq', '--filter',
                                'label=siteco.execution.owner=' + self.owner],
                               capture_output=True, timeout=15)
        if found.returncode:
            raise RuntimeError('Cannot inspect worker containers; recovery required')
        for container in found.stdout.decode('ascii').split():
            removed = subprocess.run(['docker', 'rm', '--force', container], capture_output=True, timeout=15)
            if removed.returncode:
                raise RuntimeError('Cannot remove worker container; recovery required')
        # These directories belong only to our locked worker instance. Do not follow links.
        for root in (self.work_dir / 'staging', self.work_dir / 'inputs'):
            if root.exists():
                if root.is_symlink() or root.resolve().parent != self.work_dir:
                    raise RuntimeError('Unexpected staging location')
                for child in root.iterdir():
                    if child.is_symlink() or child.resolve().parent != root:
                        raise RuntimeError('Unexpected staging entry')
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        with self._db() as db:
            # A durable result may have lost its HTTP acknowledgment. Replay only the
            # result, never the computation; backend lease fencing decides acceptance.
            rows = db.execute("SELECT job_id,lease_token,result FROM jobs WHERE status!='acknowledged'").fetchall()
            for job_id, token, stored in rows:
                result = json.loads(stored) if stored else asdict(ExecutionResult('interrupted', None, {}, True))
                self.client.post('/' + job_id + '/complete', {'lease_token': token, 'result': result})
                db.execute("UPDATE jobs SET status='acknowledged',result=NULL WHERE job_id=?", (job_id,))

    def run_once(self):
        job = self.client.post('/claim', {'worker_id': self.owner, 'image': self.executor.image})['job']
        if job is None:
            return False
        job_id, token = job['job_id'], job['lease_token']
        name = 'siteco-python-' + uuid4().hex
        with self._db() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,NULL)', (job_id, token, name, 'running'))
        cancel, done = Event(), Event()
        if self.stop.is_set():
            cancel.set()

        def heartbeat():
            while not done.wait(min(1., job['lease_seconds'] / 3)):
                try:
                    if self.stop.is_set() or not self.client.post('/' + job_id + '/heartbeat',
                            {'lease_token': token})['continue']:
                        cancel.set()
                        return
                except (OSError, ValueError):
                    cancel.set()
                    return

        monitor = Thread(target=heartbeat, daemon=True)
        monitor.start()
        root = self.work_dir / 'inputs' / uuid4().hex
        root.mkdir(parents=True)
        try:
            paths = {}
            for filename, contents in job['inputs'].items():
                if (not filename or filename in ('.', '..') or
                        any(c in filename for c in '/\\,:\0') or not isinstance(contents, str)):
                    raise ValueError('Invalid input filename or contents')
                target = root / filename
                target.write_text(contents, encoding='utf-8')
                paths[filename] = target
            try:
                result = self.executor.execute(job['script'], paths, cancel=cancel, container_name=name)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                # Keep staging and stop this worker; restart must prove cleanup first.
                self.stop.set()
                result = ExecutionResult('interrupted', None, {}, False, 'Host execution or cleanup failed')
            encoded = asdict(result)
            with self._db() as db:
                db.execute("UPDATE jobs SET status='finished',result=? WHERE job_id=?",
                           (json.dumps(encoded, allow_nan=False), job_id))
            for attempt in range(3):
                try:
                    self.client.post('/' + job_id + '/complete', {'lease_token': token, 'result': encoded})
                    with self._db() as db:
                        db.execute("UPDATE jobs SET status='acknowledged',result=NULL WHERE job_id=?", (job_id,))
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    time.sleep(1)
        finally:
            done.set()
            monitor.join(timeout=11)
            if not self.stop.is_set():
                shutil.rmtree(root)
        return True

    def run(self):
        with self.exclusive():
            self.recover()
            while not self.stop.is_set():
                try:
                    if not self.run_once():
                        self.stop.wait(1)
                except HTTPError as error:
                    if error.code in (401, 403, 409, 422):
                        raise RuntimeError('Backend rejected worker authentication or execution configuration') from None
                    self.stop.wait(2)
                except OSError:
                    # No job is re-executed here; lease expiry interrupts its waiter.
                    self.stop.wait(2)
