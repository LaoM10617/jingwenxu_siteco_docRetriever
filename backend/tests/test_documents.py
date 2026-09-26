from io import BytesIO
from app.documents import DocumentService


def test_upload_identity_survives_reopen(tmp_path):
    service = DocumentService(tmp_path)
    first = service.submit('same.csv', BytesIO(b'id,name\n1,lamp\n'))
    second = service.submit('same.csv', BytesIO(b'id,name\n1,lamp\n'))
    assert first['document_id'] != second['document_id']
    reopened = DocumentService(tmp_path)
    assert reopened.get(first['document_id'])['status'] == 'queued'
    assert reopened.get(first['document_id'])['content_hash'] == reopened.get(second['document_id'])['content_hash']
    files = list((tmp_path / 'uploads').iterdir())
    assert len(files) == 2
    assert all(p.read_bytes() == b'id,name\n1,lamp\n' for p in files)

import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from app.documents import DocumentError


def test_size_type_and_failed_write_release_capacity(tmp_path):
    service = DocumentService(tmp_path, max_bytes=8, max_documents=1)
    with pytest.raises(DocumentError) as error:
        service.submit('large.csv', BytesIO(b'123456789'))
    assert error.value.status_code == 413
    with pytest.raises(DocumentError) as error:
        service.submit('bad.exe', BytesIO(b'123'))
    assert error.value.status_code == 415
    class BrokenInput:
        def read(self, size):
            raise OSError('private-path')
    with pytest.raises(DocumentError) as error:
        service.submit('broken.csv', BrokenInput())
    assert 'private-path' not in str(error.value)
    assert not list(service.uploads.iterdir())
    assert service.submit('ok.csv', BytesIO(b'12345678'))['size_bytes'] == 8


def test_last_slot_is_reserved_during_receiving(tmp_path):
    service = DocumentService(tmp_path, max_documents=1)
    entered, release = Event(), Event()
    class SlowInput(BytesIO):
        def read(self, size):
            entered.set()
            assert release.wait(5)
            return super().read(size)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.submit, 'first.csv', SlowInput(b'id\n1'))
        try:
            assert entered.wait(5)
            with pytest.raises(DocumentError) as error:
                DocumentService(tmp_path, max_documents=1).submit('second.csv', BytesIO(b'id\n2'))
            assert error.value.code == 'document_limit_reached'
        finally:
            release.set()
        assert pending.result()['status'] == 'queued'

from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings


def test_http_accepts_one_file_and_reports_rejections(tmp_path):
    class WaitingProcessor:
        def prepare(self, path, document, report, stop):
            stop.wait(10)
            raise RuntimeError('stopped')
    with TestClient(create_app(Settings(data_dir=tmp_path), processor=WaitingProcessor())) as client:
        response = client.post('/api/documents', files={'file': ('same.csv', b'id\n1', 'text/csv')})
        assert response.status_code == 202
        assert set(response.json()) == {'document_id', 'original_filename', 'status'}
        assert response.json()['status'] == 'queued'
        assert client.post('/api/documents', files={'file': ('x.exe', b'x')}).status_code == 415
        assert client.post('/api/documents', files=[('file', ('a.csv', b'a')), ('file', ('b.csv', b'b'))]).status_code == 422
        assert client.post('/api/documents').status_code == 422
        assert client.post('/api/documents', files={'file': ('x.csv', b'x' * (20 * 1024 * 1024 + 1))}).status_code == 413
        assert client.post('/api/documents', files={'file': ('x.csv', b'x' * (21 * 1024 * 1024))}).status_code == 413
        for n in range(9):
            assert client.post('/api/documents', files={'file': (f'{n}.csv', b'x')}).status_code == 202
        full = client.post('/api/documents', files={'file': ('last.csv', b'x')})
        assert full.status_code == 409
        assert full.json()['error']['code'] == 'document_limit_reached'
        assert str(tmp_path) not in full.text


def test_recover_interrupted_reception_preserves_accepted_upload(tmp_path):
    service = DocumentService(tmp_path, max_documents=2)
    accepted = service.submit('accepted.csv', BytesIO(b'id\n1'))
    interrupted = service.reserve()
    (service.uploads / (interrupted + '.part')).write_bytes(b'incomplete')
    restarted = DocumentService(tmp_path, max_documents=2)
    restarted.recover_receiving()
    assert restarted.get(accepted['document_id'])['status'] == 'queued'
    assert not (service.uploads / (interrupted + '.part')).exists()
    assert restarted.submit('next.csv', BytesIO(b'id\n2'))['status'] == 'queued'


def test_rename_failure_leaves_no_file_or_reserved_slot(tmp_path, monkeypatch):
    from pathlib import Path
    service = DocumentService(tmp_path, max_documents=1)
    def denied(*args):
        raise PermissionError('private-storage-detail')
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'replace', denied)
        with pytest.raises(DocumentError) as error:
            service.submit('a.csv', BytesIO(b'id\n1'))
        assert 'private-storage-detail' not in str(error.value)
    assert not list(service.uploads.iterdir())
    assert service.submit('a.csv', BytesIO(b'id\n1'))['status'] == 'queued'


def test_pdf_header_and_empty_file_rejected(tmp_path):
    service = DocumentService(tmp_path, max_documents=1)
    for filename, data, code in [('bad.pdf', b'not PDF', 'invalid_pdf_header'), ('empty.csv', b'', 'empty_file')]:
        with pytest.raises(DocumentError) as error:
            service.submit(filename, BytesIO(data))
        assert error.value.code == code
    document = service.submit('../../test.pdf', BytesIO(b'%PDF-1.7\nfixture'))
    assert document['original_filename'] == 'test.pdf'
    assert document['status'] == 'queued'
