import pytest
from contextlib import closing
from io import BytesIO
import sqlite3

from app.agent_protocol import DocumentVersion, ResolvedReference
from app.documents import DocumentError, DocumentService
from app.sessions import SessionStore


def test_sessions_persist_without_expiry_and_delete_independently(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    first, second = store.create(), store.create()
    reopened = SessionStore(documents.database)
    assert reopened.get(first['session_id']) == first
    assert len(reopened.list()) == 2
    reopened.delete(first['session_id'])
    assert reopened.list() == [second]


def test_rule_operation_replay_after_later_changes_does_not_apply_twice(tmp_path):
    store = SessionStore(DocumentService(tmp_path).database)
    sid = store.create()['session_id']
    first = store.set_rules(sid, (), {}, expected_rule_version=0, operation_id='run:rules')
    store.set_rules(sid, None, {}, expected_rule_version=1)
    reopened = SessionStore(store.database)
    assert reopened.set_rules(sid, (), {}, expected_rule_version=0, operation_id='run:rules') == first
    assert reopened.get(sid)['rule_version'] == 2
    assert len(reopened.events(sid)) == 2
    with pytest.raises(DocumentError) as error:
        reopened.set_rules(sid, None, {}, expected_rule_version=0, operation_id='run:rules')
    assert error.value.code == 'request_conflict'


def ready_document(documents, store, session_id=None, logical_document_id=None):
    upload = documents.submit('sample.csv', BytesIO(b'id;value\n001;2\n'),
                              session_id=session_id, logical_document_id=logical_document_id)
    storage_id = upload['document_id']
    with closing(sqlite3.connect(documents.database)) as db, db:
        ref = store.register_upload(db, storage_id, session_id, logical_document_id)
        db.execute("UPDATE documents SET status='ready' WHERE document_id=?", (storage_id,))
        store.document_ready(db, storage_id)
    return ref


def test_scopes_are_session_local_and_snapshots_are_immutable(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    other = store.create()['session_id']
    a, b, c = [ready_document(documents, store, sid) for _ in range(3)]
    assert store.get(sid)['data_version'] == 3
    assert store.get(other)['sources'] == []
    store.set_rules(sid, (b,), {'price': (c,)}, expected_rule_version=0)
    def snapshot(request, **kwargs):
        return store.snapshot(sid, request, expected_data_version=3, expected_rule_version=1, **kwargs)
    default = snapshot('default')
    assert default['scope']['documents'] == [b.model_dump()]
    assert snapshot('price', purpose='price')['scope']['documents'] == [c.model_dump()]
    explicit = snapshot('explicit', purpose='price', explicit_sources=(a,))
    assert explicit['scope']['documents'] == [a.model_dump()]
    store.remove(sid, b, expected_data_version=3)
    assert store.read_snapshot(sid, default['snapshot_id']) == default
    assert snapshot('default') == default
    with pytest.raises(DocumentError, match='different'):
        snapshot('default', explicit_sources=(a,))
    with pytest.raises(DocumentError) as error:
        store.snapshot(sid, 'new', expected_data_version=4, expected_rule_version=1)
    assert error.value.code == 'source_unavailable'
    with pytest.raises(DocumentError):
        store.attach(other, DocumentVersion(document_id='wrong', version_id=a.version_id), expected_data_version=0)
    store.attach(other, a, expected_data_version=0)
    assert store.get(other)['sources'][0]['available'] is True


def test_history_keeps_unavailable_sources_but_context_obeys_current_rules(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    a, b = [ready_document(documents, store, sid) for _ in range(2)]
    store.append_message(sid, 'q', 'user', 'Compare these')
    store.append_message(sid, 'a', 'assistant', 'A fact', dependencies=(a,))
    store.append_message(sid, 'b', 'assistant', 'B fact', dependencies=(b,))
    store.set_rules(sid, (a,), {}, expected_rule_version=0)
    store.set_focus(sid, ResolvedReference(kind='document', reference_id=b.version_id, description='Discussing B'))
    assert [message['message_id'] for message in store.messages(sid, for_context=True)] == ['q', 'a']
    store.remove(sid, b, expected_data_version=2)
    history = store.messages(sid)
    assert len(history) == 3
    assert history[-1]['source_available'] is False
    reopened = SessionStore(documents.database)
    assert reopened.get(sid)['focus']['reference_id'] == b.version_id
    assert reopened.messages(sid) == history
    store.append_message(sid, 'a', 'assistant', 'A fact', dependencies=(a,))
    with pytest.raises(DocumentError):
        store.append_message(sid, 'a', 'assistant', 'Changed fact', dependencies=(a,))


def test_document_lifecycle_preserves_history_and_tombstones(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    ref = ready_document(documents, store, sid)
    store.append_message(sid, 'answer', 'assistant', 'Old answer', (ref,))
    snapshot = store.snapshot(sid, 'q', expected_data_version=1, expected_rule_version=0)
    with closing(sqlite3.connect(documents.database)) as db, db:
        db.execute("UPDATE documents SET status='trashed' WHERE document_id=?", (ref.version_id,))
        store.document_changed(db, ref.version_id)
    assert store.get(sid)['data_version'] == 2
    assert not store.available(sid, (ref,))
    assert store.messages(sid, for_context=True, snapshot_id=snapshot['snapshot_id']) == []
    with closing(sqlite3.connect(documents.database)) as db, db:
        db.execute("UPDATE documents SET status='ready' WHERE document_id=?", (ref.version_id,))
        store.document_changed(db, ref.version_id)
    assert store.available(sid, (ref,))
    with closing(sqlite3.connect(documents.database)) as db, db:
        store.document_deleted(db, ref.version_id)
        db.execute('DELETE FROM documents WHERE document_id=?', (ref.version_id,))
    assert store.version(ref.version_id)['deleted'] == 1
    assert store.get(sid)['data_version'] == 4
    assert store.messages(sid)[0]['source_available'] is False
    assert store.read_snapshot(sid, snapshot['snapshot_id']) == snapshot


def test_upload_hook_rolls_back_with_callers_transaction(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    ref = ready_document(documents, store)
    with pytest.raises(RuntimeError):
        with closing(sqlite3.connect(documents.database)) as db, db:
            store.register_upload(db, ref.version_id, sid)
            raise RuntimeError('abort')
    assert store.get(sid)['sources'] == []
    assert store.get(sid)['data_version'] == 0


def test_concurrent_writers_reject_stale_session_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    refs = [ready_document(documents, store) for _ in range(2)]

    def attach(ref):
        try:
            return store.attach(sid, ref, expected_data_version=0)['data_version']
        except DocumentError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attach, refs))
    assert sorted(map(str, results)) == ['1', 'session_version_conflict']
    assert len(store.get(sid)['sources']) == 1


def test_existing_documents_are_catalogued_without_implicit_session_membership(tmp_path):
    documents = DocumentService(tmp_path)
    uploaded = documents.submit('legacy.csv', BytesIO(b'id\n001\n'))
    store = SessionStore(documents.database)
    assert store.version(uploaded['document_id'])['content_hash'] == uploaded['content_hash']
    sid = store.create()['session_id']
    assert store.get(sid)['sources'] == []
    store.delete(sid)
    assert documents.get(uploaded['document_id'])['document_id'] == uploaded['document_id']


def test_new_version_does_not_replace_rules_or_existing_snapshots(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    old = ready_document(documents, store, sid)
    store.set_rules(sid, (old,), {}, expected_rule_version=0)
    before = store.snapshot(sid, 'before', expected_data_version=1, expected_rule_version=1)
    new = ready_document(documents, store, sid, logical_document_id=old.document_id)
    assert old.document_id == new.document_id and old.version_id != new.version_id
    assert store.get(sid)['data_version'] == 2
    current = store.snapshot(sid, 'after', expected_data_version=2, expected_rule_version=1)
    assert current['scope']['documents'] == [old.model_dump()]
    assert store.read_snapshot(sid, before['snapshot_id']) == before
    none = store.snapshot(sid, 'none', explicit_sources=(), expected_data_version=2, expected_rule_version=1)
    assert none['scope']['documents'] == []
    other = store.create()['session_id']
    with pytest.raises(DocumentError) as error:
        store.read_snapshot(other, before['snapshot_id'])
    assert error.value.status_code == 404


def test_ready_transition_of_retry_increments_data_version(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    ref = ready_document(documents, store, sid)
    with closing(sqlite3.connect(documents.database)) as db, db:
        db.execute("UPDATE documents SET status='failed' WHERE document_id=?", (ref.version_id,))
        store.document_changed(db, ref.version_id)
    failed_version = store.get(sid)['data_version']
    with closing(sqlite3.connect(documents.database)) as db, db:
        db.execute("UPDATE documents SET status='ready' WHERE document_id=?", (ref.version_id,))
        store.document_ready(db, ref.version_id)
    assert store.get(sid)['data_version'] == failed_version + 1
    assert store.available(sid, (ref,))


def test_scope_change_events_are_append_only_and_survive_reopening(tmp_path):
    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    sid = store.create()['session_id']
    ref = ready_document(documents, store, sid)
    store.set_rules(sid, (ref,), {}, expected_rule_version=0)
    store.set_rules(sid, None, {'price': (ref,)}, expected_rule_version=1)
    events = SessionStore(documents.database).events(sid)
    assert len(events) == 2
    assert events[0]['payload']['default_sources'] == [ref.model_dump()]
    assert events[1]['payload']['default_sources'] is None
    assert events[1]['payload']['rule_version'] == 2


def test_session_remains_readable_in_new_process_with_clock_advanced_two_days(tmp_path):
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    documents = DocumentService(tmp_path)
    store = SessionStore(documents.database)
    session = store.create()
    store.append_message(session['session_id'], 'q', 'user', 'Keep this conversation')
    code = '''
import json, sys, time
future = time.time() + 172800
time.time = lambda: future
from app.sessions import SessionStore
store = SessionStore(sys.argv[1])
print(json.dumps({'session': store.get(sys.argv[2]), 'messages': store.messages(sys.argv[2])}))
'''
    result = subprocess.run([sys.executable, '-c', code, str(documents.database), session['session_id']],
                            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    restored = json.loads(result.stdout)
    assert restored['session'] == session
    assert restored['messages'][0]['content'] == 'Keep this conversation'
