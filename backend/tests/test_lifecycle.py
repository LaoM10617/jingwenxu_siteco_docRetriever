"""Lifecycle behavior through DocumentService with a controlled processing adapter."""
from io import BytesIO
from threading import Event
import time

import pytest

from app.documents import DocumentService, DocumentError
from app.processing import PreparedDocument


class Index:
    evidence_ids = ('e1',)


class Pipeline:
    def __init__(self):
        self.entered, self.release = Event(), Event()
        self.calls = 0

    def prepare(self, path, document, report, stop):
        self.calls += 1
        report('parsing')
        self.entered.set()
        assert self.release.wait(5)
        return PreparedDocument([{'evidence_id': 'e1', 'text': 'complete', 'locator': {'page': 1}}], {'fixture': True})

    def restore(self, prepared):
        return Index()


def wait_status(service, doc_id, status):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        value = service.get(doc_id)
        if value['status'] == status:
            return value
        time.sleep(.01)
    pytest.fail(f'Expected {status}, got {value}')


def test_parse_checkpoint_retry_and_interruption(tmp_path):
    from app.parsing import parse_document, ParseLimits
    from test_parsing import pdf_file
    parsed = parse_document(pdf_file(tmp_path, ['Useful evidence', '']), 'application/pdf', ParseLimits())
    class Checkpoint:
        calls = 0
        entered = Event()
        release = Event()
        def prepare(self, path, document, report, stop):
            self.calls += 1
            if self.calls == 2:
                self.entered.set()
                assert self.release.wait(5)
            report('parsing', parsed=parsed)
            if self.calls == 1:
                raise RuntimeError('provider-private-detail')
            stop.wait(5)
            # A late checkpoint after shutdown must be rejected.
            report('parsing', parsed=parsed)
    processor = Checkpoint()
    service = DocumentService(tmp_path / 'runtime')
    service.start(processor)
    try:
        doc_id = service.submit('file.csv', BytesIO(b'id\n1'))['document_id']
        assert wait_status(service, doc_id, 'failed')['parse_result']['pages'][1]['status'] == 'no_text'
        service.retry(doc_id)
        assert processor.entered.wait(5)
        assert service.get(doc_id)['parse_result'] is None
        processor.release.set()
        until = time.monotonic() + 5
        while service.get(doc_id)['parse_result'] is None and time.monotonic() < until:
            time.sleep(.01)
        before = service.get(doc_id)['parse_result']
        assert before is not None
    finally:
        processor.release.set()
        service.stop()
    restored = DocumentService(tmp_path / 'runtime')
    restored.start()
    try:
        result = restored.get(doc_id)
        assert result['error']['code'] == 'processing_interrupted'
        assert result['parse_result'] == before
        with pytest.raises(DocumentError):
            restored.read_evidence(doc_id)
    finally:
        restored.stop()


def test_only_complete_publication_is_readable_and_survives_restart(tmp_path):
    service, pipeline = DocumentService(tmp_path), Pipeline()
    service.start(pipeline)
    try:
        doc = service.submit('one.csv', BytesIO(b'id\n1'))
        assert pipeline.entered.wait(5)
        with pytest.raises(DocumentError) as error:
            service.read_evidence(doc['document_id'])
        assert error.value.status_code == 409
        pipeline.release.set()
        wait_status(service, doc['document_id'], 'ready')
        assert service.read_evidence(doc['document_id'])[0]['text'] == 'complete'
    finally:
        pipeline.release.set()
        service.stop()
    restored = DocumentService(tmp_path)
    restored.start(pipeline)
    try:
        assert restored.read_evidence(doc['document_id'])[0]['text'] == 'complete'
        assert pipeline.calls == 1
    finally:
        restored.stop()


@pytest.mark.parametrize("bad_result", [None, PreparedDocument([], {}), PreparedDocument([{'evidence_id': 'wrong', 'text': 'text', 'locator': {}}], {'fixture': True})])
def test_incomplete_result_and_mapping_mismatch_never_publish(tmp_path, bad_result):
    class Incomplete(Pipeline):
        def prepare(self, *args):
            return bad_result
    service = DocumentService(tmp_path)
    service.start(Incomplete())
    try:
        doc = service.submit('bad.csv', BytesIO(b'id\n1'))
        result = wait_status(service, doc['document_id'], 'failed')
        assert result['error']['code'] == 'incomplete_result'
        with pytest.raises(DocumentError):
            service.read_evidence(doc['document_id'])
    finally:
        service.stop()


def test_failure_isolated_old_ready_readable_and_retry_once(tmp_path):
    class FailOnce(Pipeline):
        def prepare(self, path, document, report, stop):
            if document['original_filename'] == 'bad.csv' and self.calls == 1:
                self.calls += 1
                raise ValueError('secret-provider-token')
            return super().prepare(path, document, report, stop)
    pipeline = FailOnce()
    pipeline.release.set()
    service = DocumentService(tmp_path)
    service.start(pipeline)
    try:
        old = service.submit('old.csv', BytesIO(b'id\n1'))
        wait_status(service, old['document_id'], 'ready')
        bad = service.submit('bad.csv', BytesIO(b'id\n2'))
        result = wait_status(service, bad['document_id'], 'failed')
        assert 'secret-provider-token' not in str(result)
        pipeline.entered.clear()
        pipeline.release.clear()
        retried = service.retry(bad['document_id'])
        assert retried['document_id'] == bad['document_id']
        assert pipeline.entered.wait(5)
        assert service.read_evidence(old['document_id'])[0]['text'] == 'complete'
        with pytest.raises(DocumentError) as error:
            service.retry(bad['document_id'])
        assert error.value.status_code == 409
        pipeline.release.set()
        wait_status(service, bad['document_id'], 'ready')
        assert pipeline.calls == 3
    finally:
        pipeline.release.set()
        service.stop()


def test_restart_marks_queued_interrupted_and_retry_rechecks_capacity(tmp_path):
    service = DocumentService(tmp_path, max_documents=1)
    doc = service.submit('interrupted.csv', BytesIO(b'id\n1'))
    pipeline = Pipeline()
    restarted = DocumentService(tmp_path, max_documents=1)
    restarted.start(pipeline)
    try:
        assert restarted.get(doc['document_id'])['error']['code'] == 'processing_interrupted'
        other = restarted.submit('other.csv', BytesIO(b'id\n2'))
        assert pipeline.entered.wait(5)
        with pytest.raises(DocumentError) as error:
            restarted.retry(doc['document_id'])
        assert error.value.code == 'document_limit_reached'
    finally:
        pipeline.release.set()
        restarted.stop()


def test_stop_blocks_late_publication_and_marks_waiting_jobs(tmp_path):
    service, pipeline = DocumentService(tmp_path), Pipeline()
    service.start(pipeline)
    first = service.submit('one.csv', BytesIO(b'id\n1'))
    assert pipeline.entered.wait(5)
    second = service.submit('two.csv', BytesIO(b'id\n2'))
    service.stop()
    pipeline.release.set()
    service.stop()
    for doc in (first, second):
        assert service.get(doc['document_id'])['error']['code'] == 'processing_interrupted'
        with pytest.raises(DocumentError):
            service.read_evidence(doc['document_id'])
    assert pipeline.calls == 1


def test_invalid_csv_reports_failure_and_application_stops_worker(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        response = client.post('/api/documents', files={'file': ('one.csv', b'id\n1')})
        assert response.status_code == 202
        document_id = response.json()['document_id']
        result = wait_status(app.state.documents, document_id, 'failed')
        assert result['error'] == {
            'code': 'csv_header_invalid',
            'message': 'CSV headers do not match the supported price-list schema.',
            'retryable': False}
        with pytest.raises(DocumentError):
            app.state.documents.retry(document_id)
        assert client.get('/api/health').status_code == 200


def test_restore_failure_never_exposes_ready_data(tmp_path):
    pipeline = Pipeline()
    pipeline.release.set()
    service = DocumentService(tmp_path)
    service.start(pipeline)
    try:
        doc = service.submit('one.csv', BytesIO(b'id\n1'))
        wait_status(service, doc['document_id'], 'ready')
    finally:
        service.stop()
    class BrokenRestore(Pipeline):
        def restore(self, prepared):
            raise ValueError('secret-corruption-detail')
    restarted = DocumentService(tmp_path)
    restarted.start(BrokenRestore())
    try:
        result = restarted.get(doc['document_id'])
        assert result['status'] == 'failed'
        assert result['error']['code'] == 'index_restore_failed'
        assert 'secret-corruption-detail' not in str(result)
        with pytest.raises(DocumentError):
            restarted.read_evidence(doc['document_id'])
    finally:
        restarted.stop()


def test_process_termination_leaves_explicit_interrupted_state(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = '''
from pathlib import Path
from io import BytesIO
from time import sleep
from app.documents import DocumentService
class Blocked:
    def prepare(self, path, document, report, stop):
        report('embedding')
        print('PROCESSING', flush=True)
        stop.wait(60)
service=DocumentService(Path(__import__('sys').argv[1]))
service.start(Blocked())
doc=service.submit('one.csv', BytesIO(b'id\\n1'))
Path(__import__('sys').argv[1], 'document-id').write_text(doc['document_id'])
sleep(60)
'''
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    process = subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], env=env, stdout=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / 'document-id').exists() and time.monotonic() < deadline:
            time.sleep(.01)
        document_id = (tmp_path / 'document-id').read_text()
        observer = DocumentService(tmp_path)
        wait_status(observer, document_id, 'processing')
        process.kill()
        process.wait(timeout=5)
        restarted = DocumentService(tmp_path)
        restarted.start(Pipeline())
        try:
            assert restarted.get(document_id)['error']['code'] == 'processing_interrupted'
            assert restarted.get(document_id)['error']['retryable'] is True
        finally:
            restarted.stop()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
