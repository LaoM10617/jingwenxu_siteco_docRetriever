from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from test_csv_lifecycle import contents, terminal
from test_csv_parsing import row


def test_csv_execution_snapshot_is_complete_versioned_and_session_scoped(tmp_path):
    import pytest
    from app.agent_protocol import DocumentVersion
    from app.documents import DocumentError

    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        documents, sessions = client.app.state.documents, client.app.state.sessions
        sid = sessions.create()['session_id']
        other = sessions.create()['session_id']
        uploaded = client.post('/api/documents', params={'session_id': sid},
            files={'file': ('prices.csv', contents([row(str(i).zfill(4), '1,25') for i in range(205)]).getvalue())}).json()
        assert terminal(documents, uploaded['document_id'])['status'] == 'ready'
        source = DocumentVersion(document_id=uploaded['logical_document_id'], version_id=uploaded['version_id'])
        snapshot = documents.csv_snapshot(sid, (source,))
        table = snapshot[0]
        assert table['source'] == source.model_dump()
        assert table['content_hash'] == documents.get(source.version_id)['content_hash']
        assert len(table['rows']) == 205
        assert table['rows'][0]['values'][0] == '0000'
        assert table['rows'][-1]['values'][0] == '0204'
        assert len({r['row_id'] for r in table['rows']}) == 205
        with pytest.raises(DocumentError, match='available'):
            documents.csv_snapshot(other, (source,))
        sessions.remove(sid, source, expected_data_version=sessions.get(sid)['data_version'])
        with pytest.raises(DocumentError, match='available'):
            documents.csv_snapshot(sid, (source,))


def test_delete_failure_remains_unavailable_and_retries_after_restart(tmp_path, monkeypatch):
    from pathlib import Path
    import pytest
    from app.documents import DocumentService, DocumentError

    service = DocumentService(tmp_path)
    service.start()
    identity = service.submit('prices.csv', contents([row('001', '12,50')]))['document_id']
    assert terminal(service, identity)['status'] == 'ready'
    service.trash(identity)
    original = service.uploads / identity
    unlink = Path.unlink

    def fail_original(path, *args, **kwargs):
        if path == original:
            raise PermissionError('locked original')
        return unlink(path, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Path, 'unlink', fail_original)
            with pytest.raises(OSError):
                service.delete(identity)
        assert original.exists()
        assert service.get(identity)['status'] == 'deleting'
        with pytest.raises(DocumentError):
            service.restore(identity)
        with pytest.raises(DocumentError):
            service.read_evidence(identity)
    finally:
        service.stop()
    restarted = DocumentService(tmp_path)
    restarted.start()
    try:
        assert restarted.get(identity) is None
        assert not original.exists()
    finally:
        restarted.stop()


def test_ready_upload_is_attached_only_to_its_session(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        sessions = client.app.state.sessions
        first, second = sessions.create(), sessions.create()
        response = client.post('/api/documents', params={'session_id': first['session_id']},
            files={'file': ('prices.csv', contents([row('001', '12,50')]).getvalue())})
        assert response.status_code == 202, response.text
        uploaded = response.json()
        assert uploaded['version_id'] == uploaded['document_id']
        assert terminal(client.app.state.documents, uploaded['document_id'])['status'] == 'ready'
        sources = sessions.get(first['session_id'])['sources']
        assert len(sources) == 1
        assert sources[0]['version_id'] == uploaded['version_id']
        assert sources[0]['document_id'] == uploaded['logical_document_id']
        assert sources[0]['available'] is True
        assert sessions.get(second['session_id'])['sources'] == []


def test_new_version_preserves_old_source_and_permanent_delete_is_explicit(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        session = client.app.state.sessions.create()
        sid = session['session_id']
        first = client.post('/api/documents', params={'session_id': sid},
            files={'file': ('prices.csv', contents([row('001', '12,50')]).getvalue())}).json()
        assert terminal(client.app.state.documents, first['document_id'])['status'] == 'ready'
        second = client.post('/api/documents',
            params={'session_id': sid, 'logical_document_id': first['logical_document_id']},
            files={'file': ('prices.csv', contents([row('001', '20,00')]).getvalue())}).json()
        assert terminal(client.app.state.documents, second['document_id'])['status'] == 'ready'
        assert second['logical_document_id'] == first['logical_document_id']
        assert second['version_id'] != first['version_id']
        assert len(client.app.state.sessions.get(sid)['sources']) == 2
        identity = first['document_id']
        assert client.delete(f'/api/documents/{identity}').status_code == 409
        assert client.post(f'/api/documents/{identity}/trash').status_code == 200
        assert client.delete(f'/api/documents/{identity}').json() == {'deleted': 1}
        assert client.get(f'/api/documents/{identity}').status_code == 404
        sources = client.app.state.sessions.get(sid)['sources']
        assert [(source['version_id'], source['available']) for source in sources] == [
            (first['version_id'], False), (second['version_id'], True)]


def test_unknown_session_upload_is_rolled_back_without_orphan_original(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post('/api/documents', params={'session_id': 'unknown'},
            files={'file': ('prices.csv', contents([row('001')]).getvalue())})
        assert response.status_code == 404
        assert client.get('/api/documents').json() == []
        assert list(client.app.state.documents.uploads.iterdir()) == []


def test_delete_sql_failure_after_unlink_recovers_without_restoring_source(tmp_path, monkeypatch):
    import sqlite3
    import pytest
    from app.csv_store import CsvStore
    from app.documents import DocumentService

    service = DocumentService(tmp_path)
    service.start()
    identity = service.submit('prices.csv', contents([row('001')]))['document_id']
    assert terminal(service, identity)['status'] == 'ready'
    service.trash(identity)

    def unavailable(*args):
        raise sqlite3.OperationalError('injected index cleanup failure')

    try:
        with monkeypatch.context() as patch:
            patch.setattr(CsvStore, 'clear', unavailable)
            with pytest.raises(sqlite3.OperationalError):
                service.delete(identity)
        assert not (service.uploads / identity).exists()
        assert service.get(identity)['status'] == 'deleting'
    finally:
        service.stop()
    restarted = DocumentService(tmp_path)
    restarted.start()
    try:
        assert restarted.get(identity) is None
        assert restarted.empty_trash() == {'deleted': 0}
    finally:
        restarted.stop()
