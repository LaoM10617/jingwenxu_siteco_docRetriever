"""Bounded interaction memory; source facts remain in scoped artifacts."""
from contextlib import nullcontext
import json

from pydantic import Field

from app.agent_protocol import ProtocolModel, ScopeSnapshot, SourceScope, DocumentVersion
from app.artifacts import ArtifactStore
from app.documents import DocumentError
from app.sessions import SessionStore


class SummaryItem(ProtocolModel):
    text: str = Field(min_length=1, max_length=500)
    message_ids: tuple[str, ...] = Field(min_length=1, max_length=24)


class InteractionSummary(ProtocolModel):
    goals: tuple[SummaryItem, ...] = Field(default=(), max_length=6)
    decisions: tuple[SummaryItem, ...] = Field(default=(), max_length=6)
    preferences: tuple[SummaryItem, ...] = Field(default=(), max_length=6)
    open_questions: tuple[SummaryItem, ...] = Field(default=(), max_length=6)


class ConversationContext:
    def __init__(self, database):
        self.sessions = SessionStore(database)
        self.artifacts = ArtifactStore(database)
        with self.sessions._db(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_summaries (
                session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                operation_id TEXT NOT NULL, summary TEXT NOT NULL,
                through_message_id TEXT NOT NULL, through_rowid INTEGER NOT NULL,
                PRIMARY KEY(session_id, operation_id))''')
            db.execute('CREATE INDEX IF NOT EXISTS session_message_context ON session_messages(session_id, role)')

    @staticmethod
    def _latest(db, sid):
        return db.execute('''SELECT * FROM conversation_summaries
            WHERE session_id=? ORDER BY through_rowid DESC, rowid ASC LIMIT 1''', (sid,)).fetchone()

    @staticmethod
    def _window(db, sid, watermark):
        recent = list(reversed(db.execute("""SELECT rowid,message_id,role,content
            FROM session_messages WHERE session_id=? AND role='user'
            ORDER BY rowid DESC LIMIT 6""", (sid,)).fetchall()))
        cutoff = recent[0]['rowid'] if recent else 0
        candidates = db.execute("""SELECT rowid,message_id,role,content
            FROM session_messages WHERE session_id=? AND role='user' AND rowid>? AND rowid<?
            ORDER BY rowid LIMIT 24""", (sid, watermark, cutoff)).fetchall()
        bounded, characters = [], 0
        for message in candidates:
            if bounded and characters + len(message['content']) > 24000:
                break
            bounded.append(message)
            characters += len(message['content'])
        pending_count = db.execute("""SELECT COUNT(*) FROM session_messages
            WHERE session_id=? AND role='user' AND rowid>? AND rowid<?""", (sid, watermark, cutoff)).fetchone()[0]
        return recent, bounded, pending_count

    def assemble(self, sid, *, snapshot_id=None, purpose=None, explicit_sources=None):
        """Interaction text identifies intent, never evidence or source permission.

        Unsummarized messages are processed oldest-first in bounded batches. The
        watermark advances only after a validated summary is saved, so a failed
        run or a large pre-existing history cannot silently discard a gap.
        """
        with self.sessions._db() as db:
            self.sessions._session(db, sid)
            latest = self._latest(db, sid)
            watermark = latest['through_rowid'] if latest else 0
            recent, candidates, pending_count = self._window(db, sid, watermark)
            clean = lambda items: [{key: item[key] for key in ('message_id', 'role', 'content')} for item in items]
            return {
                'recent_messages': clean(recent),
                'interaction_summary': json.loads(latest['summary']) if latest else InteractionSummary().model_dump(mode='json'),
                'summary_candidates': clean(candidates),
                'summary_through_message_id': candidates[-1]['message_id'] if candidates else None,
                'summary_pending_count': pending_count,
                'artifact_references': self._artifact_references(db, sid, snapshot_id, purpose, explicit_sources),
                'context_policy': 'Interaction memory is user intent and reference clues only, never source evidence or authorization. Current scope rules are authoritative.',
            }

    def _artifact_references(self, db, sid, snapshot_id, purpose, explicit_sources):
        references = []
        rows = db.execute('''SELECT artifact_id,kind,scope,invalidated FROM artifact_records
            WHERE session_id=? ORDER BY rowid DESC LIMIT 24''', (sid,)).fetchall()
        accepted = self.artifacts._snapshot(db, sid, snapshot_id) if snapshot_id is not None else None
        explicit = None if explicit_sources is None else tuple(
            ref if isinstance(ref, DocumentVersion) else DocumentVersion.model_validate(ref) for ref in explicit_sources)
        for row in rows:
            previous = ScopeSnapshot.model_validate_json(row['scope'])
            available = not row['invalidated']
            try:
                self.sessions.validate_sources(db, sid, previous.documents)
            except DocumentError as error:
                if error.code != 'source_unavailable':
                    raise
                available = False
            try:
                applicable = available and self._applicable(db, sid, previous, accepted, purpose, explicit)
            except DocumentError as error:
                if error.code != 'source_unavailable':
                    raise
                applicable = False
            references.append({'artifact_id': row['artifact_id'], 'kind': row['kind'],
                               'scope': previous.model_dump(mode='json'), 'source_available': available,
                               'invalidated': bool(row['invalidated']), 'applicable': applicable})
        return references

    def _applicable(self, db, sid, previous, accepted, purpose, explicit):
        if accepted is not None:
            return (set(previous.documents) == set(accepted.documents)
                    and previous.purpose == accepted.purpose and previous.filters == accepted.filters
                    and set(previous.dependency_scopes) == set(accepted.dependency_scopes))
        if not previous.dependency_scopes:
            current = self.sessions._scope(db, sid, previous.purpose if purpose is None else purpose, explicit)
            kinds = {row['version_id']: row['original_filename'].lower().rsplit('.', 1)[-1]
                     for row in db.execute('''SELECT v.version_id,d.original_filename FROM document_versions v
                         JOIN documents d ON d.document_id=v.storage_id
                         JOIN session_sources s ON s.version_id=v.version_id WHERE s.session_id=?''', (sid,))}
            previous_kinds = {kinds.get(ref.version_id) for ref in previous.documents}
            current_documents = {ref for ref in current.documents if kinds.get(ref.version_id) in previous_kinds}
            return (set(previous.documents) == current_documents
                    and previous.purpose == current.purpose and previous.filters == current.filters)
        dependencies = {ref for scope in previous.dependency_scopes for ref in scope.documents}
        primary = SourceScope(documents=tuple(ref for ref in previous.documents if ref not in dependencies),
                              purpose=previous.purpose, filters=previous.filters)
        kinds = {row['version_id']: row['original_filename'].lower().rsplit('.', 1)[-1]
                 for row in db.execute("""SELECT v.version_id,d.original_filename FROM document_versions v
                     JOIN documents d ON d.document_id=v.storage_id""")}
        for index, segment in enumerate((primary, *previous.dependency_scopes)):
            selected_purpose = purpose if index == 0 and purpose is not None else segment.purpose
            current = self.sessions._scope(db, sid, selected_purpose, explicit)
            segment_kinds = {kinds.get(ref.version_id) for ref in segment.documents}
            current_documents = {ref for ref in current.documents if kinds.get(ref.version_id) in segment_kinds}
            if (set(segment.documents) != current_documents or segment.purpose != current.purpose
                    or segment.filters != current.filters):
                return False
        return True

    def save_summary(self, sid, operation_id, summary, *, through_message_id, db=None):
        """Save the complete replacement summary, with idempotent run identity.

        The caller folds the previous summary and summary_candidates into the
        existing intent model call. Only user-message provenance is accepted;
        this data is never passed to specialists as a source-fact cache.
        """
        if not isinstance(summary, InteractionSummary):
            summary = InteractionSummary.model_validate(summary)
        encoded = summary.model_dump_json()
        with self.sessions._db(write=True) if db is None else nullcontext(db) as db:
            self.sessions._session(db, sid)
            old = db.execute('SELECT * FROM conversation_summaries WHERE session_id=? AND operation_id=?',
                             (sid, operation_id)).fetchone()
            if old:
                if old['summary'] != encoded or old['through_message_id'] != through_message_id:
                    raise DocumentError('summary_conflict', 'Summary operation has different contents.', 409)
                return
            latest = self._latest(db, sid)
            watermark = latest['through_rowid'] if latest else 0
            through = db.execute('''SELECT rowid FROM session_messages
                WHERE session_id=? AND message_id=? AND role='user' ''', (sid, through_message_id)).fetchone()
            if not operation_id or through is None:
                raise DocumentError('invalid_summary_watermark', 'Summary must identify a covered user message.', 409)
            through_rowid = through['rowid']
            if through_rowid > watermark:
                _, candidates, _ = self._window(db, sid, watermark)
                if not candidates or candidates[-1]['message_id'] != through_message_id:
                    raise DocumentError('invalid_summary_watermark', 'Summary must cover the next pending message batch.', 409)
            # A stopped older run may publish after a newer run advanced memory.
            # Keep its receipt for conflict detection, but _latest selects the
            # highest watermark (first writer on ties), never this stale summary.
            identities = {identity for group in (summary.goals, summary.decisions, summary.preferences, summary.open_questions)
                          for item in group for identity in item.message_ids}
            eligible = set()
            if identities:
                placeholders = ','.join('?' for _ in identities)
                eligible = {row['message_id'] for row in db.execute(f'''SELECT message_id FROM session_messages
                    WHERE session_id=? AND role='user' AND rowid<=? AND message_id IN ({placeholders})''',
                    (sid, through_rowid, *identities))}
            if identities != eligible:
                raise DocumentError('invalid_summary_provenance', 'Summary references must identify covered user messages.', 422)
            if not any((summary.goals, summary.decisions, summary.preferences, summary.open_questions)):
                raise DocumentError('invalid_summary_empty', 'Empty summary cannot discard pending messages or existing memory.', 422)
            db.execute('INSERT INTO conversation_summaries VALUES (?,?,?,?,?)',
                       (sid, operation_id, encoded, through_message_id, through_rowid))

