import json
from types import SimpleNamespace

import pytest

from app.documents import DocumentError
from app.pdf_specialist import PdfSpecialist
from app.questions import QuestionBudget
from test_answers import Model, draft
from test_pdf_specialist import workspace
from app.agent_protocol import DocumentVersion, EvidenceDescriptor, ProductIdentifier, ScopeSnapshot, SourceScope
from test_csv_specialist import Model as CsvModel, Executor, plan, setup, success


def test_pdf_products_are_structured_and_bound_to_published_source_evidence(workspace):
    _, _, service, task, _ = workspace
    task = task.model_copy(update={'extract_product_identifiers': True})
    service.model = Model({**draft('S1'), 'product_identifiers': [
        {'value': 'A', 'evidence_ids': ['S1']}]})
    result = PdfSpecialist(service).execute(task, QuestionBudget())
    assert result['result']['product_identifiers'] == [
        {'value': 'A', 'evidence_ids': ['pdf:S1']}]
    assert len(service.model.calls) == 1


def dependent_task(task, value='001'):
    source = DocumentVersion(document_id='pdf', version_id='pdf-v1')
    scope = SourceScope(documents=(source,))
    return task.model_copy(update={
        'scope': task.scope.model_copy(update={'dependency_scopes': (scope,)}),
        'product_identifiers': (ProductIdentifier(value=value, evidence_ids=('pdf:S1',)),),
        'dependency_evidence': (EvidenceDescriptor(evidence_id='pdf:S1', source=source,
            location='page 1', scope=ScopeSnapshot(documents=(source,))),)})


def test_csv_dependency_filters_full_input_exactly_and_retains_pdf_provenance():
    model = CsvModel(plan(product_key_columns=[{'version_id': 'v1', 'column': 'id'}]))
    executor = Executor(success(rows=[['1.20']]))
    specialist, task = setup(model, executor)
    result = specialist.execute(dependent_task(task), QuestionBudget())
    assert result['result']['status'] == 'completed'
    supplied = json.loads(executor.calls[0][1]['datasets.json'])[0]
    assert [row['values'] for row in supplied['rows']] == [['001', '1.20']]
    artifact = result['result']['artifact_refs'][0]
    assert {ref['version_id'] for ref in artifact['scope']['documents']} == {'v1', 'pdf-v1'}
    receipt = json.loads(artifact['calculation'])
    assert receipt['product_mapping'][0]['matched_row_ids'] == ['r1']
    assert receipt['dependency_evidence'][0]['evidence_id'] == 'pdf:S1'
    assert len(model.calls) == 1


@pytest.mark.parametrize('value', ['1', 'missing'])
def test_csv_dependency_never_coerces_or_substitutes_identifiers(value):
    model = CsvModel(plan(product_key_columns=[{'version_id': 'v1', 'column': 'id'}]))
    executor = Executor()
    specialist, task = setup(model, executor)
    result = specialist.execute(dependent_task(task, value), QuestionBudget())
    assert result['result']['status'] == 'clarification'
    assert '0 exact matches' in result['result']['clarification']
    assert not executor.calls


@pytest.mark.parametrize('product', [
    {'value': 'invented', 'evidence_ids': ['S1']},
    {'value': 'A', 'evidence_ids': ['unread']},
    {'value': 1, 'evidence_ids': ['S1']},
    {'value': '2', 'evidence_ids': ['S1']},
])
def test_pdf_dependency_rejects_unverified_or_nonliteral_identifiers(workspace, product):
    _, _, service, task, _ = workspace
    task = task.model_copy(update={'extract_product_identifiers': True})
    service.model = Model({**draft('S1'), 'product_identifiers': [product]})
    with pytest.raises(DocumentError) as error:
        PdfSpecialist(service).execute(task, QuestionBudget())
    assert error.value.code == 'invalid_pdf_products'


@pytest.mark.parametrize('mode', ['coverage', 'topic'])
def test_full_reading_extracts_identifiers_without_an_extra_model_call(workspace, mode):
    from test_pdf_analysis import Model as ReadingModel

    class ProductModel(ReadingModel):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_synthesis':
                result['product_identifiers'] = [{'value': 'A',
                    'evidence_ids': payload['findings'][0]['evidence_ids']}]
            return result

    _, _, service, task, _ = workspace
    service.model = ProductModel()
    task = task.model_copy(update={'extract_product_identifiers': True, 'pdf_mode': mode})
    result = PdfSpecialist(service).execute(task, QuestionBudget())
    assert result['result']['product_identifiers'][0]['value'] == 'A'
    assert len(service.model.calls) == 3


def test_chart_followup_keeps_pdf_dependencies_without_remapping_raw_csv():
    chart = {'type': 'bar', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    model = CsvModel(plan(action='reuse_chart', reuse_artifact_id='old', chart=chart,
        operations=['chart'], aggregations=[], script=''))
    specialist, task = setup(model, Executor())
    task = dependent_task(task).model_copy(update={'product_identifiers': (), 'input_artifacts': ('old',)})
    saved_scope = task.scope.model_copy(update={'documents': (*task.scope.documents,
        task.dependency_evidence[0].source)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': saved_scope.model_dump(mode='json'),
        'source_available': True, 'invalidated': False, 'unit': 'EUR', 'calculation': '{}',
        'payload': {'columns': ['id', 'price'], 'rows': [['001', '1.20']], 'diagnostics': []}}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'completed'
    assert result['result']['artifact_refs'][0]['scope'] == saved_scope.model_dump(mode='json')
    assert not specialist.executor.calls


def test_csv_does_not_publish_if_pdf_dependency_disappears_during_execution():
    model = CsvModel(plan(product_key_columns=[{'version_id': 'v1', 'column': 'id'}]))
    executor = Executor(success())
    specialist, task = setup(model, executor)
    specialist.answers.tools.documents.lifecycle.available = lambda sid, refs: not (
        executor.calls and any(ref.version_id == 'pdf-v1' for ref in refs))
    with pytest.raises(DocumentError) as error:
        specialist.execute(dependent_task(task), QuestionBudget())
    assert error.value.code == 'source_unavailable'


@pytest.mark.parametrize('keys', [[], [{'version_id': 'v1', 'column': 'guessed'}]])
def test_csv_requires_an_explicit_available_product_key(keys):
    specialist, task = setup(CsvModel(plan(product_key_columns=keys)), Executor())
    result = specialist.execute(dependent_task(task), QuestionBudget())
    assert result['result']['status'] == 'clarification'
    assert not specialist.executor.calls


def test_csv_duplicate_product_rows_require_a_policy_instead_of_silent_deduplication():
    specialist, task = setup(CsvModel(plan(product_key_columns=[{'version_id': 'v1', 'column': 'id'}])), Executor())
    documents = specialist.answers.tools.documents
    tables = documents.csv_snapshot(task.session_id, task.scope.documents)
    tables[0]['rows'][1]['values'][0] = '001'
    documents.csv_snapshot = lambda *args: tables
    result = specialist.execute(dependent_task(task), QuestionBudget())
    assert result['result']['status'] == 'clarification'
    assert '2 exact matches' in result['result']['clarification']
    assert not specialist.executor.calls


def test_csv_retains_all_pdf_selection_sources_even_when_only_one_matched():
    specialist, task = setup(CsvModel(plan(product_key_columns=[{'version_id': 'v1', 'column': 'id'}])),
        Executor(success()))
    task = dependent_task(task)
    other = DocumentVersion(document_id='other', version_id='other-pdf')
    dependency = task.scope.dependency_scopes[0].model_copy(update={
        'documents': (*task.scope.dependency_scopes[0].documents, other)})
    task = task.model_copy(update={'scope': task.scope.model_copy(update={'dependency_scopes': (dependency,)})})
    result = specialist.execute(task, QuestionBudget())
    assert {ref['version_id'] for ref in result['result']['artifact_refs'][0]['scope']['documents']} == {
        'v1', 'pdf-v1', 'other-pdf'}


def test_valid_repaired_result_is_explicit_partial_when_review_budget_runs_out():
    from app.agent_protocol import ExecutionBudget
    from app.python_executor import ExecutionResult
    model = CsvModel(plan(group_by=['id']), {'decision': 'repair', 'reason': 'Fix import',
        'script': 'fixed()', 'clarification': None})
    executor = Executor(ExecutionResult('failed', None, {}, True, 'missing import'), success())
    specialist, task = setup(model, executor)
    task = task.model_copy(update={'budget': ExecutionBudget(max_steps=12, max_model_calls=2)})
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'partial'
    assert result['answer']['outcome'] == 'partial'
    assert result['artifacts'][0]['payload']['rows'] == [['3.50']]
    assert 'review' in result['answer']['gaps'][0].lower()
    assert len(model.calls) == 2


def test_clarified_duplicate_policy_preserves_all_original_matching_rows():
    specialist, task = setup(CsvModel(plan(product_key_columns=[{'version_id': 'v1', 'column': 'id'}],
        duplicate_product_policy='all_matches')), Executor(success()))
    documents = specialist.answers.tools.documents
    tables = documents.csv_snapshot(task.session_id, task.scope.documents)
    tables[0]['rows'][1]['values'][0] = '001'
    documents.csv_snapshot = lambda *args: tables
    task = dependent_task(task).model_copy(update={'constraints': ('Keep every row for duplicated product identifiers.',)})
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'completed'
    supplied = json.loads(specialist.executor.calls[0][1]['datasets.json'])[0]
    assert [row['values'] for row in supplied['rows']] == [['001', '1.20'], ['001', '2.30']]
    receipt = json.loads(result['artifacts'][0]['calculation'])
    assert receipt['product_mapping'][0]['matched_row_ids'] == ['r1', 'r2']
    assert receipt['plan']['duplicate_product_policy'] == 'all_matches'


def test_charting_unreviewed_partial_input_does_not_silently_certify_it():
    chart = {'type': 'bar', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    specialist, task = setup(CsvModel(plan(action='reuse_chart', reuse_artifact_id='old', chart=chart,
        operations=['chart'], aggregations=[], script='')), Executor())
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': task.scope.model_dump(mode='json'),
        'source_available': True, 'invalidated': False, 'unit': None,
        'calculation': json.dumps({'review_complete': False}),
        'payload': {'columns': ['id', 'price'], 'rows': [['001', '1.20']], 'diagnostics': []}}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'partial'
    assert 'input' in result['answer']['gaps'][0].lower()
    assert json.loads(result['artifacts'][0]['calculation'])['review_complete'] is False
