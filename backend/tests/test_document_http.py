import time
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_status_http_is_safe_and_survives_restart(tmp_path):
    ids = []
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        for _ in range(2):
            ids.append(client.post('/api/documents', files={'file': ('same.csv', b'id\n1')}).json()['document_id'])
        assert ids[0] != ids[1]
        for doc_id in ids:
            for _ in range(100):
                response = client.get('/api/documents/' + doc_id)
                assert response.status_code == 200
                if response.json()['status'] == 'failed':
                    break
                time.sleep(.01)
            assert response.json()['error']['code'] == 'processing_not_configured'
            assert 'stored_name' not in response.json()
            assert str(tmp_path) not in response.text
            assert client.get(f'/api/documents/{doc_id}/evidence').status_code == 409
            assert client.post(f'/api/documents/{doc_id}/retry').status_code == 409
        assert len(client.get('/api/documents').json()) == 2
        for path in ['/api/documents/missing', '/api/documents/missing/evidence']:
            error = client.get(path)
            assert error.status_code == 404
            assert set(error.json()['error']) == {'code', 'message', 'retryable'}
        assert client.post('/api/documents/missing/retry').status_code == 404
        error = client.get(f'/api/documents/{ids[0]}/evidence?limit=secret-invalid-value')
        assert error.status_code == 422
        assert 'secret-invalid-value' not in error.text
        assert 'error' in error.json()
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert {d['document_id'] for d in client.get('/api/documents').json()} == set(ids)


def poll(client, document_id, status):
    for _ in range(200):
        response = client.get('/api/documents/' + document_id)
        assert response.status_code == 200
        if response.json()['status'] == status:
            return response.json()
        time.sleep(.01)
    raise AssertionError(response.json())


def test_pdf_coverage_and_unpublished_evidence_survive_restart(tmp_path):
    from test_parsing import pdf_file
    path = pdf_file(tmp_path, ['Clause with condition', '', 'X1'])
    settings = Settings(data_dir=tmp_path / 'runtime')
    with TestClient(create_app(settings)) as client:
        doc_id = client.post('/api/documents', files={'file': ('sample.pdf', path.read_bytes())}).json()['document_id']
        result = poll(client, doc_id, 'failed')
        assert result['error']['code'] == 'retrieval_not_configured'
        assert result['parsing']['coverage'] == {'extracted': 2, 'degraded': 0, 'no_text': 1, 'failed': 0}
        assert result['parsing']['page_count'] == 3
        assert result['parsing']['evidence_count'] == 2
        assert result['parsing']['coverage_limited'] is True
        assert result['warnings'][0]['page_number'] == 2
        assert result['progress'] is None
        assert 'Clause with condition' not in str(result)
        assert client.get(f'/api/documents/{doc_id}/evidence').status_code == 409

        stored = client.app.state.documents.get(doc_id)['parse_result']
    with TestClient(create_app(settings)) as client:
        restored = client.get(f'/api/documents/{doc_id}').json()
        assert restored == result
        assert client.get('/api/documents').json() == [result]
        assert client.app.state.documents.get(doc_id)['parse_result'] == stored
        assert stored['evidence'][1]['page_number'] == 3
        assert stored['evidence'][0]['source_spans']
        assert client.get(f'/api/documents/{doc_id}/evidence').status_code == 409


@pytest.mark.parametrize('kind,code', [('empty', 'no_usable_evidence'), ('broken', 'pdf_unreadable'), ('limit', 'pdf_page_limit')])
def test_pdf_parse_failures_are_public_and_retained(tmp_path, kind, code):
    from test_parsing import pdf_file
    data = b'%PDF-1.4\nbroken' if kind == 'broken' else pdf_file(tmp_path, [''] * 2 if kind == 'empty' else ['X'] * 51).read_bytes()
    settings = Settings(data_dir=tmp_path / 'runtime')
    with TestClient(create_app(settings)) as client:
        doc_id = client.post('/api/documents', files={'file': ('bad.pdf', data)}).json()['document_id']
        result = poll(client, doc_id, 'failed')
        assert result['error']['code'] == code
        assert result['error']['retryable'] is False
        assert result['parsing']['evidence_count'] == 0
        assert result['parsing']['coverage_limited'] is True
        assert result['parsing']['page_count'] == (2 if kind == 'empty' else None)
        assert str(tmp_path) not in str(result)
    with TestClient(create_app(settings)) as client:
        assert client.get(f'/api/documents/{doc_id}').json() == result


def test_http_retry_publication_and_evidence_pagination(tmp_path):
    from threading import Event
    from app.processing import PreparedDocument
    class Processor:
        def __init__(self):
            self.calls = 0
            self.release = Event()
            self.indexing = Event()
        def prepare(self, path, document, report, stop):
            self.calls += 1
            if self.calls == 1:
                raise ValueError('fixture-secret')
            report('indexing')
            self.indexing.set()
            assert self.release.wait(5)
            return PreparedDocument([
                {'evidence_id': 'e1', 'text': 'first', 'locator': {'page': 1}, 'internal_path': 'private'},
                {'evidence_id': 'e2', 'text': 'second', 'locator': {'page': 2}}], {'fixture': True})
        def restore(self, result):
            class Index:
                evidence_ids = ('e1', 'e2')
            return Index()
    processor = Processor()
    with TestClient(create_app(Settings(data_dir=tmp_path), processor=processor)) as client:
        try:
            doc_id = client.post('/api/documents', files={'file': ('file.csv', b'id\n1')}).json()['document_id']
            assert poll(client, doc_id, 'failed')['error']['retryable'] is True
            response = client.post(f'/api/documents/{doc_id}/retry')
            assert response.status_code == 202
            assert response.json()['document_id'] == doc_id
            assert processor.indexing.wait(5)
            assert poll(client, doc_id, 'processing')['stage'] == 'indexing'
            assert client.get(f'/api/documents/{doc_id}/evidence').status_code == 409
            assert client.post(f'/api/documents/{doc_id}/retry').status_code == 409
            processor.release.set()
            poll(client, doc_id, 'ready')
            response = client.get(f'/api/documents/{doc_id}/evidence?offset=1&limit=1')
            assert response.json() == [{'evidence_id': 'e2', 'text': 'second', 'locator': {'page': 2}}]
            assert 'internal_path' not in client.get(f'/api/documents/{doc_id}/evidence').text
            assert client.get(f'/api/documents/{doc_id}/evidence?offset=20').json() == []
            assert client.get(f'/api/documents/{doc_id}/evidence?limit=101').status_code == 422
            assert processor.calls == 2
        finally:
            processor.release.set()


def test_http_interrupted_state_after_restart(tmp_path):
    from threading import Event
    class Waiting:
        entered = Event()
        def prepare(self, path, document, report, stop):
            self.entered.set()
            stop.wait(5)
            raise RuntimeError('stopped')
    processor = Waiting()
    with TestClient(create_app(Settings(data_dir=tmp_path), processor=processor)) as client:
        doc_id = client.post('/api/documents', files={'file': ('file.csv', b'id\n1')}).json()['document_id']
        assert processor.entered.wait(5)
        assert poll(client, doc_id, 'processing')['progress'] is None
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        result = client.get('/api/documents/' + doc_id).json()
        assert result['status'] == 'failed'
        assert result['error']['code'] == 'processing_interrupted'
        assert result['error']['retryable'] is True
        assert client.get(f'/api/documents/{doc_id}/evidence').status_code == 409
