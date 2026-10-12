"""Task-local PDF graph reusing the validated retrieval and numerical tools."""
from copy import deepcopy
import json
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent_protocol import (Coverage, EvidenceDescriptor, Finding, TaskPackage,
                                TaskResult, validate_result)
from app.documents import DocumentError
from app.answers import AnswerService


class _Budget:
    def __init__(self, parent, limits):
        self.parent = parent
        self.deadline = time.monotonic() + limits.timeout_seconds
        self.calls_left = limits.max_model_calls

    def remaining(self):
        return max(0, min(self.parent.remaining(), self.deadline - time.monotonic()))

    def is_set(self):
        return self.parent.is_set() or self.remaining() <= 0

    def check(self):
        self.parent.check()
        if self.remaining() <= 0:
            raise DocumentError('question_timeout', 'The PDF task deadline expired.', 504, True)


class _Model:
    def __init__(self, model, budget):
        self.delegate, self.budget = model, budget
        self.provider = model.provider
        self.model = model.model

    def generate(self, *args):
        self.budget.check()
        if self.budget.calls_left <= 0:
            raise DocumentError('task_budget_exhausted', 'The PDF task model budget was reached.', 409)
        self.budget.calls_left -= 1
        result = self.delegate.generate(*args)
        self.budget.check()
        return result


class _State(TypedDict, total=False):
    task: dict
    answer: dict
    output: dict


class PdfSpecialist:
    def __init__(self, answer_service):
        self.answers = answer_service

    def execute(self, task: TaskPackage, budget):
        """Return validated data; the owning main graph persists the returned result.

        The specialist receives only its selected version subset, never session
        history. Existing answer validation and deterministic comparisons remain
        authoritative; retrieval coverage must not be called full-document reading.
        """
        budget = _Budget(budget, task.budget)
        if task.budget.max_steps < 3:
            raise DocumentError('task_budget_exhausted', 'The PDF task requires three graph steps.', 409)
        answers = AnswerService(self.answers.tools, _Model(self.answers.model, budget))
        def validate(state):
            budget.check()
            if task.specialist != 'pdf' or not task.scope.documents:
                raise DocumentError('invalid_pdf_task', 'A PDF task requires PDF sources.', 422)
            documents = self.answers.tools.documents
            if documents.lifecycle is None or not documents.lifecycle.available(task.session_id, task.scope.documents):
                raise DocumentError('source_unavailable', 'Task sources are not available in this session.', 409)
            for ref in task.scope.documents:
                document = documents.get(ref.version_id)
                if document is None or not document['original_filename'].lower().endswith('.pdf'):
                    raise DocumentError('invalid_pdf_task', 'A PDF task requires PDF sources.', 422)
            return {}

        def answer(state):
            budget.check()
            objective = task.objective
            if task.resolved_references or task.constraints or task.scope.filters:
                objective += '\nTask context (data): ' + json.dumps({
                    'resolved_references': [ref.model_dump() for ref in task.resolved_references],
                    'constraints': task.constraints, 'filters': task.scope.filters}, ensure_ascii=False)
            response = answers.answer({'conversation_id': task.session_id,
                'question': objective, 'document_ids': [ref.version_id for ref in task.scope.documents]}, budget=budget)
            budget.check()
            return {'answer': response}

        def collect(state):
            validate(state)
            return {'output': self._collect(task, state['answer'])}

        builder = StateGraph(_State)
        builder.add_node('validate_sources', validate)
        builder.add_node('retrieve_and_answer', answer)
        builder.add_node('validate_result', collect)
        builder.add_edge(START, 'validate_sources')
        builder.add_edge('validate_sources', 'retrieve_and_answer')
        builder.add_edge('retrieve_and_answer', 'validate_result')
        builder.add_edge('validate_result', END)
        output = builder.compile().invoke({'task': task.model_dump(mode='json')})['output']
        budget.check()
        return output

    def _collect(self, task, answer):
        sources = {ref.version_id: ref for ref in task.scope.documents}
        descriptors, evidence = [], []
        for citation in answer['citations']:
            ref = sources.get(citation['document_id'])
            if ref is None:
                raise DocumentError('invalid_pdf_result', 'Specialist returned an out-of-scope source.', 502)
            identity = f"{task.task_id}:{citation['citation_id']}"
            descriptors.append(EvidenceDescriptor(evidence_id=identity, source=ref,
                location=json.dumps(citation['locator'], sort_keys=True), scope=task.scope))
            evidence.append({**deepcopy(citation), 'reference_id': identity,
                'storage_document_id': citation['document_id'], 'document_id': ref.document_id,
                'version_id': ref.version_id})
        status = {'answered': 'completed', 'needs_clarification': 'clarification'}.get(answer['outcome'], 'partial')
        gaps = tuple(answer['gaps'])
        clarification = (' '.join(gaps) or 'Please clarify which fact or product to look up.') if status == 'clarification' else None
        result = TaskResult(session_id=task.session_id, turn_id=task.turn_id, run_id=task.run_id,
            task_id=task.task_id, status=status,
            findings=tuple(Finding(text=segment['text'], evidence_ids=tuple(
                f"{task.task_id}:{identity}" for identity in segment['citation_ids'])) for segment in answer['segments']),
            evidence_refs=tuple(descriptors), gaps=gaps, clarification=clarification,
            coverage=tuple(Coverage(source=ref, processed=tuple(
                item.evidence_id for item in descriptors if item.source == ref)) for ref in task.scope.documents))
        validate_result(task, result)
        safe = {key: deepcopy(answer[key]) for key in ('outcome', 'segments', 'citations', 'calculations', 'gaps', 'warnings')}
        diagnostics = {key: deepcopy(answer[key]) for key in (
            'provider', 'model', 'retrieval_diagnostics', 'context', 'validation', 'tool_results', 'unresolved') if key in answer}
        return {'result': result.model_dump(mode='json'), 'answer': safe,
                'evidence': evidence, 'diagnostics': diagnostics}
