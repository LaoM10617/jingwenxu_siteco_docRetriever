"""Persist bounded JSON results and provenance; never equate history with reuse."""
from contextlib import contextmanager, nullcontext
import json
import sqlite3

from app.agent_protocol import ScopeSnapshot
from app.documents import DocumentError
from app.sessions import SessionStore


class ArtifactStore:
    def __init__(self, database):
        self.database = database
        self.sessions = SessionStore(database)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS artifact_records (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    artifact_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                    kind TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT,
                    calculation TEXT, unit TEXT, cache_key TEXT,
                    invalidated INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(session_id, artifact_id));
                CREATE TABLE IF NOT EXISTS artifact_dependencies (
                    session_id TEXT NOT NULL, artifact_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    PRIMARY KEY(session_id, artifact_id, version_id),
                    FOREIGN KEY(session_id,artifact_id) REFERENCES artifact_records
                        (session_id,artifact_id) ON DELETE CASCADE);
            ''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _snapshot(db, sid, snapshot_id):
        row = db.execute('SELECT scope FROM turn_snapshots WHERE session_id=? AND snapshot_id=?',
                         (sid, snapshot_id)).fetchone()
        if row is None:
            raise DocumentError('snapshot_not_found', 'Unknown session snapshot.', 404)
        return ScopeSnapshot.model_validate_json(row['scope'])

    def publish(self, sid, artifact_id, snapshot_id, *, kind, payload,
                calculation=None, unit=None, cache_key=None, scope=None, db=None):
        """Publishing belongs to the trusted graph, not a public client route.

        Dependencies conservatively include the entire accepted snapshot. A later
        specialist may narrow them only through a validated result protocol.
        A supplied SQLite Row connection belongs to the caller's active write
        transaction; this method does not commit or close it.
        """
        if (not isinstance(artifact_id, str) or not artifact_id.strip()
                or kind not in {'table', 'numeric', 'chart', 'answer', 'summary'}):
            raise DocumentError('invalid_artifact', 'Invalid artifact identity or kind.', 422)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            raise DocumentError('invalid_artifact', 'Artifact must contain finite JSON data.', 422) from None
        if len(encoded.encode('utf-8')) > 16_777_216:
            raise DocumentError('artifact_too_large', 'Artifact exceeds the inline storage limit.', 413)
        owns_transaction = db is None
        with self._db() if owns_transaction else nullcontext(db) as db:
            if owns_transaction:
                db.execute('BEGIN IMMEDIATE')
            accepted = self._snapshot(db, sid, snapshot_id)
            scope = accepted if scope is None else scope
            if (not set(scope.documents) <= set(accepted.documents)
                    or scope.purpose != accepted.purpose or not set(accepted.filters) <= set(scope.filters)):
                raise DocumentError('invalid_artifact_scope', 'Artifact exceeds the accepted scope.', 422)
            old = db.execute('SELECT * FROM artifact_records WHERE session_id=? AND artifact_id=?',
                             (sid, artifact_id)).fetchone()
            if old is not None:
                if old['invalidated']:
                    raise DocumentError('artifact_invalidated', 'Deleted-source artifacts cannot be republished.', 409)
                if any(old[key] != value for key, value in {
                    'snapshot_id': snapshot_id, 'kind': kind, 'payload': encoded,
                    'calculation': calculation, 'unit': unit, 'cache_key': cache_key,
                    'scope': scope.model_dump_json()}.items()):
                    raise DocumentError('artifact_conflict', 'Artifact identity already has different content.', 409)
                return self._view(db, old)
            self.sessions.validate_sources(db, sid, scope.documents)
            db.execute('''INSERT INTO artifact_records
                (session_id,artifact_id,snapshot_id,kind,scope,payload,calculation,unit,cache_key)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (sid, artifact_id, snapshot_id, kind, scope.model_dump_json(), encoded,
                 calculation, unit, cache_key))
            db.executemany('INSERT INTO artifact_dependencies VALUES (?,?,?)',
                           [(sid, artifact_id, ref.version_id) for ref in scope.documents])
            row = db.execute('SELECT * FROM artifact_records WHERE session_id=? AND artifact_id=?',
                             (sid, artifact_id)).fetchone()
            return self._view(db, row)

    def _view(self, db, row):
        scope = ScopeSnapshot.model_validate_json(row['scope'])
        available = not row['invalidated']
        try:
            self.sessions.validate_sources(db, row['session_id'], scope.documents)
        except DocumentError:
            available = False
        return {'artifact_id': row['artifact_id'], 'version_id': '1', 'kind': row['kind'],
                'snapshot_id': row['snapshot_id'], 'scope': scope.model_dump(mode='json'),
                'payload': json.loads(row['payload']) if row['payload'] is not None else None,
                'calculation': row['calculation'], 'unit': row['unit'],
                'invalidated': bool(row['invalidated']), 'source_available': available}

    def get(self, sid, artifact_id):
        """History remains visible, with explicit source availability."""
        with self._db() as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM artifact_records WHERE session_id=? AND artifact_id=?',
                             (sid, artifact_id)).fetchone()
            if row is None:
                raise DocumentError('artifact_not_found', 'Unknown session artifact.', 404)
            return self._view(db, row)

    def page(self, sid, artifact_id, offset=0, limit=100):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise DocumentError('invalid_pagination', 'Invalid result pagination.', 422)
        artifact = self.get(sid, artifact_id)
        if artifact['kind'] != 'table':
            raise DocumentError('artifact_not_table', 'This artifact is not a result table.', 422)
        payload = artifact['payload']
        if payload is None:
            raise DocumentError('artifact_invalidated', 'The result data was deleted with its source.', 410)
        rows = payload['rows']
        return {'artifact_id': artifact_id, 'columns': payload['columns'], 'rows': rows[offset:offset + limit],
                'total': len(rows), 'offset': offset, 'limit': limit, 'has_more': offset + limit < len(rows),
                'source_available': artifact['source_available'], 'scope': artifact['scope'], 'unit': artifact['unit']}

    def _reuse(self, db, row, current):
        previous = ScopeSnapshot.model_validate_json(row['scope'])
        # Exact scope/filters/purpose: changing the computation population needs
        # a new computation, even if all old input files still exist.
        if (row['invalidated'] or set(previous.documents) != set(current.documents)
                or previous.purpose != current.purpose or previous.filters != current.filters):
            raise DocumentError('artifact_not_reusable', 'Result does not match the current source scope.', 409)
        self.sessions.validate_sources(db, row['session_id'], current.documents)
        return self._view(db, row)

    def reuse(self, sid, artifact_id, snapshot_id):
        with self._db() as db:
            db.execute('BEGIN')
            current = self._snapshot(db, sid, snapshot_id)
            row = db.execute('SELECT * FROM artifact_records WHERE session_id=? AND artifact_id=?',
                             (sid, artifact_id)).fetchone()
            if row is None:
                raise DocumentError('artifact_not_found', 'Unknown session artifact.', 404)
            return self._reuse(db, row, current)

    def cached(self, sid, cache_key, snapshot_id):
        with self._db() as db:
            db.execute('BEGIN')
            current = self._snapshot(db, sid, snapshot_id)
            rows = db.execute('''SELECT * FROM artifact_records
                WHERE session_id=? AND cache_key=? AND invalidated=0 ORDER BY rowid DESC''',
                (sid, cache_key)).fetchall()
            for row in rows:
                try:
                    return self._reuse(db, row, current)
                except DocumentError as exc:
                    if exc.code not in {'artifact_not_reusable', 'source_unavailable'}:
                        raise
            return None

    def invalidate_deleted(self, db, storage_id):
        """Part of the caller's document deletion transaction; no file side effect."""
        db.execute('''UPDATE artifact_records SET invalidated=1,cache_key=NULL,
            payload=CASE WHEN kind='answer' THEN payload ELSE NULL END
            WHERE (session_id,artifact_id) IN (
                SELECT session_id,artifact_id FROM artifact_dependencies WHERE version_id=?)''',
            (storage_id,))
        from app.run_cleanup import invalidate_source
        invalidate_source(db, storage_id)
