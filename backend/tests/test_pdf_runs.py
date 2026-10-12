"""PDF reading routes and durable model receipts at the conversation interface."""
from io import BytesIO
from types import SimpleNamespace
import pytest

from app.conversation_runs import ConversationRuns
from app.documents import DocumentService
from app.processing import DocumentProcessor
from app.sessions import SessionStore
from app.pdf_specialist import PdfSpecialist
from test_conversation_runs import Model
from test_csv_lifecycle import terminal
from test_csv_runs import Specialist
from test_parsing import pdf_file
from test_pdf_publication import Gateway


def test_pdf_reading_mode_preserves_request_and_six_call_ceiling(tmp_path):
    documents = DocumentService(tmp_path / 'runtime')
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']
    documents.start(DocumentProcessor(Gateway()))
    try:
        path = pdf_file(tmp_path, ['Product A. Read the full document.'])
        did = documents.submit('A.pdf', BytesIO(path.read_bytes()), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        model = Model([{'route': 'pdf', 'pdf_mode': 'coverage', 'objective': 'Summarize'}])
        specialist = Specialist()
        service = SimpleNamespace(model=model, config_snapshot={})
        runs = ConversationRuns(documents.database, SimpleNamespace(documents=documents, answers=lambda: service),
                                lambda _: specialist)
        run = runs.submit(sid, 'summary', 'Summarize every page and disclose missing coverage.',
                          expected_data_version=1, expected_rule_version=0)
        assert runs.execute(run['run_id'])['status'] == 'completed'
        task = specialist.tasks[0]
        assert task.pdf_mode == 'coverage'
        assert task.budget.max_model_calls == 5  # one of six calls already used for intent
        assert any('every page' in text for text in task.constraints)
    finally:
        documents.stop()


@pytest.mark.parametrize('interruption', ['invalid_citation', 'stop'])
def test_pdf_resume_reuses_reading_receipts_without_automatic_calls(tmp_path, interruption):
    from test_pdf_analysis import Model as ReadingModel

    documents = DocumentService(tmp_path / 'runtime')
    documents.lifecycle = SessionStore(documents.database)
    sid = documents.lifecycle.create()['session_id']

    class InterruptModel(ReadingModel):
        def generate(self, system, payload, schema, budget):
            if payload['phase'] == 'intent':
                self.calls.append(payload)
                return {'route': 'pdf', 'pdf_mode': 'coverage', 'objective': 'Summarize every page'}
            result = super().generate(system, payload, schema, budget)
            if payload['phase'] == 'pdf_synthesis' and sum(
                    p['phase'] == 'pdf_synthesis' for p in self.calls) == 1:
                if interruption == 'stop':
                    runs.stop(sid, run_id)
                else:
                    result['findings'][0]['evidence_ids'] = ['unread']
            return result

    model = InterruptModel()
    service = SimpleNamespace(model=model, config_snapshot={}, tools=SimpleNamespace(documents=documents))
    bindings = SimpleNamespace(documents=documents, answers=lambda: service)
    runs = ConversationRuns(documents.database, bindings, PdfSpecialist)
    documents.start(DocumentProcessor(Gateway()))
    try:
        path = pdf_file(tmp_path, ['Product A has a documented property.'])
        did = documents.submit('A.pdf', BytesIO(path.read_bytes()), session_id=sid)['document_id']
        assert terminal(documents, did)['status'] == 'ready'
        run_id = runs.submit(sid, 'summary', 'Summarize every page', expected_data_version=1,
                             expected_rule_version=0)['run_id']
        assert runs.execute(run_id)['status'] == ('stopped' if interruption == 'stop' else 'failed')
        phases = [p['phase'] for p in model.calls]
        runs = ConversationRuns(documents.database, bindings, PdfSpecialist)
        runs.execute(run_id)
        assert [p['phase'] for p in model.calls] == phases
        runs.resume(sid, run_id)
        assert [p['phase'] for p in model.calls] == phases
        done = runs.execute(run_id)
        assert done['status'] == 'completed', done
        assert [p['phase'] for p in model.calls] == phases + ['pdf_synthesis']
        assert len(model.calls) == 5
        assert len(runs.sessions.messages(sid)) == 2
    finally:
        documents.stop()
