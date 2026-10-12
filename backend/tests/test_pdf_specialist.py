from io import BytesIO
import json

import pytest

from app.agent_protocol import DocumentVersion, ExecutionBudget, ScopeSnapshot, TaskPackage, TaskResult
from app.answers import AnswerService
from app.documents import DocumentService, DocumentError
from app.pdf_specialist import PdfSpecialist
from app.processing import DocumentProcessor
from app.questions import QuestionBudget, QuestionTools
from app.retrieval.pdf import PdfRetriever
from app.sessions import SessionStore
from test_answers import Model, draft
from test_csv_lifecycle import terminal
from test_parsing import pdf_file
from test_pdf_publication import Gateway


@pytest.fixture
def workspace(tmp_path):
    gateway = Gateway()
    documents = DocumentService(tmp_path / 'runtime')
    sessions = SessionStore(documents.database)
    documents.lifecycle = sessions
    sid = sessions.create()['session_id']
    documents.start(DocumentProcessor(gateway))
    refs = []
    try:
        for name in ('A', 'B'):
            path = pdf_file(tmp_path, [f'{name} power: 12.5 W'])
            doc = documents.submit(name + '.pdf', BytesIO(path.read_bytes()), session_id=sid)
            assert terminal(documents, doc['document_id'])['status'] == 'ready'
            refs.append(DocumentVersion(document_id=doc['document_id'], version_id=doc['document_id']))
        service = AnswerService(QuestionTools(documents, PdfRetriever(documents, documents.lexical, gateway)), Model(draft('S1')))
        task = TaskPackage(session_id=sid, turn_id='turn', run_id='run', task_id='pdf',
                           objective='What is the output?', specialist='pdf', scope=ScopeSnapshot(documents=(refs[0],)))
        yield documents, sessions, service, task, refs
    finally:
        documents.stop()


def test_pdf_task_uses_only_assigned_subset_and_separates_diagnostics(workspace):
    documents, sessions, service, task, refs = workspace
    output = PdfSpecialist(service).execute(task, QuestionBudget())
    result = TaskResult.model_validate_json(json.dumps(output['result']))
    assert result.status == 'completed'
    assert {ref.source for ref in result.evidence_refs} == {refs[0]}
    assert result.findings[0].evidence_ids == ('pdf:S1',)
    assert output['answer']['citations'][0]['document_id'] == refs[0].version_id
    assert output['evidence'][0]['version_id'] == refs[0].version_id
    assert 'provider' not in output['answer']
    assert 'retrieval_diagnostics' not in output['answer']
    assert output['diagnostics']['provider'] == 'test'
    assert result.coverage[0].semantic_sufficiency == 'unknown'


def test_source_removed_during_generation_cannot_be_returned(workspace):
    documents, sessions, service, task, refs = workspace

    class RemovingModel(Model):
        def generate(self, *args):
            current = sessions.get(task.session_id)
            sessions.remove(task.session_id, refs[0], expected_data_version=current['data_version'])
            return draft('S1')

    service.model = RemovingModel(None)
    with pytest.raises(DocumentError) as error:
        PdfSpecialist(service).execute(task, QuestionBudget())
    assert error.value.code == 'source_unavailable'


def test_model_call_budget_prevents_generation(workspace):
    documents, sessions, service, task, refs = workspace
    task = TaskPackage(**{**task.model_dump(), 'budget': ExecutionBudget(max_model_calls=0)})
    with pytest.raises(DocumentError) as error:
        PdfSpecialist(service).execute(task, QuestionBudget())
    assert error.value.code == 'task_budget_exhausted'
    assert service.model.calls == []


def test_pdf_conversion_keeps_deterministic_calculation_and_citations(workspace):
    documents, sessions, service, task, refs = workspace

    class ConvertingModel(Model):
        def generate(self, system, payload, schema, budget):
            if payload['phase'] == 'pdf_facts_answer':
                return {'outcome': 'partial', 'segments': [], 'gaps': [], 'calculations': [
                    {'calculation_id': 'C1', 'operation': {'tool': 'convert',
                     'fact': {'citation_id': 'S1', 'parameter': 'power', 'product': 'A', 'span_index': 0}, 'unit': 'kW'}}]}
            assert payload['calculations'][0]['result']['converted']['value'] == '0.0125'
            return {'outcome': 'answered', 'segments': [{'text': 'A power is 0.0125 kW.',
                'citation_ids': ['S1'], 'calculation_ids': ['C1']}], 'gaps': [], 'calculations': []}

    service.model = ConvertingModel(None)
    output = PdfSpecialist(service).execute(task, QuestionBudget())
    assert output['answer']['calculations'][0]['result']['converted']['value'] == '0.0125'
    assert output['answer']['segments'][0]['calculation_ids'] == ['C1']


def test_clarification_and_invalid_citations_are_not_fabricated_success(workspace):
    documents, sessions, service, task, refs = workspace
    service.model = Model({'outcome': 'needs_clarification', 'segments': [],
                          'gaps': ['Which product?'], 'calculations': []})
    result = PdfSpecialist(service).execute(task, QuestionBudget())['result']
    assert result['status'] == 'clarification'
    assert result['clarification'] == 'Which product?'
    service.model = Model(draft('invented'))
    with pytest.raises(DocumentError) as error:
        PdfSpecialist(service).execute(task, QuestionBudget())
    assert error.value.code == 'invalid_pdf_citations'


def test_stop_after_model_return_prevents_result_publication(workspace):
    documents, sessions, service, task, refs = workspace
    budget = QuestionBudget()

    class StoppingModel(Model):
        def generate(self, *args):
            budget.deadline = 0
            return draft('S1')

    service.model = StoppingModel(None)
    with pytest.raises(DocumentError) as error:
        PdfSpecialist(service).execute(task, budget)
    assert error.value.code == 'question_timeout'
