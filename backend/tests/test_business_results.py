"""M3.3 business outcomes and source publication through real task HTTP."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.processing import DocumentProcessor
from test_app import settings_for
from test_multi_document_tasks import TaskGateway, ScopeModel, upload, finish
from test_question_tasks import csv_bytes
from test_csv_parsing import row
from test_parsing import pdf_file


@pytest.mark.parametrize('query_pdf', [False, True])
def test_exact_csv_miss_stays_separate_from_pdf_evidence(tmp_path, query_pdf):
    class Mixed(ScopeModel):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'plan' and not query_pdf:
                result['tools'] = [t for t in result['tools'] if t['tool'] == 'lookup_orders']
            return result
    model, gateway = Mixed(), TaskGateway()
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(gateway), model=model)) as client:
        pdf = upload(client, 'parameters.pdf', pdf_file(tmp_path, ['001 power: 20 W']).read_bytes())
        csv = upload(client, 'prices.csv', csv_bytes([row('001-A', '99,00')]))
        before = len(gateway.calls)
        task = finish(client, {'conversation_id':'a','request_id':'r',
            'question':'Power and exact price of 001?', 'document_ids':[pdf,csv]})
        answer = task['answer']
        assert answer['outcome'] == ('partial' if query_pdf else 'exact_not_found')
        assert answer['unresolved'] == [{'code':'exact_not_found','order_ids':['001'],'document_ids':[csv]}]
        lookup = next(t for t in answer['tool_results'] if t['tool'] == 'lookup_orders')
        assert lookup['document_ids'] == [csv] and lookup['result']['total'] == 0
        assert lookup['result']['unmatched_order_ids'] == ['001']
        if query_pdf:
            assert {s['document_id'] for s in answer['citations']} == {pdf}
            assert answer['segments'] and '99,00' not in str(answer['segments'])
        else:
            assert answer['citations'] == answer['segments'] == []
            assert len(gateway.calls) == before
            assert [p['phase'] for p in model.payloads] == ['plan']


def test_omitted_and_invalid_sources_withdraw_whole_segments_but_paging_keeps_duplicates(tmp_path):
    class Limited(ScopeModel):
        def generate(self, system, payload, schema, budget):
            if payload['phase'] == 'plan':
                return super().generate(system, payload, schema, budget)
            self.payloads.append(payload)
            shown = {e['citation_id'] for e in payload['bundle']['evidence']}
            assert 'S1' in shown and 'S51' not in shown
            return {'outcome':'answered','segments':[
                {'text':'One verified price is 12,50, valid from 01.06.2026.',
                 'citation_ids':['S1'],'calculation_ids':[]},
                {'text':'WITHDRAW entire unsupported conclusion.',
                 'citation_ids':['S1','S51'],'calculation_ids':[]}],
                'gaps':['Only the supplied records are represented.'],'calculations':[]}
    model = Limited()
    with TestClient(create_app(settings_for(tmp_path), processor=DocumentProcessor(), model=model)) as client:
        first = upload(client, 'same.csv', csv_bytes([row('001','12,50')] * 55))
        second = upload(client, 'same.csv', csv_bytes([row('001','12,50')]))
        task = finish(client, {'conversation_id':'a','request_id':'r','question':'Price 001?',
                               'document_ids':[first,second]})
        answer = task['answer']
        assert answer['outcome'] == 'partial'
        assert answer['validation']['rejected_segments'] == 1
        assert len(answer['segments']) == len(answer['citations']) == 1
        assert 'WITHDRAW' not in str(answer)
        assert answer['context']['omitted_evidence_count'] > 0
        assert answer['tool_results'][0]['result']['total'] == 56
        assert answer['tool_results'][0]['result']['has_more'] is True
        source = answer['citations'][0]
        assert source['raw_values'][source['headers'].index('Listenpreis')] == '12,50'
        assert source['raw_values'][source['headers'].index('gültig ab')] == '01.06.2026'
        calls = len(model.payloads)
        records = []
        for offset in (0,20,40):
            page = client.get(f"/api/questions/{task['question_id']}/csv/0",
                params={'conversation_id':'a','offset':offset,'limit':20}).json()
            assert page['total'] == 56
            records.extend(page['records'])
        assert len({(s['document_id'],s['evidence_id']) for s in records}) == 56
        assert {s['document_id'] for s in records} == {first,second}
        assert sorted(s['locator']['record_number'] for s in records if s['document_id']==first) == list(range(1,56))
        assert len(model.payloads) == calls
        restored = client.get('/api/questions/' + task['question_id'],params={'conversation_id':'a'}).json()
        assert restored['answer'] == answer


@pytest.mark.parametrize('wrong_product', [True, False])
def test_unverified_product_or_incompatible_conditions_cannot_publish_calculated_claim(tmp_path, wrong_product):
    class Numeric(ScopeModel):
        def generate(self, system, payload, schema, budget):
            self.payloads.append(payload)
            evidence = payload['bundle']['evidence']
            refs = {e['source']['text'].split()[0]: {'citation_id':e['citation_id'],
                'product':e['source']['text'].split()[0], 'parameter':'power', 'span_index':0} for e in evidence}
            if payload['phase'] == 'answer':
                operation = ({'tool':'convert','fact':{**refs['A'],'product':'B'},'unit':'kW'} if wrong_product else
                             {'tool':'compare','left':refs['A'],'right':refs['B'],'operator':'lt'})
                return {'outcome':'partial','segments':[],'gaps':[],
                        'calculations':[{'calculation_id':'C1','operation':operation}]}
            assert payload['calculations'][0]['result'] == {'status':'unavailable',
                'reason':'unverified_relationship' if wrong_product else 'incomparable_facts'}
            return {'outcome':'answered','segments':[
                *[{'text':e['source']['text'],'citation_ids':[e['citation_id']], 'calculation_ids':[]} for e in evidence],
                {'text':'WITHDRAW calculated ownership or comparison.',
                 'citation_ids':[e['citation_id'] for e in evidence],'calculation_ids':['C1']}],
                'gaps':['The calculation is unavailable; the original product conditions differ or ownership is unverified.'],
                'calculations':[]}
    model = Numeric()
    with TestClient(create_app(settings_for(tmp_path / 'runtime'),
                    processor=DocumentProcessor(TaskGateway()), model=model)) as client:
        pdf = upload(client, 'products.pdf', pdf_file(tmp_path,
            ['A power: 20 W (at 25 C)', 'B power: 30 W (at 40 C)']).read_bytes())
        task = finish(client, {'conversation_id':'a','request_id':'r','question':'Compare A and B power',
                               'document_ids':[pdf]})
        answer = task['answer']
        assert answer['outcome'] == 'partial'
        assert answer['validation']['rejected_segments'] == 1
        assert 'WITHDRAW' not in str(answer)
        assert len(answer['segments']) == len(answer['citations']) == 2
        sources = {s['locator']['page_number']:s for s in answer['citations']}
        assert sources[1]['text'] == 'A power: 20 W (at 25 C)'
        assert sources[2]['text'] == 'B power: 30 W (at 40 C)'
        assert answer['gaps']
