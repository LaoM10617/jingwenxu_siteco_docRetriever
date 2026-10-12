"""Business-owned Python jobs; only a live graph waiter authorizes worker claims."""
from contextlib import contextmanager, nullcontext
import hashlib
import json
import sqlite3
from threading import Lock
import time
from uuid import uuid4

from app.documents import DocumentError
from app.python_executor import ExecutionResult


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


class ExecutionJobs:
    def __init__(self, database, *, poll_seconds=.1, lease_seconds=15, expected_image=None):
        self.database = database
        self.poll_seconds, self.lease_seconds = poll_seconds, lease_seconds
        self.expected_image = expected_image
        self._waiters = set()
        self._guard = Lock()
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS execution_jobs (
                job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES conversation_runs(run_id) ON DELETE CASCADE,
                task_id TEXT NOT NULL, request_hash TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, lease_token TEXT, worker_id TEXT, lease_until REAL,
                result TEXT, created_at REAL NOT NULL)''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def _available(self, db, payload):
        task = payload['task']
        run = db.execute('SELECT stop_requested FROM conversation_runs WHERE run_id=?',
                         (task['run_id'],)).fetchone()
        if run is None or run['stop_requested']:
            return False
        for source in task['scope']['documents']:
            row = db.execute('''SELECT 1 FROM document_versions v
                JOIN documents d ON d.document_id=v.storage_id
                JOIN session_sources s ON s.version_id=v.version_id
                WHERE s.session_id=? AND s.state='active' AND v.deleted=0
                AND d.status='ready' AND v.version_id=? AND v.document_id=?''',
                (task['session_id'], source['version_id'], source['document_id'])).fetchone()
            if row is None:
                return False
        return True

    def execute(self, task, script, inputs, budget):
        """Wait for one explicitly authorized computation, reusing durable results."""
        if not isinstance(script, str) or not 0 < len(script.encode('utf-8')) <= 131072:
            raise ValueError('Script exceeds execution limit')
        for name, value in inputs.items():
            if (not name or name in ('.', '..') or any(c in name for c in '/\\,:\0')
                    or not isinstance(value, str)):
                raise ValueError('Inputs must be text contents keyed by plain filename')
        payload = {'task': task.model_dump(mode='json'), 'script': script, 'inputs': inputs,
                   'image': self.expected_image}
        encoded = _json(payload)
        if len(encoded.encode('utf-8')) > 64 * 1024 * 1024:
            raise ValueError('Execution input exceeds 64 MiB')
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        job_id = hashlib.sha256((task.task_id + ':' + digest).encode()).hexdigest()
        budget.check()
        with self._guard:
            if job_id in self._waiters:
                raise DocumentError('execution_busy', 'This computation is already running.', 409)
            self._waiters.add(job_id)
        started = time.monotonic()
        try:
            with self._db() as db:
                if not self._available(db, payload):
                    raise DocumentError('source_unavailable', 'Execution sources or run are unavailable.', 409)
                existing = db.execute('SELECT * FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
                if existing and existing['result']:
                    previous = ExecutionResult(**json.loads(existing['result']))
                    if previous.cleaned_up and previous.status not in ('cancelled', 'timed_out', 'interrupted'):
                        return previous
                # Only this explicit execute invocation may requeue an interrupted job.
                db.execute('''INSERT INTO execution_jobs
                    (job_id,session_id,run_id,task_id,request_hash,payload,status,created_at)
                    VALUES (?,?,?,?,?,?,'queued',?) ON CONFLICT(job_id) DO UPDATE SET
                    status='queued', lease_token=NULL, worker_id=NULL, lease_until=NULL,result=NULL''',
                    (job_id, task.session_id, task.run_id, task.task_id, digest, encoded, time.time()))
            while True:
                budget.check()
                with self._db() as db:
                    row = db.execute('SELECT * FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
                    if row is None or not self._available(db, payload):
                        raise DocumentError('source_unavailable', 'Execution sources or run are unavailable.', 409)
                    if row['result']:
                        return ExecutionResult(**json.loads(row['result']))
                    if row['status'] == 'interrupted' or (row['status'] == 'leased' and row['lease_until'] < time.time()):
                        db.execute("UPDATE execution_jobs SET status='interrupted' WHERE job_id=?", (job_id,))
                        return ExecutionResult('interrupted', None, {'total': time.monotonic()-started}, False)
                if time.monotonic() - started > task.budget.timeout_seconds:
                    return ExecutionResult('timed_out', None, {'total': time.monotonic()-started}, False)
                time.sleep(self.poll_seconds)
        finally:
            with self._guard:
                self._waiters.discard(job_id)
            with self._db() as db:
                db.execute("UPDATE execution_jobs SET status='interrupted' WHERE job_id=? AND result IS NULL", (job_id,))

    def claim(self, worker_id, image=None):
        if self.expected_image is not None and image != self.expected_image:
            raise DocumentError('execution_image_mismatch', 'Worker image does not match configured runner.', 409)
        with self._guard, self._db() as db:
            active = set(self._waiters)
            rows = db.execute("SELECT * FROM execution_jobs WHERE status='queued' ORDER BY created_at").fetchall()
            for row in rows:
                if row['job_id'] not in active:
                    continue
                payload = json.loads(row['payload'])
                if not self._available(db, payload):
                    continue
                token = uuid4().hex
                db.execute("UPDATE execution_jobs SET status='leased', lease_token=?,worker_id=?,lease_until=? WHERE job_id=?",
                           (token, worker_id, time.time()+self.lease_seconds, row['job_id']))
                return {'job_id': row['job_id'], 'lease_token': token,
                        'lease_seconds': self.lease_seconds, 'script': payload['script'],
                        'inputs': payload['inputs']}
        return None

    def heartbeat(self, job_id, lease_token):
        with self._guard, self._db() as db:
            active = job_id in self._waiters
            row = db.execute('SELECT * FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
            valid = bool(active and row and row['status'] == 'leased' and
                         row['lease_token'] == lease_token and row['lease_until'] >= time.time() and
                         self._available(db, json.loads(row['payload'])))
            if valid:
                db.execute('UPDATE execution_jobs SET lease_until=? WHERE job_id=?',
                           (time.time()+self.lease_seconds, job_id))
            return valid

    def complete(self, job_id, lease_token, result):
        encoded = _json(result)
        if len(encoded.encode()) > 20 * 1024 * 1024:
            raise ValueError('Execution result exceeds limit')
        with self._guard, self._db() as db:
            active = job_id in self._waiters
            row = db.execute('SELECT * FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
            if row is None or row['lease_token'] != lease_token:
                return False
            if row['result']:
                return row['result'] == encoded
            if (not active or row['status'] != 'leased' or row['lease_until'] < time.time()
                    or not self._available(db, json.loads(row['payload']))):
                return False
            db.execute('UPDATE execution_jobs SET status=?,result=? WHERE job_id=?',
                       (result['status'], encoded, job_id))
            return True

    def purge_session(self, session_id, *, db=None):
        with self._db() if db is None else nullcontext(db) as connection:
            connection.execute('DELETE FROM execution_jobs WHERE session_id=?', (session_id,))

    def purge_source(self, version_id, *, db=None):
        with self._db() if db is None else nullcontext(db) as connection:
            for row in connection.execute('SELECT job_id,payload FROM execution_jobs').fetchall():
                if any(s['version_id'] == version_id for s in json.loads(row['payload'])['task']['scope']['documents']):
                    connection.execute('DELETE FROM execution_jobs WHERE job_id=?', (row['job_id'],))
