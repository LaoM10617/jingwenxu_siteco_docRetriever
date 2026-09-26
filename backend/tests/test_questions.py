"""T-008/T-009 through real document publication and question tools."""
from io import BytesIO

import pytest

from app.documents import DocumentService, DocumentError
from app.questions import QuestionTools
from test_csv_lifecycle import publish, service
from test_csv_parsing import row
from app.processing import DocumentProcessor
from app.retrieval.pdf import PdfRetriever
from test_pdf_publication import Gateway
from test_parsing import pdf_file
from test_lifecycle import wait_status


def test_complete_scope_rejected_before_planning(tmp_path):
    documents = DocumentService(tmp_path)
    pending = documents.submit('pending.pdf', BytesIO(b'%PDF-fixture'))['document_id']
    tools = QuestionTools(documents, None)

    def forbidden(*args):
        raise AssertionError('Invalid scope must not call a model')

    for question, ids, code in [(' ', [pending], 'invalid_question'),
                                ('Power?', ['missing'], 'document_not_found'),
                                ('Power?', [pending], 'document_not_ready')]:
        with pytest.raises(DocumentError) as error:
            tools.prepare({'conversation_id': 'a', 'question': question,
                           'document_ids': ids}, planner=forbidden)
        assert error.value.code == code


def test_csv_plan_preserves_exact_matches_sources_and_misses(service):
    identity = publish(service, [row('001Ab-9', '1.234,50'), row('001Ab-9', ''), row('002', 'bad')])
    tools = QuestionTools(service, None)
    request = {'conversation_id': 'a', 'question': 'Prices for 001Ab-9 and 001ab-9?',
               'document_ids': [identity, identity]}
    plan = {'tools': [{'tool': 'lookup_orders', 'document_ids': [identity],
                       'order_ids': ['001Ab-9', '001ab-9']}]}
    result = tools.prepare(request, planner=lambda *args: plan)
    assert result['document_ids'] == [identity]
    assert result['tools'][0]['result']['total'] == 2
    assert result['tools'][0]['result']['unmatched_order_ids'] == ['001ab-9']
    assert [e['citation_id'] for e in result['evidence']] == ['S1', 'S2']
    assert [e['source']['price'] for e in result['evidence']] == ['1234.50', None]
    assert result['evidence'][0]['source']['locator']['record_number'] == 1
    assert result['warnings']


@pytest.mark.parametrize('tool', [
    {'tool': 'python', 'code': 'print(1)'},
    {'tool': 'lookup_orders', 'document_ids': ['outside'], 'order_ids': ['001']},
    {'tool': 'lookup_orders', 'document_ids': [], 'order_ids': ['001']},
    {'tool': 'lookup_orders', 'document_ids': ['REPLACE'], 'order_ids': [1]},
    {'tool': 'lookup_orders', 'document_ids': ['REPLACE'], 'order_ids': ['hallucinated']},
    {'tool': 'lookup_orders', 'document_ids': ['REPLACE'], 'order_ids': ['001'], 'sql': 'SELECT 1'},
])
def test_invalid_plan_has_no_partial_tool_execution(service, tool):
    identity = publish(service, [row('001')])
    if tool.get('document_ids') == ['REPLACE']:
        tool = {**tool, 'document_ids': [identity]}
    with pytest.raises(DocumentError) as error:
        QuestionTools(service, None).prepare(
            {'conversation_id': 'a', 'question': '001', 'document_ids': [identity]},
            planner=lambda *args: {'tools': [tool]})
    assert error.value.code == 'invalid_tool_plan'


@pytest.fixture
def mixed(tmp_path):
    gateway = Gateway()
    documents = DocumentService(tmp_path / 'runtime')
    documents.start(DocumentProcessor(gateway))
    pdf = documents.submit('models.pdf', BytesIO(pdf_file(tmp_path, [
        'AB-123 power: 20 W', 'ZX-456 power: 0.025 kW']).read_bytes()))['document_id']
    wait_status(documents, pdf, 'ready')
    csv = publish(documents, [row('001', '12,50')])
    yield documents, gateway, pdf, csv
    documents.stop()


def test_pdf_and_csv_scopes_and_conversations_are_independent(mixed):
    documents, gateway, pdf, csv = mixed
    tools = QuestionTools(documents, PdfRetriever(documents, documents.lexical, gateway))
    first = tools.prepare({'conversation_id': 'a', 'question': 'AB-123 power', 'document_ids': [pdf]})
    assert all(e['source']['document_id'] == pdf for e in first['evidence'])
    assert first['evidence'][0]['source']['source_spans']
    assert first['evidence'][0]['source']['locator']['kind'] == 'pdf'
    second = tools.prepare({'conversation_id': 'b', 'question': '001 price', 'document_ids': [csv]},
        planner=lambda question, metadata, budget: {'tools': [
            {'tool': 'lookup_orders', 'document_ids': [csv], 'order_ids': ['001']}]})
    assert second['evidence'][0]['citation_id'] == 'S1'
    assert second['evidence'][0]['source']['document_id'] == csv
    assert first['conversation_id'] == 'a' and second['conversation_id'] == 'b'
    assert first['evidence'][0]['source']['document_id'] == pdf
    # Validate the entire plan before even the valid first PDF route runs.
    before = list(gateway.calls)
    with pytest.raises(DocumentError):
        tools.prepare({'conversation_id': 'a', 'question': '001', 'document_ids': [pdf, csv]},
            planner=lambda *args: {'tools': [{'tool': 'retrieve_pdf', 'document_ids': [pdf]},
                                           {'tool': 'lookup_orders', 'document_ids': [pdf], 'order_ids': ['001']}]})
    assert gateway.calls == before


def test_question_deadline_discards_late_plan_before_tools(service):
    from app.questions import QuestionBudget
    clock = [0.0]
    budget = QuestionBudget(now=lambda: clock[0])
    identity = publish(service, [row('001')])
    def late(*args):
        clock[0] = 241
        return {'tools': [{'tool': 'lookup_orders', 'document_ids': [identity], 'order_ids': ['001']}]}
    with pytest.raises(DocumentError) as error:
        QuestionTools(service, None).prepare(
            {'conversation_id': 'a', 'question': '001', 'document_ids': [identity]}, planner=late, budget=budget)
    assert error.value.code == 'question_timeout'


def test_missing_order_clarification_and_exact_miss_do_not_search_pdf(mixed):
    documents, gateway, pdf, csv = mixed
    tools = QuestionTools(documents, PdfRetriever(documents, documents.lexical, gateway))
    before = list(gateway.calls)
    empty = tools.prepare({'conversation_id': 'a', 'question': 'What is the price?', 'document_ids': [csv]},
                          planner=lambda *args: {'tools': []})
    assert empty['unresolved'] == [{'code': 'needs_clarification'}]
    missing = tools.prepare({'conversation_id': 'a', 'question': 'missing-001', 'document_ids': [pdf, csv]},
        planner=lambda *args: {'tools': [{'tool': 'lookup_orders', 'document_ids': [csv],
                                        'order_ids': ['missing-001']}]})
    assert missing['tools'][0]['result']['total'] == 0
    assert missing['unresolved'][0]['code'] == 'exact_not_found'
    assert not missing['evidence'] and gateway.calls == before


def test_multiple_routes_keep_miss_and_pdf_evidence_separate(mixed):
    documents, gateway, pdf, csv = mixed
    result = QuestionTools(documents, PdfRetriever(documents, documents.lexical, gateway)).prepare(
        {'conversation_id': 'a', 'question': 'AB-123 power and price of 999', 'document_ids': [pdf, csv]},
        planner=lambda *args: {'tools': [
            {'tool': 'lookup_orders', 'document_ids': [csv], 'order_ids': ['999']},
            {'tool': 'retrieve_pdf', 'document_ids': [pdf]}]})
    assert result['unresolved'][0]['code'] == 'exact_not_found'
    assert result['tools'][0]['result']['total'] == 0
    assert result['tools'][1]['document_ids'] == [pdf]
    assert result['evidence']


def test_csv_large_result_reports_full_count_without_claiming_full_context(service):
    identity = publish(service, [row('001')] * 55)
    result = QuestionTools(service, None).prepare(
        {'conversation_id': 'a', 'question': '001', 'document_ids': [identity]},
        planner=lambda *args: {'tools': [{'tool': 'lookup_orders', 'document_ids': [identity], 'order_ids': ['001']}]})
    assert len(result['evidence']) == 50
    assert result['tools'][0]['result']['total'] == 55
    assert result['tools'][0]['result']['has_more']
    assert result['unresolved'] == [{'code': 'results_paginated', 'total': 55}]


@pytest.mark.parametrize('changes', [{'history': ['another conversation']}, {'question': 123},
                                    {'conversation_id': ''}, {'document_ids': []}])
def test_question_rejects_unknown_history_and_coercion(service, changes):
    identity = publish(service, [row('001')])
    with pytest.raises(DocumentError) as error:
        QuestionTools(service, None).prepare(
            {'conversation_id': 'a', 'question': '001', 'document_ids': [identity], **changes})
    assert error.value.code == 'invalid_question'


def test_duplicate_route_and_substring_order_are_rejected(service):
    identity = publish(service, [row('001')])
    tool = {'tool': 'lookup_orders', 'document_ids': [identity], 'order_ids': ['001']}
    for question, plan in [('001', [tool, tool]), ('X001', [tool]), ('001-A', [tool])]:
        with pytest.raises(DocumentError) as error:
            QuestionTools(service, None).prepare(
                {'conversation_id': 'a', 'question': question, 'document_ids': [identity]},
                planner=lambda *args: {'tools': plan})
        assert error.value.code == 'invalid_tool_plan'


def test_deadline_and_wait_callback_reach_embedding(mixed):
    from app.questions import QuestionBudget
    from app.embeddings import EmbeddingError
    documents, gateway, pdf, csv = mixed
    clock = [0.0]
    class WaitingProvider(Gateway):
        def embed(self, texts, *, input_type, stop=None, on_wait=None):
            on_wait()
            clock[0] = 241
            assert stop.is_set()
            raise EmbeddingError('embedding_interrupted')
    observed = []
    tools = QuestionTools(documents, PdfRetriever(documents, documents.lexical, WaitingProvider()))
    with pytest.raises(DocumentError) as error:
        tools.prepare({'conversation_id': 'a', 'question': 'power', 'document_ids': [pdf]},
                      budget=QuestionBudget(now=lambda: clock[0]), on_wait=lambda: observed.append('waiting'))
    assert error.value.code == 'question_timeout'
    assert observed == ['waiting'] and documents.get(pdf)['status'] == 'ready'


def test_plan_cannot_silently_shrink_selected_same_type_scope(service):
    first = publish(service, [row('001')])
    second = publish(service, [row('001')])
    with pytest.raises(DocumentError) as error:
        QuestionTools(service, None).prepare(
            {'conversation_id': 'a', 'question': '001', 'document_ids': [first, second]},
            planner=lambda *args: {'tools': [{'tool': 'lookup_orders', 'document_ids': [first],
                                              'order_ids': ['001']}]})
    assert error.value.code == 'invalid_tool_plan'
