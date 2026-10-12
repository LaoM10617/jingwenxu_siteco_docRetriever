from app.parsing import parse_document, ParseLimits
from test_parsing import pdf_file
from io import BytesIO
from contextlib import closing
import json
import sqlite3
import pytest
from app.documents import DocumentService, DocumentError
from app.sessions import SessionStore
from app.processing import DocumentProcessor
from app.agent_protocol import DocumentVersion
from test_multi_document_tasks import TaskGateway
from test_csv_lifecycle import terminal


@pytest.fixture
def workspace(tmp_path):
    documents = DocumentService(tmp_path / 'runtime')
    sessions = SessionStore(documents.database)
    documents.lifecycle = sessions
    documents.start(DocumentProcessor(TaskGateway()))
    sid = sessions.create()['session_id']
    doc = documents.submit('read.pdf', BytesIO(pdf_file(tmp_path, ['A' * 6001, '', 'Last page']).read_bytes()), session_id=sid)
    assert terminal(documents, doc['document_id'])['status'] == 'ready'
    source = DocumentVersion(document_id=doc['document_id'], version_id=doc['document_id'])
    try:
        yield documents, sessions, sid, source
    finally:
        documents.stop()


def test_reading_snapshot_is_session_gated_and_references_resolve(workspace):
    documents, sessions, sid, source = workspace
    snapshot = documents.pdf_reading_snapshot(sid, (source,))[0]
    assert snapshot['source'] == source.model_dump()
    unit = snapshot['pages'][0]['units'][1]
    resolved = documents.read_evidence_id(source.version_id, unit['evidence_id'])
    assert all(resolved[key] == value for key, value in unit.items())
    assert resolved['document_id'] == source.version_id
    with pytest.raises(DocumentError):
        documents.pdf_reading_snapshot(sessions.create()['session_id'], (source,))
    sessions.remove(sid, source, expected_data_version=sessions.get(sid)['data_version'])
    with pytest.raises(DocumentError):
        documents.pdf_reading_snapshot(sid, (source,))


def test_legacy_reading_backfill_preserves_index_and_survives_offline_restart(workspace, monkeypatch):
    documents, sessions, sid, source = workspace
    old = documents.read_evidence(source.version_id)
    expected = documents.pdf_reading_snapshot(sid, (source,))
    # Simulate the already supported v2 database, whose parse payload lacked reading.
    with closing(sqlite3.connect(documents.database)) as db, db:
        parsed = documents.get(source.version_id)['parse_result']
        parsed.pop('reading')
        db.execute('UPDATE document_parses SET payload=? WHERE document_id=?',
                   (json.dumps(parsed), source.version_id))
    def no_embeddings(*args, **kwargs):
        pytest.fail('Reading migration must not re-embed')
    monkeypatch.setattr(TaskGateway, 'embed', no_embeddings)
    assert documents.pdf_reading_snapshot(sid, (source,)) == expected
    assert documents.read_evidence(source.version_id) == old
    documents.stop()
    restored = DocumentService(documents.database.parent)
    restored.lifecycle = sessions
    restored.start()
    try:
        assert restored.pdf_reading_snapshot(sid, (source,)) == expected
        assert restored.read_evidence(source.version_id) == old
    finally:
        restored.stop()


def test_reading_checks_original_even_when_cache_exists(workspace):
    documents, sessions, sid, source = workspace
    snapshot = documents.pdf_reading_snapshot(sid, (source,))
    path = documents.uploads / documents.get(source.version_id)['stored_name']
    path.write_bytes(b'changed')
    with pytest.raises(DocumentError) as error:
        documents.pdf_reading_snapshot(sid, (source,))
    assert error.value.code == 'original_changed'
    with pytest.raises(DocumentError):
        documents.read_evidence_id(source.version_id, snapshot[0]['pages'][0]['units'][0]['evidence_id'])


def test_reading_follows_trash_restore_and_permanent_deletion(workspace):
    documents, sessions, sid, source = workspace
    expected = documents.pdf_reading_snapshot(sid, (source,))
    evidence_id = expected[0]['pages'][0]['units'][0]['evidence_id']
    documents.trash(source.version_id)
    with pytest.raises(DocumentError):
        documents.pdf_reading_snapshot(sid, (source,))
    with pytest.raises(DocumentError):
        documents.read_evidence_id(source.version_id, evidence_id)
    documents.restore(source.version_id)
    assert documents.pdf_reading_snapshot(sid, (source,)) == expected
    documents.trash(source.version_id)
    documents.delete(source.version_id)
    with pytest.raises(DocumentError):
        documents.pdf_reading_snapshot(sid, (source,))
    with pytest.raises(DocumentError):
        documents.read_evidence_id(source.version_id, evidence_id)


def test_entire_oversized_native_document_is_publishable(tmp_path):
    documents = DocumentService(tmp_path / 'runtime')
    documents.start(DocumentProcessor(TaskGateway()))
    try:
        doc = documents.submit('long.pdf', BytesIO(pdf_file(tmp_path, ['X' * 12001]).read_bytes()))
        assert terminal(documents, doc['document_id'])['status'] == 'ready'
        reading = documents.get(doc['document_id'])['parse_result']['reading']
        assert ''.join(u['text'] for u in reading['pages'][0]['units']) == 'X' * 12001
        evidence = documents.read_evidence(doc['document_id'])
        assert ''.join(u['text'] for u in evidence) == 'X' * 12001
    finally:
        documents.stop()


def test_native_reading_preserves_oversized_page_and_physical_gaps(tmp_path):
    text = 'A' * 6001
    parsed = parse_document(pdf_file(tmp_path, [text, '', 'Last page']), 'application/pdf', ParseLimits())
    reading = parsed.reading
    assert [p['page_number'] for p in reading['pages']] == [1, 2, 3]
    units = reading['pages'][0]['units']
    assert ''.join(u['text'] for u in units) == text
    assert all(len(u['text']) <= 6000 for u in units)
    assert units[1]['continuation'] is True
    assert reading['pages'][1] == {'page_number': 2, 'status': 'no_text', 'units': []}
    assert reading['pages'][2]['units'][0]['text'] == 'Last page'
    assert reading == parse_document(tmp_path / 'fixture.pdf', 'application/pdf', ParseLimits()).reading


def test_reading_retains_page_structure_hints_without_inventing_sections(tmp_path):
    commands = 'BT /F2 12 Tf 20 180 Td (Terms) Tj ET\nBT /F1 12 Tf 20 150 Td (Delivery after approval.) Tj ET'
    result = parse_document(pdf_file(tmp_path, [commands], commands=True), 'application/pdf', ParseLimits())
    page = result.reading['pages'][0]
    assert any(h['text'] == 'Terms' for region in page['structure'] for h in region['headings'])
    assert all(region['kind'] in {'text', 'table', 'fallback'} for region in page['structure'])
    assert page['units'][0]['section'] is None


def test_reading_failed_pages_have_explicit_gaps(tmp_path, monkeypatch):
    from pdfplumber.page import Page
    from pdfminer.psexceptions import PSSyntaxError
    original = Page.extract_text
    def extract(page, *args, **kwargs):
        if page.page_number == 2:
            raise PSSyntaxError('broken native page')
        return original(page, *args, **kwargs)
    monkeypatch.setattr(Page, 'extract_text', extract)
    result = parse_document(pdf_file(tmp_path, ['First', 'Broken', 'Last']), 'application/pdf', ParseLimits())
    assert result.reading['pages'][1] == {'page_number': 2, 'status': 'failed', 'units': []}
    assert result.reading['pages'][2]['units'][0]['text'] == 'Last'


def test_reading_missing_original_and_stopped_budget_do_not_return_cache(workspace):
    documents, sessions, sid, source = workspace
    class Stopped:
        def check(self):
            raise RuntimeError('stopped')
    with pytest.raises(RuntimeError, match='stopped'):
        documents.pdf_reading_snapshot(sid, (source,), Stopped())
    (documents.uploads / documents.get(source.version_id)['stored_name']).unlink()
    with pytest.raises(DocumentError) as error:
        documents.pdf_reading_snapshot(sid, (source,))
    assert error.value.code == 'original_unavailable'
