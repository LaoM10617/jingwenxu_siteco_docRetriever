"""T-004/T-007: real PDF lifecycle with a controlled embedding adapter."""
from io import BytesIO
from threading import Event

import numpy as np
import pytest

from app.documents import DocumentService, DocumentError
from app.processing import DocumentProcessor
from app.retrieval.pdf import PdfRetriever
from test_lifecycle import wait_status
from test_parsing import pdf_file


class Gateway:
    model = 'voyage-4'

    def __init__(self):
        self.calls = []
        self.entered, self.release = Event(), Event()
        self.release.set()

    def embed(self, texts, *, input_type, stop=None, on_wait=None):
        self.calls.append(input_type)
        self.entered.set()
        assert self.release.wait(5)
        vectors = np.zeros((len(texts), 1024), dtype='float32')
        vectors[:, 0] = 3
        vectors[:, 1] = 4
        return vectors


def test_pdf_complete_publication_and_offline_restart(tmp_path):
    source = pdf_file(tmp_path, ['Model AB-123 output 12.5 W', 'Second page'])
    gateway = Gateway()
    gateway.release.clear()
    service = DocumentService(tmp_path / 'runtime')
    service.start(DocumentProcessor(gateway))
    try:
        identity = service.submit('one.pdf', BytesIO(source.read_bytes()))['document_id']
        assert gateway.entered.wait(5)
        assert service.get(identity)['stage'] == 'embedding'
        with pytest.raises(DocumentError):
            service.read_evidence(identity)
        gateway.release.set()
        wait_status(service, identity, 'ready')
        evidence = service.read_evidence(identity)
        assert len(evidence) == 2
        assert evidence[0]['locator']['kind'] == 'pdf'
        assert evidence[0]['locator']['page_number'] == 1
    finally:
        gateway.release.set()
        service.stop()
    restored = DocumentService(tmp_path / 'runtime')
    restored.start()
    try:
        assert restored.get(identity)['status'] == 'ready'
        assert restored.read_evidence(identity) == evidence
        assert gateway.calls == ['document']
    finally:
        restored.stop()


def test_hybrid_duplicate_sources_and_empty_lexical_route(tmp_path):
    source = pdf_file(tmp_path, ['Model AB-123 output 12.5 W'])
    gateway = Gateway()
    service = DocumentService(tmp_path / 'runtime')
    service.start(DocumentProcessor(gateway))
    try:
        ids = []
        for _ in range(2):
            identity = service.submit('same.pdf', BytesIO(source.read_bytes()))['document_id']
            wait_status(service, identity, 'ready')
            ids.append(identity)
        retriever = PdfRetriever(service, service.lexical, gateway)
        result = retriever.retrieve('AB-123', ids + ids)
        assert result['document_ids'] == ids
        rows = result['records']
        assert [r['document_id'] for r in rows] == sorted(ids)
        assert rows[0]['evidence_id'] == rows[1]['evidence_id']
        assert [r['lexical_rank'] for r in rows] == [1, 2]
        assert [r['semantic_rank'] for r in rows] == [1, 2]
        assert rows[0]['semantic_score'] == pytest.approx(1)
        assert rows[0]['fused_score'] == pytest.approx(2 / 61)
        assert len(retriever.retrieve('AB-123', [ids[1]])['records']) == 1
        empty = retriever.retrieve('xyzunknown', ids)
        assert empty['routes']['lexical']['count'] == 0
        assert all(r['lexical_rank'] is None for r in empty['records'])
        assert empty['records'][0]['fused_score'] == pytest.approx(1 / 61)
        before = len(gateway.calls)
        with pytest.raises(DocumentError):
            retriever.retrieve('AB-123', ids + ['missing'])
        assert len(gateway.calls) == before
    finally:
        service.stop()


def test_global_candidates_are_cut_before_fusion_and_ties_are_stable(tmp_path):
    source = pdf_file(tmp_path, [f'lamp page {n}' for n in range(25)])
    gateway = Gateway()
    service = DocumentService(tmp_path / 'runtime')
    service.start(DocumentProcessor(gateway))
    try:
        ids = []
        for _ in range(2):
            identity = service.submit('same.pdf', BytesIO(source.read_bytes()))['document_id']
            wait_status(service, identity, 'ready')
            ids.append(identity)
        retriever = PdfRetriever(service, service.lexical, gateway)
        result = retriever.retrieve('lamp', ids, top_k=100)
        assert result['routes']['lexical']['count'] == 20
        assert result['routes']['semantic']['count'] == 20
        assert len(result['records']) == 20
        assert {r['document_id'] for r in result['records']} == {min(ids)}
        assert result['records'] == retriever.retrieve('lamp', list(reversed(ids)), 100)['records']
        assert len(retriever.retrieve('lamp', ids)['records']) == 8
        only_second = retriever.retrieve('lamp', [max(ids)])
        assert {r['document_id'] for r in only_second['records']} == {max(ids)}
    finally:
        service.stop()


def test_failed_embedding_isolated_retry_keeps_one_mapping(tmp_path):
    from app.embeddings import EmbeddingError
    class FailOnce(Gateway):
        failed = False
        def embed(self, texts, *, input_type, **kwargs):
            if any('broken' in text for text in texts) and not self.failed:
                self.failed = True
                raise EmbeddingError('embedding_provider_unavailable', retryable=True)
            return super().embed(texts, input_type=input_type, **kwargs)
    gateway = FailOnce()
    service = DocumentService(tmp_path / 'runtime')
    service.start(DocumentProcessor(gateway))
    try:
        good = service.submit('good.pdf', BytesIO(pdf_file(tmp_path, ['lamp']).read_bytes()))['document_id']
        wait_status(service, good, 'ready')
        bad = service.submit('bad.pdf', BytesIO(pdf_file(tmp_path, ['broken lamp']).read_bytes()))['document_id']
        assert wait_status(service, bad, 'failed')['error']['retryable'] is True
        retriever = PdfRetriever(service, service.lexical, gateway)
        assert len(retriever.retrieve('lamp', [good])['records']) == 1
        with pytest.raises(DocumentError):
            retriever.retrieve('lamp', [bad])
        service.retry(bad)
        wait_status(service, bad, 'ready')
        assert len(service.read_evidence(bad)) == 1
        assert len(retriever.retrieve('lamp', [good, bad])['records']) == 2
    finally:
        service.stop()


def test_semantic_failure_never_silently_returns_lexical_results(tmp_path):
    from app.embeddings import EmbeddingError
    class QueryFails(Gateway):
        def embed(self, texts, *, input_type, **kwargs):
            if input_type == 'query':
                raise EmbeddingError('embedding_wait_timeout')
            return super().embed(texts, input_type=input_type, **kwargs)
    gateway = QueryFails()
    service = DocumentService(tmp_path / 'runtime')
    service.start(DocumentProcessor(gateway))
    try:
        identity = service.submit('one.pdf', BytesIO(pdf_file(tmp_path, ['lamp']).read_bytes()))['document_id']
        wait_status(service, identity, 'ready')
        retriever = PdfRetriever(service, service.lexical, gateway)
        assert retriever.lexical_candidates('lamp', [identity])['records']
        with pytest.raises(DocumentError) as error:
            retriever.retrieve('lamp', [identity])
        assert error.value.code == 'embedding_wait_timeout'
        assert error.value.retryable is True
    finally:
        service.stop()


def test_ready_queries_continue_during_ingestion_wait(tmp_path):
    class Waiting(Gateway):
        def embed(self, texts, *, input_type, stop=None, on_wait=None):
            if input_type == 'document' and 'waiting' in texts[0]:
                on_wait()
                self.entered.set()
                assert self.release.wait(5)
            vectors = np.zeros((len(texts), 1024), dtype='float32')
            vectors[:, 0] = 1
            return vectors
    gateway = Waiting()
    service = DocumentService(tmp_path / 'runtime')
    service.start(DocumentProcessor(gateway))
    try:
        first = service.submit('one.pdf', BytesIO(pdf_file(tmp_path, ['lamp']).read_bytes()))['document_id']
        wait_status(service, first, 'ready')
        gateway.release.clear()
        second = service.submit('two.pdf', BytesIO(pdf_file(tmp_path, ['waiting']).read_bytes()))['document_id']
        assert gateway.entered.wait(5)
        assert service.get(second)['stage'] == 'waiting_rate_limit'
        retriever = PdfRetriever(service, service.lexical, gateway)
        assert len(retriever.retrieve('lamp', [first])['records']) == 1
        with pytest.raises(DocumentError):
            retriever.retrieve('lamp', [first, second])
        gateway.release.set()
        wait_status(service, second, 'ready')
    finally:
        gateway.release.set()
        service.stop()


@pytest.mark.parametrize('corrupt', ['vectors', 'metadata'])
def test_corrupt_persisted_artifact_is_withdrawn_on_restart(tmp_path, corrupt):
    from contextlib import closing
    import sqlite3
    gateway = Gateway()
    runtime = tmp_path / 'runtime'
    service = DocumentService(runtime)
    service.start(DocumentProcessor(gateway))
    identity = service.submit('one.pdf', BytesIO(pdf_file(tmp_path, ['lamp']).read_bytes()))['document_id']
    wait_status(service, identity, 'ready')
    service.stop()
    # Fault injection into a stopped store, never observing a running DB externally.
    with closing(sqlite3.connect(runtime / 'app.sqlite3')) as db, db:
        db.execute(f'UPDATE pdf_artifacts SET {corrupt}=?', (b'broken' if corrupt == 'vectors' else '{}',))
    restored = DocumentService(runtime)
    restored.start(DocumentProcessor(gateway))
    try:
        assert restored.get(identity)['error']['code'] == 'index_restore_failed'
        with pytest.raises(DocumentError):
            restored.read_evidence(identity)
        restored.retry(identity)
        wait_status(restored, identity, 'ready')
        rows = PdfRetriever(restored, restored.lexical, gateway).retrieve('lamp', [identity])['records']
        assert len(rows) == 1
    finally:
        restored.stop()


def test_faiss_scores_and_sources_are_identical_after_restart(tmp_path):
    class Varied(Gateway):
        def embed(self, texts, **kwargs):
            return np.array([np.random.default_rng(len(t)).normal(size=1024) for t in texts], dtype='float32')
    gateway = Varied()
    runtime = tmp_path / 'runtime'
    service = DocumentService(runtime)
    service.start(DocumentProcessor(gateway))
    try:
        identity = service.submit('one.pdf', BytesIO(pdf_file(tmp_path, ['lamp alpha', 'lamp beta']).read_bytes()))['document_id']
        wait_status(service, identity, 'ready')
        before = PdfRetriever(service, service.lexical, gateway).retrieve('lamp', [identity])
    finally:
        service.stop()
    restored = DocumentService(runtime)
    restored.start()
    try:
        assert PdfRetriever(restored, restored.lexical, gateway).retrieve('lamp', [identity]) == before
    finally:
        restored.stop()


def test_pdf_shutdown_rejects_late_embedding_result(tmp_path):
    gateway = Gateway()
    gateway.release.clear()
    runtime = tmp_path / 'runtime'
    service = DocumentService(runtime)
    service.start(DocumentProcessor(gateway))
    identity = service.submit('late.pdf', BytesIO(pdf_file(tmp_path, ['lamp']).read_bytes()))['document_id']
    assert gateway.entered.wait(5)
    service.stop()
    gateway.release.set()
    service.stop()
    assert service.get(identity)['error']['code'] == 'processing_interrupted'
    restored = DocumentService(runtime)
    restored.start()
    try:
        with pytest.raises(DocumentError):
            restored.read_evidence(identity)
        assert restored.get(identity)['status'] == 'failed'
    finally:
        restored.stop()


def test_missing_tokenizer_has_actionable_error_without_blocking_startup(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    app = create_app(Settings(data_dir=tmp_path / 'runtime', voyage_api_key='synthetic-not-a-real-key'))
    source = pdf_file(tmp_path, ['lamp']).read_bytes()
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        response = client.post('/api/documents', files={'file': ('one.pdf', source)})
        identity = response.json()['document_id']
        result = wait_status(app.state.documents, identity, 'failed')
        assert result['error']['code'] == 'embedding_configuration_invalid'
        assert result['parse_result']['evidence']
        assert 'synthetic-not-a-real-key' not in str(client.get(f'/api/documents/{identity}').json())
