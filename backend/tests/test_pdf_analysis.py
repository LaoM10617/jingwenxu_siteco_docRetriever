from types import SimpleNamespace
import pytest
from app.agent_protocol import DocumentVersion, ScopeSnapshot, TaskPackage, ExecutionBudget
from app.pdf_specialist import PdfSpecialist
from app.questions import QuestionBudget
from app.documents import DocumentError
from test_pdf_specialist import workspace


class Documents:
    def __init__(self, counts=(4, 1)):
        self.lifecycle = SimpleNamespace(available=lambda *args: True)
        self.snapshots = []
        for index, count in enumerate(counts):
            vid = str(index)
            self.snapshots.append({'source': {'document_id': vid, 'version_id': vid},
                'original_filename': vid + '.pdf', 'content_hash': vid, 'reading_version': 'v1',
                'warnings': [], 'pages': [{'page_number': n + 1, 'status': 'extracted',
                    'units': [{'evidence_id': f'{vid}:{n}', 'text': vid * 6000,
                        'locator': {'kind': 'pdf', 'page_number': n + 1, 'bbox': [0., 0., 100., 100.]},
                        'source_spans': [], 'context': [], 'section': None}]} for n in range(count)]})
    def get(self, vid):
        return {'original_filename': vid + '.pdf'}
    def pdf_reading_snapshot(self, sid, refs, budget=None):
        return self.snapshots
    def read_evidence_id(self, vid, eid):
        return {'document_id': vid, **next(u for s in self.snapshots if s['source']['version_id'] == vid
            for p in s['pages'] for u in p['units'] if u['evidence_id'] == eid)}


class Model:
    provider = 'test'
    model = 'fake'
    def __init__(self):
        self.calls = []
    def generate(self, system, payload, schema, budget):
        self.calls.append(payload)
        if payload['phase'] == 'pdf_plan':
            return {'dimensions': ['properties'], 'page_ranges': [], 'comparison_requested': False}
        if payload['phase'] == 'pdf_read':
            return {'findings': [{'text': 'Source property.', 'evidence_ids': [payload['units'][0]['evidence_id']]}],
                'gaps': [], 'semantic_sufficiency': 'sufficient'}
        return {'findings': payload['findings'], 'comparisons': [], 'gaps': [], 'semantic_sufficiency': 'sufficient',
            'documents': [{'version_id': c['source']['version_id'], 'semantic_sufficiency':
                c['semantic_sufficiency']} for c in payload['coverage']
                if c['source']['version_id'] in payload['target_version_ids']]}


def execute(documents, model, calls=5):
    task = TaskPackage(session_id='sid', turn_id='turn', run_id='run', task_id='pdf',
        specialist='pdf', pdf_mode='coverage', objective='Summarize all documents',
        scope=ScopeSnapshot(documents=tuple(DocumentVersion(**s['source']) for s in documents.snapshots)),
        budget=ExecutionBudget(max_model_calls=calls, max_steps=10))
    service = SimpleNamespace(tools=SimpleNamespace(documents=documents), model=model)
    return PdfSpecialist(service).execute(task, QuestionBudget())


def test_coverage_reads_files_fairly_and_reports_budget_omissions():
    model = Model()
    output = execute(Documents((10, 1)), model)
    reads = [p for p in model.calls if p['phase'] == 'pdf_read']
    assert [p['version_id'] for p in reads] == ['0', '1', '0']
    assert len(model.calls) == 5
    assert output['result']['status'] == 'partial'
    assert output['result']['coverage'][0]['omitted']
    assert output['result']['coverage'][1]['omitted'] == []
    assert output['answer']['gaps']


def test_many_sources_report_omissions_within_the_same_call_budget():
    model = Model()
    output = execute(Documents((1,) * 11), model)
    assert len(model.calls) == 5
    assert output['result']['status'] == 'partial'
    assert len(output['result']['coverage']) == 11
    assert sum(bool(c['omitted']) for c in output['result']['coverage']) == 8


@pytest.mark.parametrize('phase', ['pdf_read', 'pdf_synthesis'])
def test_unread_or_cross_batch_citations_are_rejected(phase):
    class InvalidModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == phase:
                result['findings'][0]['evidence_ids'] = ['unread']
            return result
    with pytest.raises(DocumentError) as error:
        execute(Documents((1,)), InvalidModel())
    assert error.value.code == 'invalid_pdf_citations'


def test_mechanical_coverage_does_not_assert_semantic_sufficiency():
    class UncertainModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_read':
                result['semantic_sufficiency'] = 'unknown'
            return result
    output = execute(Documents((1,)), UncertainModel())
    coverage = output['result']['coverage'][0]
    assert len(coverage['processed']) == 1
    assert not coverage['omitted']
    assert coverage['semantic_sufficiency'] == 'unknown'
    assert output['result']['status'] == 'partial'
    assert output['answer']['gaps']


def test_empty_synthesis_cannot_publish_a_completed_analysis():
    class EmptyModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_synthesis':
                result['findings'] = []
            return result
    output = execute(Documents((1,)), EmptyModel())
    assert output['result']['status'] == 'partial'
    assert output['answer']['gaps']


def test_unreadable_page_and_unselected_pages_remain_omissions():
    documents = Documents((3,))
    documents.snapshots[0]['pages'][1].update(status='no_text', units=[])
    class RangeModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_plan':
                result['page_ranges'] = [{'version_id': '0', 'first': 1, 'last': 2}]
            return result
    output = execute(documents, RangeModel())
    assert output['result']['coverage'][0]['omitted'] == [
        'page:2:no_text', 'page:3:outside_planned_range']
    assert output['result']['status'] == 'partial'


def test_three_call_budget_keeps_synthesis_and_marks_other_file_unread():
    model = Model()
    output = execute(Documents((1, 1)), model, calls=3)
    assert [p['phase'] for p in model.calls] == ['pdf_plan', 'pdf_read', 'pdf_synthesis']
    assert output['result']['coverage'][1]['processed'] == []
    assert output['result']['coverage'][1]['omitted']


def test_cached_batches_are_reused_when_only_synthesis_budget_remains():
    class CachedModel(Model):
        def remaining_calls(self):
            return 1
        def has_receipt(self, system, payload, schema):
            return payload['phase'] != 'pdf_synthesis'
    model = CachedModel()
    output = execute(Documents((1, 1)), model)
    assert len([p for p in model.calls if p['phase'] == 'pdf_read']) == 2
    assert output['result']['status'] == 'completed'


def test_identical_evidence_ids_in_different_files_keep_ownership():
    documents = Documents((1, 1))
    for snapshot in documents.snapshots:
        snapshot['pages'][0]['units'][0]['evidence_id'] = 'same'
    output = execute(documents, Model())
    assert {c['document_id'] for c in output['answer']['citations']} == {'0', '1'}
    assert len({c['citation_id'] for c in output['answer']['citations']}) == 2


def test_real_parsed_reading_units_publish_source_citations(workspace):
    documents, sessions, service, task, refs = workspace
    service.model = Model()
    task = task.model_copy(update={'pdf_mode': 'coverage',
        'scope': ScopeSnapshot(documents=tuple(refs)), 'budget': ExecutionBudget(max_model_calls=5)})
    output = PdfSpecialist(service).execute(task, QuestionBudget())
    assert output['result']['status'] == 'completed'
    assert {c['document_id'] for c in output['answer']['citations']} == {r.version_id for r in refs}
    for citation in output['answer']['citations']:
        current = documents.read_evidence_id(citation['document_id'], citation['evidence_id'])
        assert current['text'] == citation['text']
        assert citation['locator']['page_number'] == 1


def test_fact_path_retrieves_each_document_separately(workspace):
    documents, sessions, service, task, refs = workspace
    original = service.tools.retriever
    class TrackingRetriever:
        calls = []
        def retrieve(self, question, ids, **kwargs):
            self.calls.append(ids)
            return original.retrieve(question, ids, **kwargs)
    service.tools.retriever = TrackingRetriever()
    task = task.model_copy(update={'scope': ScopeSnapshot(documents=tuple(refs))})
    PdfSpecialist(service).execute(task, QuestionBudget())
    assert service.tools.retriever.calls == [[r.version_id] for r in refs]
    context = service.model.calls[0]['bundle']
    assert {e['source']['document_id'] for e in context['evidence']} == {r.version_id for r in refs}


def test_constraints_and_filters_reach_every_reading_phase(workspace):
    documents, sessions, service, task, refs = workspace
    service.model = Model()
    from app.agent_protocol import ResolvedReference
    task = task.model_copy(update={'pdf_mode': 'topic', 'constraints': ('Keep product ownership',),
        'resolved_references': (ResolvedReference(kind='product', reference_id='P1', description='Product A'),),
        'scope': ScopeSnapshot(documents=(refs[0],), filters=('Only installation requirements',))})
    PdfSpecialist(service).execute(task, QuestionBudget())
    assert {p['phase'] for p in service.model.calls} == {'pdf_plan', 'pdf_read', 'pdf_synthesis'}
    assert all(p['constraints'] == ['Keep product ownership'] and
        p['filters'] == ['Only installation requirements'] for p in service.model.calls)
    assert all(p['resolved_references'][0]['reference_id'] == 'P1' for p in service.model.calls)


def test_factual_receipt_lookup_and_generation_use_same_task_payload(workspace):
    documents, sessions, service, task, refs = workspace
    from test_answers import draft
    class ReceiptModel:
        provider, model = 'test', 'test'
        lookups, generated = [], []
        def has_receipt(self, system, payload, schema):
            self.lookups.append(payload)
            return True
        def remaining_calls(self):
            return 0
        def generate(self, system, payload, schema, budget):
            self.generated.append(payload)
            return draft('S1')
    service.model = ReceiptModel()
    task = task.model_copy(update={'budget': ExecutionBudget(max_model_calls=0)})
    output = PdfSpecialist(service).execute(task, QuestionBudget())
    assert output['result']['status'] == 'completed'
    assert service.model.lookups == service.model.generated
    assert service.model.generated[0]['task_id'] == task.task_id
    assert service.model.generated[0]['phase'] == 'pdf_facts_answer'


def test_synthesis_resolves_batch_local_gaps_without_erasing_mechanical_omissions():
    class ReconciledModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_read':
                result.update(gaps=['The other document is absent from this batch.'], semantic_sufficiency='limited')
            if payload['phase'] == 'pdf_synthesis':
                assert len(payload['batch_gaps']) >= 2
                result['documents'] = [{'version_id': c['source']['version_id'],
                    'semantic_sufficiency': 'sufficient'} for c in payload['coverage']]
            return result
    complete = execute(Documents((1, 1)), ReconciledModel())
    assert complete['result']['status'] == 'completed'
    assert not complete['answer']['gaps']
    partial = execute(Documents((10, 1)), ReconciledModel())
    assert partial['result']['status'] == 'partial'
    assert 'coverage incomplete' in partial['answer']['gaps'][0]


@pytest.mark.parametrize('counts', [(2,), (2, 1)])
def test_model_page_range_cannot_certify_full_reading_by_narrowing_scope(counts):
    class RangeModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_plan':
                result['page_ranges'] = [{'version_id': '0', 'first': 1, 'last': 1}]
                result['comparison_requested'] = len(counts) > 1
            return result
    output = execute(Documents(counts), RangeModel())
    assert output['result']['status'] == 'partial'
    assert any('outside the model reading plan' in gap for gap in output['answer']['gaps'])
    assert output['result']['coverage'][0]['omitted'] == ['page:2:outside_planned_range']
    if len(counts) > 1:
        assert any('cross-document comparison' in gap for gap in output['answer']['gaps'])


@pytest.mark.parametrize('assessment_ids', [[], ['0', '0'], ['0', 'foreign']])
def test_synthesis_requires_exactly_one_assessment_per_target(assessment_ids):
    class InvalidAssessment(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_synthesis':
                result['documents'] = [{'version_id': vid, 'semantic_sufficiency': 'sufficient'}
                                       for vid in assessment_ids]
            return result
    with pytest.raises(DocumentError) as error:
        execute(Documents((1, 1)), InvalidAssessment())
    assert error.value.code == 'invalid_pdf_output'


@pytest.mark.parametrize('comparison_kind, expected', [
    ('none', 'partial'), ('same_source', 'partial'), ('cross_source', 'completed')])
def test_comparison_requires_a_grounded_cross_source_conclusion(comparison_kind, expected):
    class ComparingModel(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_plan':
                result['comparison_requested'] = True
            if payload['phase'] == 'pdf_synthesis' and comparison_kind != 'none':
                first = payload['findings'][0]['evidence_ids'][0]
                second = payload['findings'][1]['evidence_ids'][0]
                result['comparisons'] = [{'text': 'Both documents state the same property.',
                    'evidence_ids': [first, second if comparison_kind == 'cross_source' else first]}]
            return result
    output = execute(Documents((1, 1)), ComparingModel())
    assert output['result']['status'] == expected
    if expected == 'completed':
        assert len(output['answer']['segments'][-1]['citation_ids']) == 2
    else:
        assert any('comparison' in gap for gap in output['answer']['gaps'])


def test_comparison_with_unknown_evidence_is_rejected():
    class InvalidComparison(Model):
        def generate(self, system, payload, schema, budget):
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_synthesis':
                result['comparisons'] = [{'text': 'Unsupported comparison.', 'evidence_ids': ['foreign']}]
            return result
    with pytest.raises(DocumentError) as error:
        execute(Documents((1, 1)), InvalidComparison())
    assert error.value.code == 'invalid_pdf_citations'
