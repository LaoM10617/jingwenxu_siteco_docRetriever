"""Retained evidence preparation: selected scope, citations and exact CSV lookup."""
import time
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_parsing import pdf_file
from test_pdf_publication import Gateway
from document_test_helpers import csv_bytes
from test_csv_parsing import row


class TaskGateway(Gateway):
    def embed(self, texts, *, input_type, stop=None, on_wait=None, on_start=None):
        if on_start:
            on_start()
        return super().embed(texts, input_type=input_type, stop=stop, on_wait=on_wait)


class ScopeModel:
    provider = 'test'
    model = 'controlled'

    def __init__(self):
        self.payloads = []

    def generate(self, system, payload, schema, budget):
        self.payloads.append(deepcopy(payload))
        if payload['phase'] == 'plan':
            tools = []
            for media, route in [('application/pdf', 'retrieve_pdf'), ('text/csv', 'lookup_orders')]:
                ids = [d['document_id'] for d in payload['documents'] if d['media_type'] == media]
                if ids:
                    tools.append({'tool': route, 'document_ids': ids,
                                  **({'order_ids': ['001']} if route == 'lookup_orders' else {})})
            return {'tools': tools}
        return {'outcome': 'answered', 'segments': [
            {'text': e['source']['text'], 'citation_ids': [e['citation_id']], 'calculation_ids': []}
            for e in payload['bundle']['evidence']], 'gaps': [], 'calculations': []}


def upload(client, name, content):
    response = client.post('/api/documents', files={'file': (name, content)})
    assert response.status_code == 202
    identity = response.json()['document_id']
    for _ in range(250):
        doc = client.get('/api/documents/' + identity).json()
        if doc['status'] == 'ready':
            return identity
        assert doc['status'] != 'failed', doc
        time.sleep(.02)
    pytest.fail('Document did not become ready')


def finish(client, body):
    # Exercise the retained evidence/answer seam, independently of retired HTTP jobs.
    request = {k: v for k, v in body.items() if k != 'request_id'}
    answer = client.app.state.bindings.answers().answer(request, on_wait=lambda: None, on_stage=lambda stage: None)
    return {'document_ids': body['document_ids'], 'answer': answer}


@pytest.mark.parametrize('duplicate', [False, True])
@pytest.mark.parametrize('kind', ['pdf', 'csv', 'mixed'])
def test_multi_document_scope_preserves_duplicates_and_excludes_unselected(tmp_path, kind, duplicate):
    model = ScopeModel()
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(TaskGateway()), model=model)) as client:
        pdf_bytes = pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes()
        pdfs = [upload(client, 'same.pdf', pdf_bytes), upload(client, 'same.pdf', pdf_bytes if duplicate else
            pdf_file(tmp_path, ['ZX-456 power: 30 W']).read_bytes())]
        upload(client, 'outside.pdf', pdf_file(tmp_path, ['OUTSIDE power: 999 W']).read_bytes())
        csvs = [upload(client, 'same.csv', csv_bytes([row('001', price)]))
                for price in ('12,50', '12,50' if duplicate else '25,00')]
        outside = upload(client, 'outside.csv', csv_bytes([row('001', '999,00')]))
        scope = pdfs if kind == 'pdf' else csvs if kind == 'csv' else pdfs + csvs
        body = {'conversation_id': 'first', 'request_id': 'r1',
                'question': 'AB-123 power and price 001?', 'document_ids': scope}
        task = finish(client, body)
        assert task['document_ids'] == scope
        answer = task['answer']
        assert answer['outcome'] == 'answered'
        assert {s['document_id'] for s in answer['citations']} == set(scope)
        assert len(answer['citations']) == len(scope)
        assert len({(s['document_id'], s['evidence_id']) for s in answer['citations']}) == len(scope)
        assert outside not in {s['document_id'] for s in answer['citations']}
        for tool in answer['tool_results']:
            assert set(tool['document_ids']) == set(pdfs if tool['tool'] == 'retrieve_pdf' else csvs)
        if kind != 'pdf':
            index = next(i for i, t in enumerate(answer['tool_results']) if t['tool'] == 'lookup_orders')
            # A later question changes scope; old task paging must still use its original two CSVs.
            finish(client, {**body, 'conversation_id': 'second', 'document_ids': [outside]})
            pages = [client.app.state.documents.lookup_orders(['001'], csvs, offset=offset, limit=1)
                     for offset in (0, 1)]
            assert [p['total'] for p in pages] == [2, 2]
            assert {p['records'][0]['document_id'] for p in pages} == set(csvs)
            assert sorted(p['records'][0]['price'] for p in pages) == (['12.50', '12.50'] if duplicate else ['12.50', '25.00'])



@pytest.mark.parametrize('unavailable', ['unknown', 'processing'])
def test_entire_mixed_scope_is_rejected_before_provider_calls(tmp_path, unavailable):
    gateway, model = TaskGateway(), ScopeModel()
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(gateway), model=model)) as client:
        ready_csv = upload(client, 'prices.csv', csv_bytes([row('001')]))
        identity = 'unknown'
        if unavailable == 'processing':
            gateway.entered.clear()
            gateway.release.clear()
            content = pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes()
            response = client.post('/api/documents', files={'file': ('pending.pdf', content)})
            assert response.status_code == 202
            identity = response.json()['document_id']
            assert gateway.entered.wait(2)
        try:
            calls = list(gateway.calls)
            from app.documents import DocumentError
            with pytest.raises(DocumentError) as error:
                finish(client, {'conversation_id': 'a', 'request_id': 'r',
                    'question': 'AB-123 power and price 001?', 'document_ids': [ready_csv, identity]})
            assert error.value.code == ('document_not_found' if unavailable == 'unknown' else 'document_not_ready')
            assert model.payloads == []
            assert gateway.calls == calls
        finally:
            gateway.release.set()


@pytest.mark.parametrize('route', ['retrieve_pdf', 'lookup_orders'])
def test_mixed_plan_cannot_narrow_either_selected_document_type(tmp_path, route):
    class Narrowed(ScopeModel):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'plan':
                next(t for t in result['tools'] if t['tool'] == route)['document_ids'].pop()
            return result

    gateway, model = TaskGateway(), Narrowed()
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(gateway), model=model)) as client:
        content = pdf_file(tmp_path, ['AB-123 power: 20 W']).read_bytes()
        scope = [upload(client, 'same.pdf', content) for _ in range(2)]
        scope += [upload(client, 'same.csv', csv_bytes([row('001')])) for _ in range(2)]
        calls = list(gateway.calls)
        from app.documents import DocumentError
        with pytest.raises(DocumentError) as error:
            finish(client, {'conversation_id':'a','request_id':'r',
                'question':'AB-123 power and price 001?', 'document_ids':scope})
        assert error.value.code == 'invalid_tool_plan'
        assert gateway.calls == calls
        assert [p['phase'] for p in model.payloads] == ['plan']
