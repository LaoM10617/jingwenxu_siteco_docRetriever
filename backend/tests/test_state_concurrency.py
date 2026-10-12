"""M3.2 real HTTP and storage with controlled external waits."""
from threading import Event
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_multi_document_tasks import TaskGateway, ScopeModel, upload, finish
from test_parsing import pdf_file
from document_test_helpers import ready, csv_bytes
from test_csv_parsing import row


def test_ingestion_wait_keeps_ready_answers_and_http_available(tmp_path):
    waiting, admitted, admit, complete = Event(), Event(), Event(), Event()
    class Waiting(TaskGateway):
        def embed(self, texts, *, input_type, stop=None, on_wait=None, on_start=None):
            if input_type == 'document' and 'waiting' in texts[0]:
                on_wait()
                waiting.set()
                assert admit.wait(10)
                if on_start:
                    on_start()
                admitted.set()
                assert complete.wait(10)
            return super().embed(texts, input_type=input_type, stop=stop,
                                 on_wait=on_wait, on_start=on_start)

    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(Waiting()), model=ScopeModel())) as client:
        try:
            old = upload(client, 'old.pdf', pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes())
            pending = client.post('/api/documents', files={'file': ('new.pdf',
                pdf_file(tmp_path, ['waiting lamp']).read_bytes())}).json()['document_id']
            assert waiting.wait(2)
            assert client.get('/api/documents/' + pending).json()['stage'] == 'waiting_rate_limit'
            task = finish(client, {'conversation_id':'a','request_id':'r',
                                  'question':'AB-123 power?', 'document_ids':[old]})
            assert task['answer']['citations'][0]['document_id'] == old
            assert client.get('/api/health').status_code == 200
            extra = client.post('/api/documents', files={'file':('prices.csv',csv_bytes([row('001')]))})
            assert extra.status_code == 202
            assert client.get('/api/documents/' + old).json()['status'] == 'ready'
            admit.set()
            assert admitted.wait(2)
            # Provider execution has begun; quota waiting is no longer the current stage.
            assert client.get('/api/documents/' + pending).json()['stage'] == 'embedding'
            complete.set()
            for _ in range(100):
                if client.get('/api/documents/' + pending).json()['status'] == 'ready':
                    break
                time.sleep(.02)
            assert client.get('/api/documents/' + pending).json()['status'] == 'ready'
        finally:
            admit.set()
            complete.set()


def test_query_quota_wait_resumes_without_blocking_health_or_upload(tmp_path):
    waiting, admit, started, complete = Event(), Event(), Event(), Event()
    class Waiting(TaskGateway):
        def embed(self, texts, *, input_type, stop=None, on_wait=None, on_start=None):
            if input_type == 'query':
                on_wait()
                waiting.set()
                assert admit.wait(10)
                on_start()
                started.set()
                assert complete.wait(10)
            return super().embed(texts, input_type=input_type, stop=stop, on_wait=on_wait)
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(Waiting()), model=ScopeModel())) as client:
        try:
            old = upload(client, 'old.pdf', pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes())
            from concurrent.futures import ThreadPoolExecutor
            body = {'conversation_id':'a','request_id':'r','question':'AB-123 power?','document_ids':[old]}
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(finish, client, body)
                try:
                    assert waiting.wait(2)
                    assert client.get('/api/health').status_code == 200
                    assert ready(client) != old
                    admit.set()
                    assert started.wait(2)
                    complete.set()
                    task = pending.result(timeout=5)
                    assert task['answer']['citations'][0]['document_id'] == old
                finally:
                    admit.set()
                    complete.set()
        finally:
            admit.set()
            complete.set()
