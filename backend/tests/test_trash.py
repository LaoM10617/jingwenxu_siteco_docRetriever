from contextlib import closing
from io import BytesIO
import sqlite3

import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.documents import DocumentService, DocumentError
from app.processing import DocumentProcessor
from test_csv_lifecycle import contents, terminal
from test_csv_parsing import row
from test_pdf_publication import Gateway
from test_parsing import pdf_file
from test_lifecycle import Pipeline, wait_status


@pytest.mark.parametrize('kind', ['csv', 'pdf'])
def test_trash_restart_restore_and_permanent_cleanup(tmp_path, kind):
    runtime = tmp_path / 'runtime'
    gateway = Gateway()
    service = DocumentService(runtime)
    service.start(DocumentProcessor(gateway))
    try:
        data = contents([row('001', '12,50')]) if kind == 'csv' else BytesIO(pdf_file(tmp_path, ['Product AB-123']).read_bytes())
        identity = service.submit('sample.' + kind, data)['document_id']
        assert terminal(service, identity)['status'] == 'ready'
        evidence = service.read_evidence(identity)
        service.trash(identity)
        assert service.list() == []
        assert service.list(trashed=True)[0]['document_id'] == identity
        with pytest.raises(DocumentError):
            service.read_evidence(identity)
        with pytest.raises(DocumentError):
            service.read_evidence_id(identity, evidence[0]['evidence_id'])
        if kind == 'csv':
            with pytest.raises(DocumentError):
                service.lookup_orders(['001'], [identity])
        else:
            with pytest.raises(DocumentError):
                service.pdf_snapshot([identity])
    finally:
        service.stop()
    service = DocumentService(runtime)
    service.start()
    try:
        assert service.get(identity)['status'] == 'trashed'
        assert service.restore(identity)['status'] == 'ready'
        assert service.read_evidence(identity) == evidence
        assert gateway.calls == (['document'] if kind == 'pdf' else [])
        service.trash(identity)
        assert service.empty_trash() == {'deleted': 1}
        assert service.get(identity) is None
        assert not (service.uploads / identity).exists()
        with closing(sqlite3.connect(service.database)) as db:
            for table in ('documents', 'document_trash', 'document_parses', 'document_artifacts', 'csv_records', 'csv_documents', 'pdf_artifacts', 'pdf_fts'):
                assert db.execute(f'SELECT COUNT(*) FROM {table} WHERE document_id=?', (identity,)).fetchone()[0] == 0
        assert service.empty_trash() == {'deleted': 0}
    finally:
        service.stop()


def test_capacity_and_processing_guard(tmp_path):
    service, pipeline = DocumentService(tmp_path, max_documents=1), Pipeline()
    service.start(pipeline)
    try:
        identity = service.submit('one.csv', BytesIO(b'id\n1'))['document_id']
        assert pipeline.entered.wait(5)
        with pytest.raises(DocumentError) as exc:
            service.trash(identity)
        assert exc.value.code == 'document_busy'
        pipeline.release.set()
        wait_status(service, identity, 'ready')
        service.trash(identity)
        second = service.submit('two.csv', BytesIO(b'id\n2'))['document_id']
        wait_status(service, second, 'ready')
        with pytest.raises(DocumentError) as exc:
            service.restore(identity)
        assert exc.value.code == 'document_limit_reached'
        service.empty_trash()
        assert service.read_evidence(second)
        assert (service.uploads / second).exists()
    finally:
        pipeline.release.set()
        service.stop()


def test_http_trash_failed_file_restore_and_clear(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        identity = client.post('/api/documents', files={'file': ('bad.csv', b'id\n1')}).json()['document_id']
        terminal(client.app.state.documents, identity)
        before = client.get('/api/documents/' + identity).json()
        assert client.post(f'/api/documents/{identity}/trash').json()['status'] == 'trashed'
        assert client.post(f'/api/documents/{identity}/trash').status_code == 200
        assert client.get('/api/documents').json() == []
        assert len(client.get('/api/trash').json()) == 1
        restored = client.post(f'/api/documents/{identity}/restore').json()
        assert restored['status'] == before['status'] == 'failed'
        assert restored['error'] == before['error']
        client.post(f'/api/documents/{identity}/trash')
        assert client.delete('/api/trash').json() == {'deleted': 1}
        assert client.get('/api/trash').json() == []
        assert client.post(f'/api/documents/{identity}/restore').status_code == 404
