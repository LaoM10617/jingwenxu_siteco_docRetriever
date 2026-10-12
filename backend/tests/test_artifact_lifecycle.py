"""Artifacts are historical records; reuse requires a current source snapshot."""
import json
import pytest

from app.artifacts import ArtifactStore
from app.agent_protocol import DocumentVersion, ScopeSnapshot
from app.documents import DocumentService, DocumentError
from app.sessions import SessionStore
from test_csv_lifecycle import contents, terminal
from test_csv_parsing import row


@pytest.fixture
def workspace(tmp_path):
    documents = DocumentService(tmp_path)
    sessions = SessionStore(documents.database)
    artifacts = ArtifactStore(documents.database)
    documents.lifecycle, documents.derived = sessions, artifacts
    documents.start()
    try:
        session = sessions.create()
        sid = session['session_id']
        doc = documents.submit('prices.csv', contents([row('001', '12,50')]), session_id=sid)
        assert terminal(documents, doc['document_id'])['status'] == 'ready'
        yield documents, sessions, artifacts, sid, doc['document_id']
    finally:
        documents.stop()


def snapshot(sessions, sid, request_id):
    current = sessions.get(sid)
    return sessions.snapshot(sid, request_id, expected_data_version=current['data_version'],
                             expected_rule_version=current['rule_version'])


def test_specialist_scope_and_pagination_keep_only_actual_dependencies(workspace):
    documents, sessions, artifacts, sid, original = workspace
    other = documents.submit('other.csv', contents([row('002', '1,00')]), session_id=sid)
    assert terminal(documents, other['document_id'])['status'] == 'ready'
    snap = snapshot(sessions, sid, 'mixed')
    accepted = ScopeSnapshot.model_validate_json(json.dumps(snap['scope']))
    scope = accepted.model_copy(update={'documents': (DocumentVersion(document_id=original, version_id=original),)})
    rows = [[str(i).zfill(3), i] for i in range(150)]
    artifacts.publish(sid, 'table', snap['snapshot_id'], kind='table',
        payload={'columns': ['id', 'value'], 'rows': rows}, scope=scope)
    assert artifacts.page(sid, 'table')['rows'] == rows[:100]
    assert artifacts.page(sid, 'table', 100)['rows'] == rows[100:]
    assert not artifacts.page(sid, 'table', 100)['has_more']
    documents.trash(other['document_id'])
    documents.empty_trash()
    assert artifacts.get(sid, 'table')['source_available']
    outside = scope.model_copy(update={'documents': (DocumentVersion(document_id='outside', version_id='outside'),)})
    with pytest.raises(DocumentError, match='accepted scope'):
        artifacts.publish(sid, 'outside', snap['snapshot_id'], kind='table', payload={}, scope=outside)
    documents.trash(original)
    documents.empty_trash()
    with pytest.raises(DocumentError, match='deleted with its source'):
        artifacts.page(sid, 'table')


def test_artifact_reuse_checks_current_sources_and_preserves_history(workspace):
    documents, sessions, artifacts, sid, storage_id = workspace
    snap = snapshot(sessions, sid, 'first')
    result = artifacts.publish(sid, 'total', snap['snapshot_id'], kind='numeric',
                               payload={'value': '12.50'}, calculation='sum Listenpreis',
                               unit='source price unit', cache_key='sum-v1')
    assert artifacts.reuse(sid, 'total', snap['snapshot_id'])['payload'] == {'value': '12.50'}
    assert artifacts.publish(sid, 'total', snap['snapshot_id'], kind='numeric',
                             payload={'value': '12.50'}, calculation='sum Listenpreis',
                             unit='source price unit', cache_key='sum-v1') == result
    documents.trash(storage_id)
    assert artifacts.get(sid, 'total')['payload'] == {'value': '12.50'}
    assert not artifacts.get(sid, 'total')['source_available']
    with pytest.raises(DocumentError):
        artifacts.reuse(sid, 'total', snap['snapshot_id'])
    documents.restore(storage_id)
    fresh = snapshot(sessions, sid, 'restored')
    assert artifacts.cached(sid, 'sum-v1', fresh['snapshot_id'])['artifact_id'] == 'total'
    documents.trash(storage_id)
    documents.empty_trash()
    historical = artifacts.get(sid, 'total')
    assert historical['invalidated'] and historical['payload'] is None
    assert not historical['source_available']
    assert artifacts.cached(sid, 'sum-v1', fresh['snapshot_id']) is None


def test_reuse_never_crosses_sessions_or_recomputes_changed_scope(workspace):
    documents, sessions, artifacts, sid, storage_id = workspace
    snap = snapshot(sessions, sid, 'first')
    artifacts.publish(sid, 'total', snap['snapshot_id'], kind='numeric', payload={'value': '12.50'}, cache_key='sum')
    second = sessions.create()['session_id']
    sessions.attach(second, DocumentVersion(document_id=storage_id, version_id=storage_id), expected_data_version=0)
    second_snap = snapshot(sessions, second, 'q')
    assert artifacts.cached(second, 'sum', second_snap['snapshot_id']) is None
    with pytest.raises(DocumentError):
        artifacts.get(second, 'total')
    with pytest.raises(DocumentError):
        artifacts.reuse(sid, 'total', second_snap['snapshot_id'])
    newer = documents.submit('new.csv', contents([row('002', '1,00')]), session_id=sid)
    assert terminal(documents, newer['document_id'])['status'] == 'ready'
    changed = snapshot(sessions, sid, 'new-scope')
    assert artifacts.cached(sid, 'sum', changed['snapshot_id']) is None
    with pytest.raises(DocumentError, match='current source scope'):
        artifacts.reuse(sid, 'total', changed['snapshot_id'])
    assert artifacts.get(sid, 'total')['payload'] == {'value': '12.50'}


def test_deletion_retains_answer_but_erases_summary_and_session_delete_cleans(workspace):
    documents, sessions, artifacts, sid, storage_id = workspace
    snap = snapshot(sessions, sid, 'q')
    for kind in ('answer', 'summary'):
        artifacts.publish(sid, kind, snap['snapshot_id'], kind=kind, payload={'text': '12.50'}, cache_key=kind)
    documents.trash(storage_id)
    documents.empty_trash()
    assert artifacts.get(sid, 'answer')['payload'] == {'text': '12.50'}
    assert artifacts.get(sid, 'answer')['invalidated']
    assert artifacts.get(sid, 'summary')['payload'] is None
    sessions.delete(sid)
    with pytest.raises(DocumentError):
        artifacts.get(sid, 'answer')


@pytest.mark.parametrize('selection', ['explicit', 'default', 'purpose'])
def test_duplicate_source_selection_publishes_once(workspace, selection):
    documents, sessions, artifacts, sid, storage_id = workspace
    source = DocumentVersion(document_id=storage_id, version_id=storage_id)
    if selection != 'explicit':
        sessions.set_rules(sid, (source, source) if selection == 'default' else None,
                           {'price': (source, source)} if selection == 'purpose' else {},
                           expected_rule_version=0)
    state = sessions.get(sid)
    snap = sessions.snapshot(sid, 'duplicates', purpose='price',
        explicit_sources=(source, source) if selection == 'explicit' else None,
        expected_data_version=state['data_version'], expected_rule_version=state['rule_version'])
    result = artifacts.publish(sid, 'deduplicated', snap['snapshot_id'], kind='numeric', payload={'value': 1})
    assert len(result['scope']['documents']) == 1


def test_changed_filter_requires_recomputation(workspace):
    documents, sessions, artifacts, sid, storage_id = workspace
    before = snapshot(sessions, sid, 'all')
    artifacts.publish(sid, 'total', before['snapshot_id'], kind='numeric', payload={'value': '12.50'}, cache_key='sum')
    state = sessions.get(sid)
    filtered = sessions.snapshot(sid, 'filtered', expected_data_version=state['data_version'],
        expected_rule_version=state['rule_version'], filters=('Listenpreis < 10',))
    assert artifacts.cached(sid, 'sum', filtered['snapshot_id']) is None
    assert filtered['scope']['filters'] == ['Listenpreis < 10']


def test_dependency_purpose_change_prevents_public_reuse_and_cache_hit(workspace):
    from app.agent_protocol import SourceScope
    _, sessions, artifacts, sid, storage_id = workspace
    source = DocumentVersion(document_id=storage_id, version_id=storage_id)
    state = sessions.get(sid)
    def make(identity, purpose):
        return sessions.snapshot(sid, identity, purpose='price',
            dependency_scopes=(SourceScope(documents=(source,), purpose=purpose),),
            expected_data_version=state['data_version'], expected_rule_version=state['rule_version'])
    original = make('original', 'selection')
    artifacts.publish(sid, 'result', original['snapshot_id'], kind='numeric', payload={'value': 1}, cache_key='k')
    changed = make('changed', 'other-selection')
    with pytest.raises(DocumentError, match='current source scope'):
        artifacts.reuse(sid, 'result', changed['snapshot_id'])
    assert artifacts.cached(sid, 'k', changed['snapshot_id']) is None
