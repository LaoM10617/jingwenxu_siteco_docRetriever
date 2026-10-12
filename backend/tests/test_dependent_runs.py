from app.agent_protocol import (DocumentVersion, EvidenceDescriptor, ProductIdentifier,
                                ScopeSnapshot, TaskPackage, TaskResult, validate_result)
import pytest


def test_product_mapping_requires_known_evidence():
    source = DocumentVersion(document_id='manual', version_id='v1')
    scope = ScopeSnapshot(documents=(source,))
    task = TaskPackage(session_id='s', turn_id='t', run_id='r', task_id='pdf',
                       objective='identify products', specialist='pdf', scope=scope)
    result = TaskResult(session_id='s', turn_id='t', run_id='r', task_id='pdf', status='completed',
        product_identifiers=(ProductIdentifier(value='00123', evidence_ids=('missing',)),))
    with pytest.raises(ValueError, match='product.*evidence'):
        validate_result(task, result)

from test_conversation_runs import setup, ready_pdf, RecordingSpecialist


class Products(RecordingSpecialist):
    def execute(self, task, budget):
        output = super().execute(task, budget)
        output['result']['product_identifiers'] = [{'value': '00123',
            'evidence_ids': [output['result']['evidence_refs'][0]['evidence_id']]}]
        return output


class Prices(RecordingSpecialist):
    def execute(self, task, budget):
        assert [p.value for p in task.product_identifiers] == ['00123']
        assert task.dependency_evidence[0].source.document_id != task.scope.documents[0].document_id
        return super().execute(task, budget)


def test_dependent_task_passes_pdf_identifiers_and_independent_purposes(tmp_path):
    runs, sid, model, bindings = setup(tmp_path, [{'route': 'mixed', 'objective': 'Find lighting product prices',
        'dependency': 'pdf_to_csv', 'purpose': 'price', 'pdf_purpose': 'technical'}])
    pdf = ready_pdf(runs, bindings, sid, 'manual.pdf')
    csv = ready_pdf(runs, bindings, sid, 'prices.csv')
    runs.sessions.set_rules(sid, None, {'technical': (pdf,), 'price': (csv,)}, expected_rule_version=0)
    products, prices = Products(), Prices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    accepted = runs.submit(sid, 'dependent', 'Find lighting product prices', expected_data_version=2, expected_rule_version=1)
    done = runs.execute(accepted['run_id'])
    assert done['status'] == 'completed', done
    assert products.tasks[0].scope.purpose == 'technical'
    assert prices.tasks[0].scope.purpose == 'price'
    assert products.tasks[0].budget.max_model_calls == 3
    assert prices.tasks[0].budget.max_model_calls == 4
    assert runs.execute(accepted['run_id']) == done
    assert len(products.tasks) == len(prices.tasks) == 1


def test_downstream_clarification_reuses_successful_pdf_after_restart(tmp_path):
    from app.conversation_runs import ConversationRuns
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices for selected products'}
    runs, sid, model, bindings = setup(tmp_path, [intent, {**intent, 'keep_pdf_selection': True}])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    products = Products()
    class ClarifyingPrices(Prices):
        def execute(self, task, budget):
            output = super().execute(task, budget)
            if len(self.tasks) == 1:
                output['result']['status'] = 'clarification'
                output['result']['clarification'] = 'Which CSV product-code column?'
                output['answer']['outcome'] = 'needs_clarification'
            return output
    prices = ClarifyingPrices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    run = runs.submit(sid, 'dependent', 'Find prices', expected_data_version=2, expected_rule_version=0)
    assert runs.execute(run['run_id'])['status'] == 'waiting'
    reopened = ConversationRuns(runs.database, bindings, lambda _: products, csv_specialist_factory=lambda _: prices)
    assert len(products.tasks) == 1
    reopened.resume(sid, run['run_id'], 'Use article_number')
    done = reopened.execute(run['run_id'])
    assert done['status'] == 'completed', done
    assert len(products.tasks) == 1
    assert len(prices.tasks) == 2
    assert 'User clarification (data): Use article_number' in prices.tasks[-1].constraints


def test_clarification_grants_one_new_bounded_round_and_duplicate_reply_is_idempotent(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices'}
    runs, sid, model, bindings = setup(tmp_path, [intent, *[{} for _ in range(5)], {**intent, 'keep_pdf_selection': True}])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    products = Products()
    tasks = []
    class BudgetPrices(Prices):
        def __init__(self, service):
            super().__init__()
            self.service = service
        def execute(self, task, budget):
            tasks.append(task)
            output = super().execute(task, budget)
            if len(tasks) == 1:
                for index in range(5):
                    self.service.model.generate('test', {'phase': 'test', 'index': index}, {}, budget)
                output['result'].update(status='clarification', clarification='Which key?')
                output['answer']['outcome'] = 'needs_clarification'
            return output
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = BudgetPrices
    run = runs.submit(sid, 'dependent', 'Prices', expected_data_version=2, expected_rule_version=0)
    assert runs.execute(run['run_id'])['status'] == 'waiting'
    runs.resume(sid, run['run_id'], 'article_number')
    runs.resume(sid, run['run_id'], 'article_number')
    assert runs.execute(run['run_id'])['status'] == 'completed'
    events = runs.events(sid, run['run_id'], developer=True)
    assert len([event for event in events if event['kind'] == 'clarification_round']) == 1


def test_failed_downstream_exposes_partial_pdf_and_resumes_without_repeating_it(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices'}
    runs, sid, model, bindings = setup(tmp_path, [intent])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    products = Products()
    class FailingPrices(Prices):
        def execute(self, task, budget):
            output = super().execute(task, budget)
            if len(self.tasks) == 1:
                output['result']['status'] = 'failed'
            return output
    prices = FailingPrices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    run = runs.submit(sid, 'dependent', 'Prices', expected_data_version=2, expected_rule_version=0)
    failed = runs.execute(run['run_id'])
    assert failed['status'] == 'failed'
    assert failed['answer'] is None
    assert failed['partial_answer']['outcome'] == 'partial'
    assert failed['partial_answer']['segments'][0]['text'] == 'Fresh fact'
    runs.resume(sid, run['run_id'])
    assert runs.execute(run['run_id'])['status'] == 'completed'
    assert len(products.tasks) == 1


def test_explicit_old_pdf_selection_can_drive_new_price_source(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices', 'purpose': 'price', 'pdf_purpose': 'technical'}
    runs, sid, model, bindings = setup(tmp_path, [intent])
    pdf = ready_pdf(runs, bindings, sid, 'manual.pdf')
    csv = ready_pdf(runs, bindings, sid, 'prices.csv')
    new_csv = ready_pdf(runs, bindings, sid, 'new_prices.csv')
    runs.sessions.set_rules(sid, None, {'technical': (pdf,), 'price': (csv,)}, expected_rule_version=0)
    products, prices = Products(), Prices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    first = runs.submit(sid, 'first', 'Find products and prices', expected_data_version=3, expected_rule_version=1)
    assert runs.execute(first['run_id'])['status'] == 'completed'
    runs.sessions.set_rules(sid, None, {'technical': (pdf,), 'price': (new_csv,)}, expected_rule_version=1)
    model.outputs.append({**intent, 'reuse_pdf_from': first['run_id'] + ':answer'})
    second = runs.submit(sid, 'second', 'Keep selected products; use new prices', expected_data_version=3, expected_rule_version=2)
    assert runs.execute(second['run_id'])['status'] == 'completed'
    assert len(products.tasks) == 1
    assert prices.tasks[-1].scope.documents == (new_csv,)


def test_stop_after_pdf_persistence_reuses_it_on_explicit_resume(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices'}
    runs, sid, model, bindings = setup(tmp_path, [intent])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    products = Products()
    class StoppingPrices(Prices):
        def execute(self, task, budget):
            output = super().execute(task, budget)
            if len(self.tasks) == 1:
                runs.stop(sid, task.run_id)
                budget.check()
            return output
    prices = StoppingPrices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    run = runs.submit(sid, 'dependent', 'Prices', expected_data_version=2, expected_rule_version=0)
    stopped = runs.execute(run['run_id'])
    assert stopped['status'] == 'stopped'
    assert stopped['partial_answer']['segments'][0]['text'] == 'Fresh fact'
    runs.resume(sid, run['run_id'])
    assert runs.execute(run['run_id'])['status'] == 'completed'
    assert len(products.tasks) == 1
    assert prices.tasks[0].task_id == prices.tasks[1].task_id


def test_changed_pdf_purpose_rejects_explicit_old_selection(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices', 'pdf_purpose': 'technical'}
    runs, sid, model, bindings = setup(tmp_path, [intent])
    pdf = ready_pdf(runs, bindings, sid, 'manual.pdf')
    newer = ready_pdf(runs, bindings, sid, 'new_manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    runs.sessions.set_rules(sid, None, {'technical': (pdf,)}, expected_rule_version=0)
    products, prices = Products(), Prices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    first = runs.submit(sid, 'first', 'Find products and prices', expected_data_version=3, expected_rule_version=1)
    assert runs.execute(first['run_id'])['status'] == 'completed'
    assert len(runs.pdf_results(sid)) == 1
    runs.sessions.set_rules(sid, None, {'technical': (newer,)}, expected_rule_version=1)
    assert runs.pdf_results(sid) == []
    model.outputs.append({**intent, 'reuse_pdf_from': first['run_id'] + ':answer'})
    second = runs.submit(sid, 'second', 'Reuse selection', expected_data_version=3, expected_rule_version=2)
    rejected = runs.execute(second['run_id'])
    assert rejected['status'] == 'failed'
    assert rejected['error']['code'] == 'pdf_result_scope_changed'
    assert len(prices.tasks) == 1


def test_followup_table_keeps_pdf_selection_dependencies_without_repeating_mapping(tmp_path):
    import json
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices', 'purpose': 'price', 'pdf_purpose': 'technical'}
    runs, sid, model, bindings = setup(tmp_path, [intent])
    pdf = ready_pdf(runs, bindings, sid, 'manual.pdf')
    csv = ready_pdf(runs, bindings, sid, 'prices.csv')
    runs.sessions.set_rules(sid, None, {'technical': (pdf,), 'price': (csv,)}, expected_rule_version=0)
    products = Products()
    class TablePrices(RecordingSpecialist):
        def execute(self, task, budget):
            output = super().execute(task, budget)
            if not task.input_artifacts:
                scope = task.scope.model_copy(update={'documents': (csv, pdf)})
                identity = task.task_id + ':table'
                output['result']['artifact_refs'] = [{'artifact_id': identity, 'version_id': '1',
                    'kind': 'table', 'scope': scope.model_dump(mode='json'), 'storage_ref': identity}]
                output['artifacts'] = [{'artifact_id': identity, 'kind': 'table',
                    'payload': {'columns': ['code'], 'rows': [['00123']]},
                    'calculation': json.dumps({'dependency_evidence': [e.model_dump(mode='json') for e in task.dependency_evidence]})}]
            else:
                assert task.product_identifiers == ()
                assert task.scope.documents == (csv,)
                assert task.scope.dependency_scopes[0].documents == (pdf,)
                assert task.dependency_evidence[0].source == pdf
            return output
    prices = TablePrices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    first = runs.submit(sid, 'first', 'Find products and prices', expected_data_version=2, expected_rule_version=1)
    assert runs.execute(first['run_id'])['status'] == 'completed'
    artifact_id = first['run_id'] + ':csv:0:table'
    model.outputs.append({'route': 'csv', 'objective': 'Plot previous prices', 'purpose': 'price',
        'references': [{'kind': 'artifact', 'reference_id': artifact_id, 'description': 'previous prices'}]})
    second = runs.submit(sid, 'second', 'Plot previous prices', expected_data_version=2, expected_rule_version=1)
    done = runs.execute(second['run_id'])
    assert done['status'] == 'completed', done
    assert len(products.tasks) == 1
    assert len(prices.tasks) == 2


def test_missing_pdf_identifiers_waits_without_guessing_csv_keys(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Find matching prices'}
    runs, sid, model, bindings = setup(tmp_path, [intent])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    products, prices = RecordingSpecialist(), RecordingSpecialist()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    run = runs.submit(sid, 'dependent', 'Find matching prices', expected_data_version=2, expected_rule_version=0)
    waiting = runs.execute(run['run_id'])
    assert waiting['status'] == 'waiting'
    assert 'exact product codes' in waiting['clarification']
    assert prices.tasks == []
    assert waiting['partial_answer']['segments'][0]['text'] == 'Fresh fact'



def test_changed_product_condition_in_clarification_reselects_pdf_products(tmp_path):
    first_intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Select 10 W products and prices'}
    second_intent = {**first_intent, 'objective': 'Select 20 W products instead and prices'}
    runs, sid, model, bindings = setup(tmp_path, [first_intent, second_intent])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    class ChangingProducts(Products):
        def execute(self, task, budget):
            output = super().execute(task, budget)
            if len(self.tasks) == 2:
                output['result']['product_identifiers'][0]['value'] = '00999'
            return output
    class ClarifyingPrices(RecordingSpecialist):
        def execute(self, task, budget):
            output = super().execute(task, budget)
            if len(self.tasks) == 1:
                output['result'].update(status='clarification', clarification='Which product-code column?')
                output['answer']['outcome'] = 'needs_clarification'
            return output
    products, prices = ChangingProducts(), ClarifyingPrices()
    runs.specialist_factory = lambda _: products
    runs.csv_specialist_factory = lambda _: prices
    run = runs.submit(sid, 'changed', 'Select 10 W products and prices', expected_data_version=2, expected_rule_version=0)
    assert runs.execute(run['run_id'])['status'] == 'waiting'
    runs.resume(sid, run['run_id'], 'Use code, but select 20 W products instead')
    assert runs.execute(run['run_id'])['status'] == 'completed'
    assert len(products.tasks) == 2
    assert prices.tasks[-1].product_identifiers[0].value == '00999'



def test_larger_csv_allowance_never_exceeds_six_model_calls_for_the_round(tmp_path):
    intent = {'route': 'mixed', 'dependency': 'pdf_to_csv', 'objective': 'Prices'}
    runs, sid, model, bindings = setup(tmp_path, [intent, *[{} for _ in range(8)]])
    ready_pdf(runs, bindings, sid, 'manual.pdf')
    ready_pdf(runs, bindings, sid, 'prices.csv')
    class ReadingProducts(Products):
        def __init__(self, service):
            super().__init__()
            self.service = service
        def execute(self, task, budget):
            for index in range(3):
                self.service.model.generate('test', {'phase': 'pdf_read', 'index': index}, {}, budget)
            return super().execute(task, budget)
    class ReviewingPrices(Prices):
        def __init__(self, service):
            super().__init__()
            self.service = service
        def execute(self, task, budget):
            for index in range(task.budget.max_model_calls):
                self.service.model.generate('test', {'phase': 'csv_review', 'index': index}, {}, budget)
            return super().execute(task, budget)
    runs.specialist_factory = ReadingProducts
    runs.csv_specialist_factory = ReviewingPrices
    run = runs.submit(sid, 'budget', 'Prices', expected_data_version=2, expected_rule_version=0)
    done = runs.execute(run['run_id'])
    assert done['status'] == 'failed'
    assert done['error']['code'] == 'run_budget_exhausted'
    assert len(model.calls) == 6
    assert done['partial_answer']['segments'][0]['text'] == 'Fresh fact'
