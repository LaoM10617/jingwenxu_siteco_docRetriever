"""Business-owned Python jobs; only a live graph waiter authorizes worker claims."""
from contextlib import contextmanager, nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Lock
import time
from uuid import uuid4

from app.db import connect as sqlite_connect
from app.documents import DocumentError
from app.python_executor import ExecutionResult


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


class ExecutionJobs:
    def __init__(self, database, *, poll_seconds=.1, lease_seconds=15, expected_image=None):
        self.database = database
        self.poll_seconds, self.lease_seconds = poll_seconds, lease_seconds
        self.expected_image = expected_image
        self._payload_dir = Path(database).parent / 'execution_payloads'
        self._payload_dir.mkdir(parents=True, exist_ok=True)
        self._waiters = set()
        self._guard = Lock()
        with self._db() as db:
            legacy = 'payload' in {row['name'] for row in db.execute('PRAGMA table_info(execution_jobs)')}
            if legacy:
                db.execute('ALTER TABLE execution_jobs RENAME TO execution_jobs_legacy')
            db.execute('''CREATE TABLE IF NOT EXISTS execution_jobs (
                job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES conversation_runs(run_id) ON DELETE CASCADE,
                task_id TEXT NOT NULL, request_hash TEXT NOT NULL, task_json TEXT NOT NULL,
                status TEXT NOT NULL, lease_token TEXT, worker_id TEXT, lease_until REAL,
                result TEXT, created_at REAL NOT NULL)''')
            if legacy:
                # Finished rows are the reuse cache and keep their result. Unfinished
                # rows are dropped: no execute() survives a restart, so nothing could
                # ever claim them, and their inline scripts/inputs are not migrated.
                db.execute('''INSERT INTO execution_jobs
                    (job_id,session_id,run_id,task_id,request_hash,task_json,status,result,created_at)
                    SELECT job_id,session_id,run_id,task_id,request_hash,json_extract(payload,'$.task'),
                    status,result,created_at FROM execution_jobs_legacy WHERE result IS NOT NULL''')
                db.execute('DROP TABLE execution_jobs_legacy')
        # A payload lives only while its execute() call waits, and none can be
        # waiting yet; anything here (including *.tmp) is left over from a crash.
        for path in self._payload_dir.iterdir():
            path.unlink(missing_ok=True)

    @contextmanager
    def _db(self, *, write=True):
        db = sqlite_connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                if write:
                    db.execute('BEGIN IMMEDIATE')
                yield db
        finally:
            db.close()

    def _payload_path(self, job_id):
        return self._payload_dir / (job_id + '.json')

    def _write_payload(self, job_id, encoded):
        path = self._payload_path(job_id)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(encoded, encoding='utf-8')
        tmp.replace(path)

    def _read_payload(self, job_id):
        return json.loads(self._payload_path(job_id).read_text(encoding='utf-8'))

    def _delete_payload(self, job_id):
        self._payload_path(job_id).unlink(missing_ok=True)

    def _available(self, db, task):
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
        task_dict = task.model_dump(mode='json')
        payload = {'task': task_dict, 'script': script, 'inputs': inputs, 'image': self.expected_image}
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
            # The script/inputs can run tens of MB; writing them to disk here, with
            # no SQLite transaction open, keeps the write transaction below touching
            # only small, fixed-size columns, so it never holds the database lock
            # for as long as the payload itself takes to persist.
            self._write_payload(job_id, encoded)
            with self._db() as db:
                if not self._available(db, task_dict):
                    raise DocumentError('source_unavailable', 'Execution sources or run are unavailable.', 409)
                existing = db.execute('SELECT result FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
                run = db.execute('SELECT kind FROM conversation_runs WHERE run_id=?', (task.run_id,)).fetchone()
                if existing and existing['result']:
                    previous = ExecutionResult(**json.loads(existing['result']))
                    if previous.cleaned_up and previous.status not in ('cancelled', 'timed_out', 'interrupted'):
                        if run['kind'] == 'background':
                            db.execute("UPDATE csv_explorations SET timings=json_set(timings,'$.execution_cache_hits',COALESCE(json_extract(timings,'$.execution_cache_hits'),0)+1) WHERE exploration_id=?", (task.run_id,))
                        return previous
                if run['kind'] == 'background':
                    exploration = db.execute('SELECT execution_calls FROM csv_explorations WHERE exploration_id=?', (task.run_id,)).fetchone()
                    if exploration is None or exploration[0] >= 2:
                        raise DocumentError('exploration_execution_budget', 'The exploration execution budget was reached.', 409)
                    db.execute('UPDATE csv_explorations SET execution_calls=execution_calls+1 WHERE exploration_id=?', (task.run_id,))
                # Only this explicit execute invocation may requeue an interrupted job.
                db.execute('''INSERT INTO execution_jobs
                    (job_id,session_id,run_id,task_id,request_hash,task_json,status,created_at)
                    VALUES (?,?,?,?,?,?,'queued',?) ON CONFLICT(job_id) DO UPDATE SET
                    status='queued', lease_token=NULL, worker_id=NULL, lease_until=NULL,result=NULL''',
                    (job_id, task.session_id, task.run_id, task.task_id, digest, _json(task_dict), time.time()))
            while True:
                budget.check()
                # Plain read: no BEGIN IMMEDIATE, so this poll never competes for the
                # single writer slot that a concurrent large execute() is holding.
                with self._db(write=False) as db:
                    row = db.execute('SELECT status,lease_until,result FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
                    if row is None or not self._available(db, task_dict):
                        raise DocumentError('source_unavailable', 'Execution sources or run are unavailable.', 409)
                    if row['result']:
                        return ExecutionResult(**json.loads(row['result']))
                    expired = row['status'] == 'interrupted' or (row['status'] == 'leased' and row['lease_until'] < time.time())
                if expired:
                    # Escalate to a write transaction only now, and re-check first:
                    # the read above held no lock, so the lease may already have
                    # been renewed or the result already written in the meantime.
                    with self._db() as db:
                        row = db.execute('SELECT status,lease_until,result FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
                        if row and row['result']:
                            return ExecutionResult(**json.loads(row['result']))
                        if row and (row['status'] == 'interrupted' or (row['status'] == 'leased' and row['lease_until'] < time.time())):
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
            # Without a waiter the job can never be claimed again, so its script and
            # inputs (a copy of the source data) are deleted on every exit path.
            self._delete_payload(job_id)

    def claim(self, worker_id, image=None):
        if self.expected_image is not None and image != self.expected_image:
            raise DocumentError('execution_image_mismatch', 'Worker image does not match configured runner.', 409)
        leased = None
        with self._guard, self._db() as db:
            active = set(self._waiters)
            rows = db.execute("SELECT job_id,task_json FROM execution_jobs WHERE status='queued' ORDER BY created_at").fetchall()
            for row in rows:
                if row['job_id'] not in active:
                    continue
                if not self._available(db, json.loads(row['task_json'])):
                    continue
                token = uuid4().hex
                db.execute("UPDATE execution_jobs SET status='leased', lease_token=?,worker_id=?,lease_until=? WHERE job_id=?",
                           (token, worker_id, time.time()+self.lease_seconds, row['job_id']))
                leased = (row['job_id'], token)
                break
        if leased is None:
            return None
        job_id, token = leased
        # Read the (possibly large) script/inputs after the lease commits and the
        # database lock is released, so this never holds up other writers.
        try:
            payload = self._read_payload(job_id)
        except FileNotFoundError:
            # execute() ended between the lease commit and this read and removed
            # the payload; the job is already interrupted, so there is nothing to run.
            return None
        return {'job_id': job_id, 'lease_token': token,
                'lease_seconds': self.lease_seconds, 'script': payload['script'],
                'inputs': payload['inputs']}

    def heartbeat(self, job_id, lease_token):
        with self._guard, self._db() as db:
            active = job_id in self._waiters
            row = db.execute('SELECT * FROM execution_jobs WHERE job_id=?', (job_id,)).fetchone()
            valid = bool(active and row and row['status'] == 'leased' and
                         row['lease_token'] == lease_token and row['lease_until'] >= time.time() and
                         self._available(db, json.loads(row['task_json'])))
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
                    or not self._available(db, json.loads(row['task_json']))):
                return False
            db.execute('UPDATE execution_jobs SET status=?,result=? WHERE job_id=?',
                       (result['status'], encoded, job_id))
            run = db.execute('SELECT kind FROM conversation_runs WHERE run_id=?', (row['run_id'],)).fetchone()
            if run['kind'] == 'background':
                # Includes failed attempts; duplicate delivery returns above.
                db.execute("UPDATE csv_explorations SET timings=json_set(timings,'$.compute_seconds',COALESCE(json_extract(timings,'$.compute_seconds'),0)+?) WHERE exploration_id=?",
                           (result.get('seconds', {}).get('total', 0), row['run_id']))
            return True

    def purge_session(self, session_id, *, db=None):
        with self._db() if db is None else nullcontext(db) as connection:
            job_ids = [row[0] for row in connection.execute(
                'SELECT job_id FROM execution_jobs WHERE session_id=?', (session_id,)).fetchall()]
            connection.execute('DELETE FROM execution_jobs WHERE session_id=?', (session_id,))
        for job_id in job_ids:
            self._delete_payload(job_id)

    def purge_source(self, version_id, *, db=None):
        with self._db() if db is None else nullcontext(db) as connection:
            job_ids = []
            for row in connection.execute('SELECT job_id,task_json FROM execution_jobs').fetchall():
                if any(s['version_id'] == version_id for s in json.loads(row['task_json'])['scope']['documents']):
                    job_ids.append(row['job_id'])
                    connection.execute('DELETE FROM execution_jobs WHERE job_id=?', (row['job_id'],))
        for job_id in job_ids:
            self._delete_payload(job_id)
