"""T-009: source-bound calculations, never model-supplied numeric operands."""
from app.question_numbers import EvidenceTools
from app.questions import QuestionTools
from test_csv_lifecycle import publish, service
from test_csv_parsing import row
from test_questions import mixed
from app.retrieval.pdf import PdfRetriever
from io import BytesIO
import pytest
from app.documents import DocumentService, DocumentError
from app.processing import DocumentProcessor
from test_pdf_publication import Gateway
from test_parsing import pdf_file
from test_lifecycle import wait_status


@pytest.fixture
def pdf_tools(tmp_path):
    gateway = Gateway()
    documents = DocumentService(tmp_path / 'runtime')
    documents.start(DocumentProcessor(gateway))
    def prepare(texts, commands=False):
        identity = documents.submit('facts.pdf', BytesIO(pdf_file(tmp_path, texts, commands=commands).read_bytes()))['document_id']
        wait_status(documents, identity, 'ready')
        bundle = QuestionTools(documents, PdfRetriever(documents, documents.lexical, gateway)).prepare(
            {'conversation_id': 'a', 'question': 'A parameter', 'document_ids': [identity]})
        return bundle, EvidenceTools(bundle)
    yield prepare
    documents.stop()


def test_price_comparison_uses_stored_decimal_and_missing_is_not_zero(service):
    identity = publish(service, [row('001', '123456789012345678901234567890,01'),
                                 row('002', '123456789012345678901234567890,02'), row('003', '')])
    bundle = QuestionTools(service, None).prepare(
        {'conversation_id': 'a', 'question': '001 002 003', 'document_ids': [identity]},
        planner=lambda *args: {'tools': [{'tool': 'lookup_orders', 'document_ids': [identity],
                                          'order_ids': ['001', '002', '003']}]})
    tools = EvidenceTools(bundle)
    left = {'citation_id': 'S1', 'parameter': 'price'}
    right = {'citation_id': 'S2', 'parameter': 'price'}
    result = tools.execute({'tool': 'compare', 'left': left, 'operator': 'lt', 'right': right})
    assert result['status'] == 'ok' and result['result'] is True
    assert result['left']['value'] == '123456789012345678901234567890.01'
    assert result['left']['raw_value'] == '123456789012345678901234567890,01'
    assert result['left']['unit'] is None
    missing = tools.execute({'tool': 'compare', 'left': left, 'operator': 'gt',
                             'right': {'citation_id': 'S3', 'parameter': 'price'}})
    assert missing['status'] == 'unavailable' and missing['reason'] == 'price_missing'


def test_pdf_explicit_product_parameter_conversion_and_comparison(mixed):
    documents, gateway, pdf, csv = mixed
    bundle = QuestionTools(documents, PdfRetriever(documents, documents.lexical, gateway)).prepare(
        {'conversation_id': 'a', 'question': 'AB-123 ZX-456 power', 'document_ids': [pdf]})
    refs = {e['source']['text'].split()[0]: {'citation_id': e['citation_id'], 'parameter': 'power',
            'product': e['source']['text'].split()[0], 'span_index': 0} for e in bundle['evidence']}
    tools = EvidenceTools(bundle)
    converted = tools.execute({'tool': 'convert', 'fact': refs['ZX-456'], 'unit': 'W'})
    assert converted['status'] == 'ok'
    assert converted['converted']['value'] == '25'
    assert converted['converted']['factor'] == '1000'
    assert converted['fact']['raw_value'] == '0.025'
    compared = tools.execute({'tool': 'compare', 'left': refs['AB-123'], 'operator': 'lt', 'right': refs['ZX-456']})
    assert compared['status'] == 'ok' and compared['result'] is True
    assert compared['right']['unit'] == 'kW'
    assert compared['right_converted']['value'] == '25'
    wrong = tools.execute({'tool': 'convert', 'fact': {**refs['AB-123'], 'product': 'ZX-456'}, 'unit': 'W'})
    assert wrong['status'] == 'unavailable' and wrong['reason'] == 'unverified_relationship'
    incompatible = tools.execute({'tool': 'convert', 'fact': refs['AB-123'], 'unit': 'kg'})
    assert incompatible['reason'] == 'incompatible_unit'


@pytest.mark.parametrize('text,parameter,target,reason', [
    ('A B power: 20 W', 'power', 'W', 'unverified_relationship'),
    ('A power: 1,234 W', 'power', 'W', 'ambiguous_numeric_format'),
    ('A power: NaN W', 'power', 'W', 'unverified_relationship'),
    ('A power: 20 kg', 'power', 'W', 'incompatible_unit'),
    ('A power: 20 W; B power: 30 W', 'power', 'W', 'unverified_relationship'),
])
def test_ambiguous_pdf_keeps_evidence_without_inventing_numeric_fact(pdf_tools, text, parameter, target, reason):
    bundle, tools = pdf_tools([text])
    result = tools.execute({'tool': 'convert', 'fact': {'citation_id': 'S1', 'product': 'A',
                            'parameter': parameter, 'span_index': 0}, 'unit': target})
    assert result == {'status': 'unavailable', 'reason': reason}
    assert text in bundle['evidence'][0]['source']['text']


@pytest.mark.parametrize('text,parameter,target,expected,factor', [
    ('A length: 1250 mm', 'length', 'm', '1.25', '0.001'),
    ('A mass: 1,6 kg', 'mass', 'g', '1600', '1000'),
    ('A luminous flux: 1800 lm', 'luminous_flux', 'lm', '1800', '1'),
    ('A color temperature: 3000 K', 'color_temperature', 'K', '3000', '1'),
])
def test_whitelisted_units_keep_source_and_exact_conversion(pdf_tools, text, parameter, target, expected, factor):
    bundle, tools = pdf_tools([text])
    result = tools.execute({'tool': 'convert', 'fact': {'citation_id': 'S1', 'product': 'A',
                            'parameter': parameter, 'span_index': 0}, 'unit': target})
    assert result['converted']['value'] == expected
    assert result['converted']['factor'] == factor
    assert result['fact']['locator']['page_number'] == 1


def test_different_qualifiers_and_different_power_labels_are_not_equivalent(pdf_tools):
    for texts in [('A power: 20 W (at 25 C)', 'B power: 30 W (at 40 C)'),
                  ('A rated power: 20 W', 'B Systemleistung: 30 W')]:
        bundle, tools = pdf_tools(texts)
        refs = {e['source']['text'][0]: {'citation_id': e['citation_id'], 'product': e['source']['text'][0],
                'parameter': 'power', 'span_index': 0} for e in bundle['evidence']}
        result = tools.execute({'tool': 'compare', 'left': refs['A'], 'right': refs['B'], 'operator': 'lt'})
        assert result == {'status': 'unavailable', 'reason': 'incomparable_facts'}


def test_model_cannot_supply_numeric_values_or_unknown_units(pdf_tools):
    bundle, tools = pdf_tools(['A power: 20 W'])
    ref = {'citation_id': 'S1', 'product': 'A', 'parameter': 'power', 'span_index': 0}
    for request in [{'tool': 'convert', 'fact': {**ref, 'value': '999'}, 'unit': 'W'},
                    {'tool': 'convert', 'fact': ref, 'unit': 'horsepower'},
                    {'tool': 'convert', 'fact': {**ref, 'span_index': True}, 'unit': 'W'},
                    {'tool': 'exec', 'python': '1+1'}]:
        with pytest.raises(DocumentError) as error:
            tools.execute(request)
        assert error.value.code == 'invalid_numeric_tool'
    assert tools.execute({'tool': 'convert', 'fact': {**ref, 'citation_id': 'S999'}, 'unit': 'W'})['reason'] == 'unknown_citation'


def test_separate_qualifier_context_cannot_be_silently_ignored(pdf_tools):
    commands = ('BT /F2 10 Tf 10 180 Td (Only at 40 C) Tj ET\n'
                'BT /F1 8 Tf 10 155 Td (A power: 20 W) Tj ET')
    bundle, tools = pdf_tools([commands], commands=True)
    item = next(e for e in bundle['evidence'] if 'A power:' in e['source']['text'])
    assert item['source']['context']
    result = tools.execute({'tool': 'convert', 'fact': {'citation_id': item['citation_id'],
                            'product': 'A', 'parameter': 'power', 'span_index': 0}, 'unit': 'kW'})
    assert result['status'] == 'unavailable'
    assert 'Only at 40 C' in item['source']['retrieval_text']


def test_price_validity_and_cross_document_basis_are_preserved(service):
    first = row('001', '10,00')
    second = row('002', '20,00')
    first[4], second[4] = '2026-01-01', '2027-01-01'
    identity = publish(service, [first, second])
    duplicate = publish(service, [first])
    bundle = QuestionTools(service, None).prepare(
        {'conversation_id': 'a', 'question': '001 002', 'document_ids': [identity, duplicate]},
        planner=lambda *args: {'tools': [{'tool': 'lookup_orders', 'document_ids': [identity, duplicate],
                                          'order_ids': ['001', '002']}]})
    refs = {(e['source']['document_id'], e['source']['order_id']):
            {'citation_id': e['citation_id'], 'parameter': 'price'} for e in bundle['evidence']}
    tools = EvidenceTools(bundle)
    result = tools.execute({'tool': 'compare', 'left': refs[identity, '001'],
                            'right': refs[identity, '002'], 'operator': 'lt'})
    assert result['reason'] == 'incomparable_facts'
    result = tools.execute({'tool': 'compare', 'left': refs[identity, '001'],
                            'right': refs[duplicate, '001'], 'operator': 'eq'})
    assert result['reason'] == 'price_basis_unknown'
