from types import SimpleNamespace
import json
import pytest
from app.agent_protocol import DocumentVersion, ScopeSnapshot, TaskPackage, ExecutionBudget
from app.questions import QuestionBudget
from app.python_executor import ExecutionResult
from app.csv_specialist import CsvSpecialist


class Model:
    provider = 'test'
    model = 'fake'
    def __init__(self, *values):
        self.values, self.calls = list(values), []
    def generate(self, system, payload, schema, budget):
        self.calls.append(payload)
        return self.values.pop(0)


class Documents:
    def __init__(self):
        self.lifecycle = SimpleNamespace(available=lambda *args: True)
    def csv_snapshot(self, sid, refs):
        return [{'source': ref.model_dump(), 'content_hash': 'hash', 'parser_version': 'v1', 'original_filename': 'data.csv',
                 'headers': ['id', 'price'], 'rows': [
                     {'row_id': 'r1', 'record_number': 1, 'values': ['001', '1.20']},
                     {'row_id': 'r2', 'record_number': 2, 'values': ['002', '2.30']}]} for ref in refs]
    def get(self, vid):
        return {'original_filename': 'data.csv', 'parse_result': {'profile': {}}}


class Executor:
    def __init__(self, *values):
        self.values, self.calls = list(values), []
    def execute(self, task, script, inputs, budget):
        self.calls.append((script, inputs))
        return self.values.pop(0)


def plan(**changes):
    return {'action': 'compute', 'clarification': None, 'operations': ['aggregate'],
        'filters': [], 'group_by': [], 'aggregations': ['sum price'], 'joins': [],
        'null_policy': 'reject blanks', 'numeric_formats': ['price: decimal dot'],
        'unit': None, 'assumptions': [], 'script': 'print("result")',
        'reuse_artifact_id': None, 'chart': None, **changes}


def setup(model, executor):
    documents = Documents()
    task = TaskPackage(session_id='sid', turn_id='turn', run_id='run', task_id='csv',
        objective='Sum price', specialist='csv', scope=ScopeSnapshot(documents=(
            DocumentVersion(document_id='doc', version_id='v1'),)),
        budget=ExecutionBudget(max_steps=12, max_model_calls=4))
    return CsvSpecialist(SimpleNamespace(tools=SimpleNamespace(documents=documents), model=model), executor), task


def output(**changes):
    return {'columns': ['total'], 'rows': [['3.50']], 'chart': None, 'diagnostics': [], **changes}


def success(**changes):
    return ExecutionResult('completed', output(**changes), {}, True)


def test_full_population_is_executed_and_numbers_are_not_rewritten_by_model():
    model, executor = Model(plan()), Executor(success())
    specialist, task = setup(model, executor)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'completed'
    assert '3.50' in result['answer']['segments'][0]['text']
    assert len(model.calls) == 1
    assert json.loads(executor.calls[0][1]['datasets.json'])[0]['rows'][0]['values'][0] == '001'
    assert result['artifacts'][0]['payload']['rows'] == [['3.50']]
    assert result['result']['coverage'][0]['semantic_sufficiency'] == 'unknown'


def test_business_ambiguity_returns_clarification_without_execution():
    model, executor = Model(plan(action='clarify', clarification='Which currency?', script='')), Executor()
    specialist, task = setup(model, executor)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'clarification'
    assert result['result']['clarification'] == 'Which currency?'
    assert not executor.calls


def test_script_failure_gets_one_repair_and_result_is_preserved():
    model = Model(plan(), {'decision': 'repair', 'reason': 'fix typo', 'script': 'fixed()', 'clarification': None})
    executor = Executor(ExecutionResult('failed', None, {}, True, 'NameError'), success())
    specialist, task = setup(model, executor)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'completed'
    assert len(executor.calls) == 2
    assert executor.calls[1][0] == 'fixed()'


def test_invalid_output_cannot_be_approved_by_model():
    model = Model(plan(), {'decision': 'accept', 'reason': 'looks fine', 'script': '', 'clarification': None})
    specialist, task = setup(model, Executor(success(rows=[[float('nan')]])))
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'failed'
    assert not result['artifacts']


def test_complex_analysis_is_reviewed_and_ambiguity_is_not_silently_fixed():
    model = Model(plan(group_by=['id']), {'decision': 'clarify', 'reason': 'unit mismatch',
        'script': '', 'clarification': 'Which unit?'})
    specialist, task = setup(model, Executor(success()))
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'clarification'
    assert not result['artifacts']


def test_chart_and_complete_table_are_separate_traceable_artifacts():
    chart = {'type': 'bar', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    model = Model(plan(operations=['chart'], chart=chart))
    specialist, task = setup(model, Executor(success(columns=['id', 'price'], rows=[['001', '1.20']], chart=chart)))
    result = specialist.execute(task, QuestionBudget())
    table, chart_result = result['artifacts']
    assert table['kind'] == 'table'
    assert table['payload']['rows'] == [['001', '1.20']]
    assert chart_result['payload']['table_artifact_id'] == table['artifact_id']



def test_two_failures_stop_without_publishing_or_third_execution():
    model = Model(plan(), {'decision': 'repair', 'reason': 'fix', 'script': 'retry()', 'clarification': None})
    executor = Executor(ExecutionResult('failed', None, {}, True, 'error'), ExecutionResult('failed', None, {}, True, 'error'))
    specialist, task = setup(model, executor)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'failed'
    assert not result['artifacts']
    assert len(executor.calls) == 2


@pytest.mark.parametrize('status', ['cancelled', 'timed_out', 'interrupted'])
def test_infrastructure_interruption_is_not_script_repair(status):
    from app.documents import DocumentError
    model = Model(plan())
    specialist, task = setup(model, Executor(ExecutionResult(status, None, {}, True)))
    with pytest.raises(DocumentError, match='CSV execution stopped'):
        specialist.execute(task, QuestionBudget())
    assert len(model.calls) == 1


def test_source_removed_after_execution_cannot_be_published():
    from app.documents import DocumentError
    specialist, task = setup(Model(plan()), None)
    class RemovingExecutor(Executor):
        def execute(self, *args):
            specialist.answers.tools.documents.lifecycle.available = lambda *args: False
            return success()
    specialist.executor = RemovingExecutor()
    with pytest.raises(DocumentError) as error:
        specialist.execute(task, QuestionBudget())
    assert error.value.code == 'source_unavailable'


def test_chart_reuse_preserves_complete_data_unit_and_previous_calculation():
    chart = {'type': 'line', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    specialist, task = setup(Model(plan(action='reuse_chart', reuse_artifact_id='old', chart=chart, unit='wrong', operations=['chart'], aggregations=[], script='')), Executor())
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': task.scope.model_dump(mode='json'),
        'source_available': True, 'invalidated': False, 'unit': 'EUR', 'calculation': 'old exact sum',
        'payload': {'columns': ['id', 'price'], 'rows': [['001', '1.20']], 'diagnostics': []}}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    result = specialist.execute(task, QuestionBudget())
    assert not specialist.executor.calls
    assert result['artifacts'][0]['unit'] == 'EUR'
    assert result['artifacts'][0]['payload']['rows'] == [['001', '1.20']]
    calculation = json.loads(result['artifacts'][0]['calculation'])
    assert calculation['previous_calculation_sha256']
    assert calculation['reused_payload_sha256']


def test_changed_scope_cannot_reuse_old_chart_data():
    from app.documents import DocumentError
    chart = {'type': 'line', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    specialist, task = setup(Model(plan(action='reuse_chart', reuse_artifact_id='old', chart=chart, operations=['chart'], aggregations=[], script='')), Executor())
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': {**task.scope.model_dump(mode='json'), 'filters': ['price > 10']},
        'source_available': True, 'invalidated': False}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    with pytest.raises(DocumentError) as error:
        specialist.execute(task, QuestionBudget())
    assert error.value.code == 'artifact_not_reusable'


def test_result_preview_does_not_truncate_persisted_table():
    rows = [[str(i)] for i in range(45)]
    specialist, task = setup(Model(plan()), Executor(success(rows=rows)))
    result = specialist.execute(task, QuestionBudget())
    assert len(result['artifacts'][0]['payload']['rows']) == 45
    assert '30 of 45' in result['answer']['segments'][0]['text']


def test_complex_repair_result_requires_second_review():
    model = Model(plan(group_by=['id']),
        {'decision': 'repair', 'reason': 'fix grouping', 'script': 'fixed()', 'clarification': None},
        {'decision': 'accept', 'reason': 'consistent', 'script': '', 'clarification': None})
    specialist, task = setup(model, Executor(success(), success()))
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'completed'
    assert [c['phase'] for c in model.calls] == ['csv_plan', 'csv_review', 'csv_review']


@pytest.mark.parametrize('changes', [
    {'columns': ['same', 'same'], 'rows': []}, {'rows': [[{'value': 1}]]},
    {'rows': [['a', 'b']]}, {'rows': [[float('inf')]]},
    {'chart': {'type': 'bar', 'x': 'missing', 'y': 'total', 'title': 'x'}},
])
def test_invalid_table_shapes_are_rejected(changes):
    from app.csv_specialist import validate_table
    with pytest.raises(ValueError):
        validate_table(output(**changes))


def test_reuse_plan_cannot_hide_a_new_filter():
    from app.documents import DocumentError
    chart = {'type': 'bar', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    specialist, task = setup(Model(plan(action='reuse_chart', reuse_artifact_id='old', chart=chart,
        operations=['chart'], filters=['price > 10'], script='')), Executor())
    with pytest.raises(DocumentError) as error:
        specialist.execute(task, QuestionBudget())
    assert error.value.code == 'invalid_csv_plan'



def test_rejected_chart_reuse_is_not_published_or_silently_accepted():
    chart = {'type': 'bar', 'x': 'id', 'y': 'price', 'title': 'Prices'}
    model = Model(plan(action='reuse_chart', reuse_artifact_id='old', chart=chart,
        operations=['chart'], aggregations=[], script=''),
        {'decision': 'repair', 'reason': 'Data needs recalculation', 'script': 'repair()', 'clarification': None})
    specialist, task = setup(model, Executor())
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': task.scope.model_dump(mode='json'),
        'source_available': True, 'invalidated': False, 'unit': 'EUR', 'calculation': 'old',
        'payload': {'columns': ['id', 'price'], 'rows': [['001', '1.20']], 'diagnostics': [{'warning': 'review'}]}}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    result = specialist.execute(task, QuestionBudget())
    assert result['result']['status'] == 'failed'
    assert not result['artifacts']
    assert not specialist.executor.calls


def test_followup_computation_receives_complete_previous_table_and_records_its_identity():
    specialist, task = setup(Model(plan(operations=['filter'], filters=['price > 10'])), Executor(success()))
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'version_id': '1', 'kind': 'table',
        'scope': task.scope.model_dump(mode='json'), 'source_available': True, 'invalidated': False,
        'unit': 'EUR', 'calculation': 'grouped totals', 'payload': {'columns': ['id', 'price'],
        'rows': [['001', '12.00'], ['002', '9.00']], 'diagnostics': []}}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    result = specialist.execute(task, QuestionBudget())
    inputs = specialist.executor.calls[0][1]
    assert json.loads(inputs['artifacts.json'])[0]['payload']['rows'] == [['001', '12.00'], ['002', '9.00']]
    calculation = json.loads(result['artifacts'][0]['calculation'])
    assert calculation['input_artifacts'][0]['artifact_id'] == 'old'
    assert calculation['input_artifacts'][0]['payload_sha256']
    assert specialist.answers.model.calls[0]['overview'][0]['original_filename'] == 'data.csv'



def test_prior_script_and_nested_history_do_not_expand_model_context_or_new_provenance():
    specialist, task = setup(Model(plan()), Executor(success()))
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': task.scope.model_dump(mode='json'),
        'source_available': True, 'invalidated': False, 'unit': 'EUR',
        'calculation': json.dumps({'plan': {**plan(), 'script': 'secret_old_script' * 10000}, 'previous_history': 'x' * 500000}),
        'payload': {'columns': ['total'], 'rows': [['3.50']], 'diagnostics': []}}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    result = specialist.execute(task, QuestionBudget())
    model_input = json.dumps(specialist.answers.model.calls[0])
    assert 'secret_old_script' not in model_input
    assert len(model_input) < 10000
    assert len(result['artifacts'][0]['calculation']) < 10000


@pytest.mark.parametrize('changed', [
    {'source_available': False}, {'invalidated': True},
    {'scope': {'documents': [{'document_id': 'doc', 'version_id': 'v1'}], 'purpose': None, 'filters': ['old filter']}},
    {'kind': 'chart'},
])
def test_compute_rejects_explicit_unusable_artifact_before_planning(changed):
    from app.documents import DocumentError
    model = Model(plan(operations=['filter'], filters=['price > 10']))
    specialist, task = setup(model, Executor(success()))
    task = task.model_copy(update={'input_artifacts': ('old',)})
    previous = {'artifact_id': 'old', 'kind': 'table', 'scope': task.scope.model_dump(mode='json'),
        'source_available': True, 'invalidated': False, 'unit': 'EUR', 'calculation': 'old',
        'payload': {'columns': ['price'], 'rows': [['12.00']], 'diagnostics': []}, **changed}
    specialist.artifacts = SimpleNamespace(get=lambda *args: previous)
    with pytest.raises(DocumentError) as error:
        specialist.execute(task, QuestionBudget())
    assert error.value.code == 'artifact_not_reusable'
    assert model.calls == []
    assert specialist.executor.calls == []
