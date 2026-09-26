"""Real CSV lifecycle and exact lookup through T-002/T-006."""
from io import BytesIO, StringIO
import csv
import time
import sqlite3
from threading import Event

import pytest

from app.documents import DocumentService, DocumentError
from test_csv_parsing import HEADERS, row


def contents(rows):
    stream = StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return BytesIO(stream.getvalue().encode('utf-8'))


def terminal(service, document_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        document = service.get(document_id)
        if document['status'] in ('ready', 'failed'):
            return document
        time.sleep(.01)
    raise AssertionError('CSV processing did not finish')


def test_csv_publishes_records_and_restores_without_parsing(tmp_path, monkeypatch):
    service = DocumentService(tmp_path)
    service.start()
    try:
        doc = service.submit('prices.csv', contents([row('001', '1.234,50'), row('001', 'bad')]))
        ready = terminal(service, doc['document_id'])
        assert ready['status'] == 'ready', ready['error']
        assert ready['parse_result']['record_count'] == 2
        assert 'records' not in ready['parse_result']
        evidence = service.read_evidence(doc['document_id'])
        assert [e['locator']['record_number'] for e in evidence] == [1, 2]
        assert [e['price'] for e in evidence] == ['1234.50', None]
        assert [e['price_status'] for e in evidence] == ['valid', 'invalid']
        assert evidence[0]['headers'] == list(HEADERS)
    finally:
        service.stop()
    def forbidden(*args, **kwargs):
        raise AssertionError('Restoration must not parse or call a provider')
    monkeypatch.setattr('app.parsing.parse_document', forbidden)
    restored = DocumentService(tmp_path)
    restored.start()
    try:
        assert restored.get(doc['document_id'])['status'] == 'ready'
        assert restored.read_evidence(doc['document_id']) == evidence
        assert restored.lookup_orders(['001'], [doc['document_id']])['total'] == 2
    finally:
        restored.stop()


@pytest.fixture
def service(tmp_path):
    value = DocumentService(tmp_path)
    value.start()
    yield value
    value.stop()


def publish(service, rows, name='prices.csv'):
    document_id = service.submit(name, contents(rows))['document_id']
    assert terminal(service, document_id)['status'] == 'ready'
    return document_id


def test_exact_scope_duplicates_missing_and_pagination(service):
    first = publish(service, [row('001Ab-9'), row('001Ab-9', 'bad'), row('002')])
    second = publish(service, [row('001Ab-9')])
    excluded = publish(service, [row('001Ab-9')])
    result = service.lookup_orders([' 001Ab-9 ', '002', '001ab-9', '1Ab-9', '001Ab-9'], [second, first, first], limit=2)
    assert result['document_ids'] == [second, first]
    assert result['order_ids'] == ['001Ab-9', '002', '001ab-9', '1Ab-9']
    assert result['counts'] == [{'order_id': k, 'count': n} for k, n in
                                [('001Ab-9', 3), ('002', 1), ('001ab-9', 0), ('1Ab-9', 0)]]
    assert result['unmatched_order_ids'] == ['001ab-9', '1Ab-9']
    assert result['total'] == 4 and result['has_more']
    remaining = service.lookup_orders(result['order_ids'], [second, first], offset=2, limit=2)
    assert not remaining['has_more']
    records = result['records'] + remaining['records']
    assert [(r['document_id'], r['locator']['record_number']) for r in records[:3]] == sorted([(first, 1), (first, 2), (second, 1)])
    assert all(r['document_id'] != excluded for r in records)
    assert records[-1]['order_id'] == '002'
    assert all(r['original_filename'] == 'prices.csv' for r in records)
    assert len({(r['document_id'], r['evidence_id']) for r in records}) == 4
    invalid = next(r for r in records if r['price_status'] == 'invalid')
    assert invalid['raw_values'][3] == 'bad' and invalid['price'] is None
    assert service.lookup_orders(['001Ab-9'], [first])['total'] == 2
    empty = service.lookup_orders(['001Ab-9'], [first], offset=9)
    assert empty['total'] == 2 and empty['records'] == [] and not empty['has_more']


def test_exact_keys_are_literals_and_many_queries_are_not_sql_variables(service):
    keys = ["x' OR 1=1 --", 'A B', 'A-B', 'A%B', 'A_B', '0000']
    doc = publish(service, [row(k) for k in keys])
    result = service.lookup_orders(keys + [f'absent-{n}' for n in range(2000)], [doc])
    assert [r['order_id'] for r in result['records']] == keys
    assert result['total'] == len(keys)
    assert len(result['unmatched_order_ids']) == 2000
    assert service.lookup_orders(['AB', 'a b', '0', 'A%'], [doc])['total'] == 0


def test_many_duplicate_matches_page_without_loss_and_keep_multiline_values(service):
    original = row('0001', '12345678901234567890,12345678901234567890')
    original[2] = 'Quoted; "description"\ncontinued'
    doc = publish(service, [original for _ in range(205)])
    pages = [service.lookup_orders(['0001'], [doc], offset=n, limit=100) for n in (0, 100, 200)]
    assert [p['total'] for p in pages] == [205, 205, 205]
    assert [p['has_more'] for p in pages] == [True, True, False]
    records = [r for page in pages for r in page['records']]
    assert [r['locator']['record_number'] for r in records] == list(range(1, 206))
    assert len({r['evidence_id'] for r in records}) == 205
    assert all(r['raw_values'] == original for r in records)
    assert all(r['price'] == '12345678901234567890.12345678901234567890' for r in records)


@pytest.mark.parametrize('orders,documents', [([], ['d']), ([1], ['d']), ([' '], ['d']),
    ('001', ['d']), (['001'], []), (['001'], [1]), (['001'], 'd')])
def test_invalid_lookup_inputs(service, orders, documents):
    with pytest.raises(DocumentError) as error:
        service.lookup_orders(orders, documents)
    assert error.value.code == 'invalid_query'


@pytest.mark.parametrize('offset,limit', [(-1, 2), (0, 0), (0, 101), (True, 2), (0, 1.5)])
def test_invalid_lookup_pagination(service, offset, limit):
    with pytest.raises(DocumentError) as error:
        service.lookup_orders(['001'], ['d'], offset, limit)
    assert error.value.code == 'invalid_pagination'


def test_scope_is_all_or_error_and_missing_fields_do_not_become_zero(service):
    doc = publish(service, [row('001', ''), row('', '0')])
    assert service.get(doc)['parse_result']['indexed_record_count'] == 1
    result = service.lookup_orders(['001'], [doc])
    assert result['records'][0]['price'] is None
    assert result['records'][0]['price_status'] == 'missing'
    assert len(service.read_evidence(doc)) == 2
    with pytest.raises(DocumentError) as error:
        service.lookup_orders(['001'], [doc, 'unknown'])
    assert error.value.code == 'document_not_found'
    missing = service.submit('empty-keys.csv', contents([row('', 'bad')]))['document_id']
    failed = terminal(service, missing)
    assert failed['error']['code'] == 'csv_no_order_ids'
    assert failed['parse_result']['record_count'] == 1
    with pytest.raises(DocumentError) as error:
        service.lookup_orders(['001'], [doc, missing])
    assert error.value.code == 'document_not_ready'


def test_staged_records_are_hidden_failure_isolated_retry_does_not_duplicate(service, monkeypatch):
    old = publish(service, [row('001')])
    stage = service._csv.stage
    entered, release = Event(), Event()
    def fail_after_stage(*args):
        stage(*args)
        entered.set()
        assert release.wait(5)
        raise OSError('private storage detail')
    monkeypatch.setattr(service._csv, 'stage', fail_after_stage)
    new = service.submit('new.csv', contents([row('002'), row('002')]))['document_id']
    try:
        assert entered.wait(5)
        assert service.get(new)['stage'] == 'indexing'
        assert service.lookup_orders(['001'], [old])['total'] == 1
        with pytest.raises(DocumentError):
            service.read_evidence(new)
        with pytest.raises(DocumentError):
            service.lookup_orders(['002'], [old, new])
    finally:
        release.set()
    failed = terminal(service, new)
    assert failed['error']['code'] == 'processing_failed'
    assert 'private storage' not in str(failed)
    monkeypatch.setattr(service._csv, 'stage', stage)
    service.retry(new)
    assert terminal(service, new)['status'] == 'ready'
    assert service.lookup_orders(['002'], [new])['total'] == 2
    assert len(service.read_evidence(new)) == 2


def test_stop_prevents_staged_csv_publication(tmp_path, monkeypatch):
    service = DocumentService(tmp_path)
    service.start()
    stage = service._csv.stage
    entered, release = Event(), Event()
    def blocked(*args):
        stage(*args)
        entered.set()
        release.wait(5)
    monkeypatch.setattr(service._csv, 'stage', blocked)
    doc = service.submit('late.csv', contents([row()]))['document_id']
    try:
        assert entered.wait(5)
        service.stop()
    finally:
        release.set()
        service.stop()
    assert service.get(doc)['error']['code'] == 'processing_interrupted'
    with pytest.raises(DocumentError):
        service.lookup_orders(['001Ab-9'], [doc])


@pytest.mark.parametrize('mutation', [
    'DELETE FROM csv_records',
    "UPDATE csv_records SET price='999'",
    'DELETE FROM csv_documents',
    'DELETE FROM document_parses',
    "UPDATE document_parses SET payload='{}'",
])
def test_incomplete_or_corrupt_restart_never_queries(tmp_path, mutation):
    service = DocumentService(tmp_path)
    service.start()
    doc = publish(service, [row()])
    service.stop()
    # This is an isolated, stopped test database, never a running deployment.
    with sqlite3.connect(service.database) as db:
        db.execute(mutation)
    restored = DocumentService(tmp_path)
    restored.start()
    try:
        assert restored.get(doc)['error']['code'] == 'index_restore_failed'
        with pytest.raises(DocumentError):
            restored.lookup_orders(['001Ab-9'], [doc])
        restored.retry(doc)
        assert terminal(restored, doc)['status'] == 'ready'
        assert restored.lookup_orders(['001Ab-9'], [doc])['total'] == 1
    finally:
        restored.stop()


def test_csv_http_summary_and_record_evidence(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        response = client.post('/api/documents', files={'file': ('prices.csv', contents([row('001', ''), row('001', 'bad')]).getvalue())})
        assert response.status_code == 202 and response.json()['status'] == 'queued'
        doc = response.json()['document_id']
        assert terminal(app.state.documents, doc)['status'] == 'ready'
        status = client.get(f'/api/documents/{doc}').json()
        assert status['parsing'] == {'kind': 'csv', 'parser_version': 'price-list-v1',
            'record_count': 2, 'indexed_record_count': 2,
            'price_counts': {'valid': 0, 'missing': 1, 'invalid': 1}}
        assert status['warnings'][0]['record_number'] == 1
        evidence = client.get(f'/api/documents/{doc}/evidence?offset=1&limit=1').json()
        assert len(evidence) == 1
        assert evidence[0]['locator'] == {'kind': 'csv', 'record_number': 2}
        assert evidence[0]['headers'] == list(HEADERS)
        assert evidence[0]['price_status'] == 'invalid' and evidence[0]['price'] is None
        assert client.get('/api/documents').json()[0] == status


def test_ready_non_csv_scope_rejected(tmp_path):
    from test_lifecycle import Pipeline
    pipeline = Pipeline()
    pipeline.release.set()
    service = DocumentService(tmp_path)
    service.start(pipeline)
    try:
        doc = service.submit('fixture.pdf', BytesIO(b'%PDF-fixture'))['document_id']
        assert terminal(service, doc)['status'] == 'ready'
        with pytest.raises(DocumentError) as error:
            service.lookup_orders(['001'], [doc])
        assert error.value.code == 'document_not_csv'
    finally:
        service.stop()
