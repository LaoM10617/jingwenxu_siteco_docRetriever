"""T-007 scope gate and real SQLite lexical candidates (no provider calls)."""
from io import BytesIO
import pytest
from app.documents import DocumentService, DocumentError
from app.retrieval.pdf import PdfRetriever, FtsStore
from test_lifecycle import Pipeline, wait_status


def test_scope_is_validated_before_any_retrieval(tmp_path):
    documents = DocumentService(tmp_path)
    retriever = PdfRetriever(documents, FtsStore(documents.database))
    pending = documents.submit('pending.pdf', BytesIO(b'%PDF-fixture'))['document_id']
    for ids, code in [(['unknown'], 'document_not_found'), ([pending], 'document_not_ready')]:
        with pytest.raises(DocumentError) as error:
            retriever.retrieve('model', ids)
        assert error.value.code == code
    with pytest.raises(DocumentError) as error:
        retriever.retrieve(' ', [pending])
    assert error.value.code == 'invalid_query'


@pytest.fixture
def ready(tmp_path):
    docs = DocumentService(tmp_path)
    pipeline = Pipeline()
    pipeline.release.set()
    docs.start(pipeline)
    ids = []
    for name in ['one.pdf', 'one.pdf', 'price.csv']:
        identity = docs.submit(name, BytesIO(b'%PDF-fixture'))['document_id']
        wait_status(docs, identity, 'ready')
        ids.append(identity)
    yield docs, ids
    docs.stop()


def evidence(identity, text):
    return {'evidence_id': identity, 'text': text, 'locator': {'kind': 'pdf', 'page_number': 3, 'bbox': [1, 2, 3, 4]}}


def test_lexical_scope_sources_and_persistence(ready):
    docs, (first, second, csv) = ready
    store = FtsStore(docs.database)
    store.replace_document(first, [evidence('same-content', 'Leuchte AB-123 für Räume mit 12,5 W IP65')])
    store.replace_document(second, [evidence('same-content', 'Leuchte AB-123 für Räume mit 12,5 W IP65')])
    retriever = PdfRetriever(docs, store)
    result = retriever.lexical_candidates('AB-123', [first, second, first], top_k=1)
    assert result['document_ids'] == [first, second]
    assert result['records'][0]['document_id'] == min(first, second)
    assert result['records'][0]['locator']['page_number'] == 3
    both = retriever.lexical_candidates('AB-123', [first, second])['records']
    assert len(both) == 2
    assert both[0]['evidence_id'] == both[1]['evidence_id']
    assert both[0]['document_id'] != both[1]['document_id']
    assert retriever.lexical_candidates('AB-123', [second], top_k=1)['records'][0]['document_id'] == second
    assert PdfRetriever(docs, FtsStore(docs.database)).lexical_candidates('AB-123', [first, second])['records'] == both
    for ids, expected in [([first, csv], 'document_not_pdf'), ([first, 'missing'], 'document_not_found')]:
        with pytest.raises(DocumentError) as error:
            retriever.lexical_candidates('AB-123', ids)
        assert error.value.code == expected
    with pytest.raises(DocumentError) as error:
        retriever.retrieve('AB-123', [first])
    assert error.value.code == 'retrieval_not_configured'


@pytest.mark.parametrize('query,expected', [
    ('AB-123', ['hyphen']), ('AB/123', []), ('0012', ['zero']), ('12', ['split']),
    ('12,5', ['hyphen']), ('12.5', ['dot']), ('-5', ['minus']), ('5', []),
    ('Räume', ['hyphen']), ('Raume', []), ('output', ['dot']),
    ('" OR NOT * : ( )', []), ('!!!', []), ('unknown', []),
])
def test_lexical_literals_and_safe_query_language(ready, query, expected):
    docs, ids = ready
    store = FtsStore(docs.database)
    store.replace_document(ids[0], [evidence('hyphen', 'AB-123 Räume 12,5'),
        evidence('split', 'AB 123 12'), evidence('dot', 'output 12.5'),
        evidence('zero', '0012'), evidence('minus', '-5')])
    result = PdfRetriever(docs, store).lexical_candidates(query, [ids[0]])
    assert [e['evidence_id'] for e in result['records']] == expected


def test_replace_is_atomic_and_context_is_searchable(ready):
    docs, ids = ready
    store = FtsStore(docs.database)
    item = {**evidence('a', '12,5 W'), 'retrieval_text': 'Model ZX-009\n12,5 W'}
    store.replace_document(ids[0], [item])
    store.replace_document(ids[0], [item])
    with pytest.raises(ValueError):
        store.replace_document(ids[0], [item, item])
    result = PdfRetriever(docs, store).lexical_candidates('ZX-009', [ids[0]])['records']
    assert len(result) == 1 and result[0]['text'] == '12,5 W'
    assert result[0]['matched_literals'] == ['zx-009']
    store.replace_document(ids[0], [evidence('b', 'replacement')])
    assert PdfRetriever(docs, store).lexical_candidates('ZX-009', [ids[0]])['records'] == []


def test_german_casefold_matches_without_changing_source(ready):
    docs, ids = ready
    store = FtsStore(docs.database)
    store.replace_document(ids[0], [evidence('german', 'Straße und Außenbeleuchtung')])
    rows = PdfRetriever(docs, store).lexical_candidates('STRAẞE', [ids[0]])['records']
    assert len(rows) == 1 and rows[0]['text'] == 'Straße und Außenbeleuchtung'


def test_bm25_orders_relevance_not_source_id(ready):
    docs, ids = ready
    store = FtsStore(docs.database)
    store.replace_document(ids[0], [evidence('a', 'lamp ' + 'irrelevant ' * 50), evidence('z', 'lamp')])
    rows = PdfRetriever(docs, store).lexical_candidates('lamp', [ids[0]])['records']
    assert [r['evidence_id'] for r in rows] == ['z', 'a']
    assert rows[0]['lexical_score'] < rows[1]['lexical_score']


@pytest.mark.parametrize('question,ids,k', [('', ['x'], 8), ('x', [], 8), ('x', [1], 8),
    ('x', 'x', 8), ('x', ['x'], True), ('x', ['x'], 0), ('x', ['x'], 101)])
def test_invalid_contract(tmp_path, question, ids, k):
    docs = DocumentService(tmp_path)
    with pytest.raises(DocumentError) as error:
        PdfRetriever(docs, FtsStore(docs.database)).retrieve(question, ids, k)
    assert error.value.code == 'invalid_query'
