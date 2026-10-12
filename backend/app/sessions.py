"""Business session state in the document database; graph checkpoints live elsewhere."""
from contextlib import contextmanager, nullcontext
import json
import sqlite3
from uuid import uuid4

from app.agent_protocol import DocumentVersion, ResolvedReference, ScopeSnapshot


def _error(code, message, status=409):
    from app.documents import DocumentError
    return DocumentError(code, message, status)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class SessionStore:
    def __init__(self, database):
        self.database = database
        with self._db(write=True) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY, data_version INTEGER NOT NULL DEFAULT 0,
                    rule_version INTEGER NOT NULL DEFAULT 0, default_sources TEXT,
                    purpose_sources TEXT NOT NULL DEFAULT '{}', focus TEXT);
                CREATE TABLE IF NOT EXISTS document_versions (
                    version_id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
                    storage_id TEXT NOT NULL UNIQUE, content_hash TEXT,
                    deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS session_sources (
                    session_id TEXT NOT NULL, version_id TEXT NOT NULL,
                    state TEXT NOT NULL, PRIMARY KEY(session_id, version_id));
                CREATE TABLE IF NOT EXISTS turn_snapshots (
                    snapshot_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, request TEXT NOT NULL, scope TEXT NOT NULL,
                    data_version INTEGER NOT NULL, rule_version INTEGER NOT NULL,
                    UNIQUE(session_id, request_id));
                CREATE TABLE IF NOT EXISTS session_messages (
                    session_id TEXT NOT NULL, message_id TEXT NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL, dependencies TEXT NOT NULL,
                    PRIMARY KEY(session_id, message_id));
                CREATE TABLE IF NOT EXISTS session_events (
                    event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS session_rule_operations (
                    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    operation_id TEXT NOT NULL, request TEXT NOT NULL, response TEXT NOT NULL,
                    PRIMARY KEY(session_id, operation_id));
            ''')
            db.execute('''INSERT OR IGNORE INTO document_versions
                (version_id, document_id, storage_id, content_hash)
                SELECT document_id, document_id, document_id, content_hash FROM documents''')

    @contextmanager
    def _db(self, *, write=False):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                yield db
        finally:
            db.close()

    def _session(self, db, session_id):
        row = db.execute('SELECT * FROM sessions WHERE session_id=?', (session_id,)).fetchone()
        if row is None:
            raise _error('session_not_found', 'Session not found.', 404)
        return row

    def _view(self, db, session_id):
        row = dict(self._session(db, session_id))
        for field in ('default_sources', 'purpose_sources', 'focus'):
            row[field] = json.loads(row[field]) if row[field] is not None else None
        row['sources'] = [dict(item) for item in db.execute('''
            SELECT v.document_id, v.version_id, COALESCE(d.status, 'deleted') AS status,
                (v.deleted=0 AND d.status='ready' AND s.state='active') AS available
            FROM session_sources s JOIN document_versions v USING(version_id)
            LEFT JOIN documents d ON d.document_id=v.storage_id
            WHERE s.session_id=? ORDER BY s.rowid''', (session_id,))]
        for source in row['sources']:
            source['available'] = bool(source['available'])
        return row

    def create(self):
        session_id = uuid4().hex
        with self._db(write=True) as db:
            db.execute('INSERT INTO sessions(session_id) VALUES (?)', (session_id,))
            return self._view(db, session_id)

    def get(self, session_id):
        with self._db() as db:
            return self._view(db, session_id)

    def list(self):
        with self._db() as db:
            ids = [row[0] for row in db.execute('SELECT session_id FROM sessions ORDER BY rowid')]
            return [self._view(db, session_id) for session_id in ids]

    def delete(self, session_id, *, db=None):
        with (self._db(write=True) if db is None else nullcontext(db)) as db:
            self._session(db, session_id)
            for table in ('session_events', 'session_messages', 'turn_snapshots', 'session_sources', 'sessions'):
                db.execute(f'DELETE FROM {table} WHERE session_id=?', (session_id,))

    @staticmethod
    def _check_version(row, field, expected):
        if row[field] != expected:
            raise _error('session_version_conflict', 'Session changed; refresh before retrying.')

    def register_upload(self, db, storage_id, session_id=None, logical_document_id=None):
        if session_id is not None:
            self._session(db, session_id)
        if logical_document_id is not None and not db.execute(
                'SELECT 1 FROM document_versions WHERE document_id=?', (logical_document_id,)).fetchone():
            raise _error('document_not_found', 'Logical document not found.', 404)
        document = db.execute('SELECT content_hash, status FROM documents WHERE document_id=?',
                              (storage_id,)).fetchone()
        if document is None:
            raise _error('document_not_found', 'Document not found.', 404)
        logical_id = logical_document_id or storage_id
        existing = db.execute('SELECT document_id FROM document_versions WHERE version_id=?', (storage_id,)).fetchone()
        if existing and existing[0] != logical_id:
            raise _error('version_conflict', 'Document version is already registered differently.')
        db.execute('INSERT OR IGNORE INTO document_versions VALUES (?, ?, ?, ?, 0)',
                   (storage_id, logical_id, storage_id, document[0]))
        if session_id is not None:
            active = document[1] == 'ready'
            changed = db.execute('INSERT OR IGNORE INTO session_sources VALUES (?, ?, ?)',
                                 (session_id, storage_id, 'active' if active else 'pending')).rowcount
            if changed and active:
                db.execute('UPDATE sessions SET data_version=data_version+1 WHERE session_id=?', (session_id,))
        return DocumentVersion(document_id=logical_id, version_id=storage_id)

    def document_ready(self, db, storage_id):
        # Called only on an actual status transition. Retried active sources also
        # become available again and must invalidate previously read versions.
        db.execute("UPDATE session_sources SET state='active' WHERE version_id=? AND state='pending'", (storage_id,))
        self.document_changed(db, storage_id)

    def document_changed(self, db, storage_id):
        db.execute('''UPDATE sessions SET data_version=data_version+1 WHERE session_id IN
            (SELECT session_id FROM session_sources WHERE version_id=?)''', (storage_id,))

    def document_deleted(self, db, storage_id):
        db.execute('UPDATE document_versions SET deleted=1 WHERE version_id=?', (storage_id,))
        self.document_changed(db, storage_id)

    def version(self, storage_id):
        with self._db() as db:
            row = db.execute('''SELECT v.*, COALESCE(d.status, 'deleted') AS status
                FROM document_versions v LEFT JOIN documents d ON d.document_id=v.storage_id
                WHERE v.version_id=?''', (storage_id,)).fetchone()
            if row is None:
                raise _error('document_not_found', 'Document version not found.', 404)
            return dict(row)

    def validate_sources(self, db, session_id, refs):
        self._session(db, session_id)
        for ref in refs:
            row = db.execute('''SELECT 1 FROM session_sources s
                JOIN document_versions v USING(version_id)
                JOIN documents d ON d.document_id=v.storage_id
                WHERE s.session_id=? AND v.document_id=? AND v.version_id=?
                    AND s.state='active' AND v.deleted=0 AND d.status='ready' ''',
                (session_id, ref.document_id, ref.version_id)).fetchone()
            if row is None:
                raise _error('source_unavailable', 'A selected source is not available in this session.')

    def available(self, session_id, sources):
        with self._db() as db:
            self._session(db, session_id)
            try:
                self.validate_sources(db, session_id, sources)
            except Exception as error:
                if getattr(error, 'code', None) == 'source_unavailable':
                    return False
                raise
            return True

    def attach(self, session_id, source, *, expected_data_version):
        with self._db(write=True) as db:
            self._check_version(self._session(db, session_id), 'data_version', expected_data_version)
            if not db.execute('''SELECT 1 FROM document_versions v JOIN documents d ON d.document_id=v.storage_id
                WHERE v.document_id=? AND v.version_id=? AND v.deleted=0 AND d.status='ready' ''',
                (source.document_id, source.version_id)).fetchone():
                raise _error('source_unavailable', 'Document version is not available.')
            changed = db.execute("INSERT OR IGNORE INTO session_sources VALUES (?, ?, 'active')",
                                 (session_id, source.version_id)).rowcount
            if changed:
                db.execute('UPDATE sessions SET data_version=data_version+1 WHERE session_id=?', (session_id,))
            return self._view(db, session_id)

    def remove(self, session_id, source, *, expected_data_version):
        with self._db(write=True) as db:
            self._check_version(self._session(db, session_id), 'data_version', expected_data_version)
            if not db.execute('SELECT 1 FROM document_versions WHERE document_id=? AND version_id=?',
                              (source.document_id, source.version_id)).fetchone():
                raise _error('source_unavailable', 'Document version not found.')
            changed = db.execute('DELETE FROM session_sources WHERE session_id=? AND version_id=?',
                                 (session_id, source.version_id)).rowcount
            if changed:
                db.execute('UPDATE sessions SET data_version=data_version+1 WHERE session_id=?', (session_id,))
            return self._view(db, session_id)

    def set_rules(self, session_id, default_sources, purpose_sources, *, expected_rule_version, operation_id=None, db=None):
        default_sources = None if default_sources is None else tuple(dict.fromkeys(default_sources))
        purpose_sources = {purpose: tuple(dict.fromkeys(refs)) for purpose, refs in purpose_sources.items()}
        encoded = _json({'default_sources': None if default_sources is None else
                         [ref.model_dump() for ref in default_sources],
                         'purpose_sources': {key: [ref.model_dump() for ref in refs]
                                             for key, refs in purpose_sources.items()},
                         'expected_rule_version': expected_rule_version})
        with (self._db(write=True) if db is None else nullcontext(db)) as db:
            if operation_id is not None:
                prior = db.execute('SELECT request, response FROM session_rule_operations '
                                   'WHERE session_id=? AND operation_id=?', (session_id, operation_id)).fetchone()
                if prior:
                    if prior['request'] != encoded:
                        raise _error('request_conflict', 'Rule operation already has different contents.')
                    return json.loads(prior['response'])
            self._check_version(self._session(db, session_id), 'rule_version', expected_rule_version)
            self.validate_sources(db, session_id, default_sources or ())
            for purpose, sources in purpose_sources.items():
                if not purpose.strip():
                    raise _error('invalid_purpose', 'Purpose must not be empty.', 422)
                self.validate_sources(db, session_id, sources)
            default = None if default_sources is None else _json([ref.model_dump() for ref in default_sources])
            purposes = _json({purpose: [ref.model_dump() for ref in refs] for purpose, refs in purpose_sources.items()})
            db.execute('''UPDATE sessions SET default_sources=?, purpose_sources=?, rule_version=rule_version+1
                WHERE session_id=?''', (default, purposes, session_id))
            payload = {'default_sources': None if default is None else json.loads(default),
                       'purpose_sources': json.loads(purposes), 'rule_version': expected_rule_version + 1}
            db.execute('INSERT INTO session_events VALUES (?, ?, ?, ?)',
                       (uuid4().hex, session_id, 'scope_changed', _json(payload)))
            response = self._view(db, session_id)
            if operation_id is not None:
                db.execute('INSERT INTO session_rule_operations VALUES (?, ?, ?, ?)',
                           (session_id, operation_id, encoded, _json(response)))
            return response

    def events(self, session_id):
        with self._db() as db:
            self._session(db, session_id)
            return [dict(row, payload=json.loads(row['payload'])) for row in db.execute(
                'SELECT * FROM session_events WHERE session_id=? ORDER BY rowid', (session_id,))]

    def _scope(self, db, session_id, purpose=None, explicit_sources=None):
        row = self._session(db, session_id)
        rules = json.loads(row['purpose_sources'])
        if explicit_sources is not None:
            refs = tuple(explicit_sources)
        elif purpose in rules:
            refs = tuple(DocumentVersion.model_validate(ref) for ref in rules[purpose])
        elif row['default_sources'] is not None:
            refs = tuple(DocumentVersion.model_validate(ref) for ref in json.loads(row['default_sources']))
        else:
            refs = tuple(DocumentVersion(document_id=ref['document_id'], version_id=ref['version_id'])
                         for ref in self._view(db, session_id)['sources'] if ref['available'])
        self.validate_sources(db, session_id, refs)
        return ScopeSnapshot(documents=refs, purpose=purpose)

    @staticmethod
    def _snapshot_view(row):
        return {key: json.loads(row[key]) if key == 'scope' else row[key]
                for key in ('snapshot_id', 'session_id', 'request_id', 'scope', 'data_version', 'rule_version')}

    def snapshot(self, session_id, request_id, *, purpose=None, explicit_sources=None,
                 expected_data_version, expected_rule_version, filters=(), dependency_scopes=()):
        explicit_sources = None if explicit_sources is None else tuple(dict.fromkeys(explicit_sources))
        encoded = _json({'purpose': purpose, 'filters': filters,
                         'dependency_scopes': [scope.model_dump(mode='json') for scope in dependency_scopes],
                         'explicit_sources': None if explicit_sources is None else
                         [ref.model_dump() for ref in explicit_sources], 'data_version': expected_data_version,
                         'rule_version': expected_rule_version})
        with self._db(write=True) as db:
            row = self._session(db, session_id)
            previous = db.execute('SELECT * FROM turn_snapshots WHERE session_id=? AND request_id=?',
                                  (session_id, request_id)).fetchone()
            if previous:
                if previous['request'] != encoded:
                    raise _error('request_conflict', 'Request identity already has different contents.')
                return self._snapshot_view(previous)
            self._check_version(row, 'data_version', expected_data_version)
            self._check_version(row, 'rule_version', expected_rule_version)
            scope = self._scope(db, session_id, purpose, explicit_sources)
            scope = ScopeSnapshot(documents=scope.documents, purpose=scope.purpose, filters=tuple(filters),
                                  dependency_scopes=tuple(dependency_scopes))
            snapshot_id = uuid4().hex
            db.execute('INSERT INTO turn_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (snapshot_id, session_id, request_id, encoded, scope.model_dump_json(),
                        row['data_version'], row['rule_version']))
            return self._snapshot_view(db.execute('SELECT * FROM turn_snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone())

    def read_snapshot(self, session_id, snapshot_id):
        with self._db() as db:
            self._session(db, session_id)
            row = db.execute('SELECT * FROM turn_snapshots WHERE session_id=? AND snapshot_id=?',
                             (session_id, snapshot_id)).fetchone()
            if row is None:
                raise _error('snapshot_not_found', 'Snapshot not found.', 404)
            return self._snapshot_view(row)

    def set_focus(self, session_id, focus: ResolvedReference | None, *, db=None):
        if focus is not None and not isinstance(focus, ResolvedReference):
            raise _error('invalid_focus', 'Focus must be a resolved reference.', 422)
        with self._db(write=True) if db is None else nullcontext(db) as db:
            self._session(db, session_id)
            db.execute('UPDATE sessions SET focus=? WHERE session_id=?',
                       (None if focus is None else focus.model_dump_json(), session_id))
            return self._view(db, session_id)

    def append_message(self, session_id, message_id, role, content, dependencies=(), *, db=None):
        """Reuse a caller's active write transaction without committing or closing it."""
        if role not in ('user', 'assistant') or not isinstance(content, str) or not message_id:
            raise _error('invalid_message', 'Message identity, role or content is invalid.', 422)
        encoded = _json([ref.model_dump() for ref in dependencies])
        with self._db(write=True) if db is None else nullcontext(db) as db:
            self._session(db, session_id)
            prior = db.execute('SELECT role, content, dependencies FROM session_messages WHERE session_id=? AND message_id=?',
                               (session_id, message_id)).fetchone()
            if prior:
                if tuple(prior) != (role, content, encoded):
                    raise _error('message_conflict', 'Message identity already has different contents.')
                return
            self.validate_sources(db, session_id, dependencies)
            db.execute('INSERT INTO session_messages VALUES (?, ?, ?, ?, ?)',
                       (session_id, message_id, role, content, encoded))

    def messages(self, session_id, *, for_context=False, purpose=None, snapshot_id=None):
        """History retains provenance; context includes only currently usable facts.

        A snapshot ID permits an already accepted explicit turn override. Callers
        cannot supply an arbitrary scope to bypass the session's scope rules.
        """
        with self._db() as db:
            self._session(db, session_id)
            scope = None
            if for_context:
                if snapshot_id is None:
                    scope = self._scope(db, session_id, purpose)
                else:
                    snapshot = db.execute('SELECT scope FROM turn_snapshots WHERE session_id=? AND snapshot_id=?',
                                          (session_id, snapshot_id)).fetchone()
                    if snapshot is None:
                        raise _error('snapshot_not_found', 'Snapshot not found.', 404)
                    scope = ScopeSnapshot.model_validate_json(snapshot['scope'])
            result = []
            for row in db.execute('SELECT * FROM session_messages WHERE session_id=? ORDER BY rowid', (session_id,)):
                message = dict(row)
                message['dependencies'] = json.loads(message['dependencies'])
                refs = tuple(DocumentVersion.model_validate(ref) for ref in message['dependencies'])
                try:
                    self.validate_sources(db, session_id, refs)
                    message['source_available'] = True
                except Exception as error:
                    if getattr(error, 'code', None) != 'source_unavailable':
                        raise
                    message['source_available'] = False
                if scope is not None and (not message['source_available'] or not set(refs).issubset(scope.documents)):
                    continue
                result.append(message)
            return result
