"""Task-local PDF graph reusing the validated retrieval and numerical tools."""
from copy import deepcopy
import json
import re
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent_protocol import (Coverage, EvidenceDescriptor, Finding, ProductIdentifier, TaskPackage,
                                TaskResult, validate_result)
from app.documents import DocumentError
from app.answers import AnswerService
from app.questions import QuestionTools
from app.pdf_analysis import analyze


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
    def __init__(self, model, budget, task_id, extract_products=False):
        self.delegate, self.budget = model, budget
        self.task_id = task_id
        self.provider = model.provider
        self.model = model.model
        self.extract_products = extract_products
        self.products = []

    def _request(self, system, payload, schema):
        if self.extract_products:
            system += (' You are the PDF specialist in a dependent PDF-to-CSV task. '
                'Complete only the PDF product selection, properties and evidence portion. '
                'The downstream CSV specialist is responsible for prices/calculations. '
                'CSV absence here is expected, not a PDF gap or clarification reason. '
                'Preserve the user constraints that apply to your PDF role.')
        if self.extract_products and payload['phase'] == 'pdf_read':
            system += (' Preserve the exact article/order/product identifiers matching the requested '
                'conditions in findings text with source evidence IDs, including leading zeros. '
                'Do not omit identifiers needed for subsequent CSV matching or infer absent identifiers.')
        if not self.extract_products or payload['phase'] not in ('answer', 'answer_after_tools', 'pdf_synthesis'):
            return system, schema
        schema = deepcopy(schema)
        schema['properties']['product_identifiers'] = {'type': 'array', 'maxItems': 100,
            'items': {'type': 'object', 'additionalProperties': False,
                'properties': {'value': {'type': 'string', 'minLength': 1},
                    'evidence_ids': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}}},
                'required': ['value', 'evidence_ids']}}
        schema['required'].append('product_identifiers')
        system += (' Return product_identifiers for products matching the requested conditions. '
            'Copy explicit article/order/product identifiers exactly as strings, preserving leading zeros. '
            'Each identifier must occur literally in its cited source and in a grounded finding/segment. '
            'Use the same evidence/citation IDs as the answer. Do not invent or infer missing IDs; '
            'return [] and explain the gap when ownership or selection is ambiguous.')
        return system, schema

    def _payload(self, payload):
        phase = payload['phase']
        return {**payload, 'phase': phase if phase.startswith('pdf_') else f'pdf_facts_{phase}',
                'task_id': self.task_id}

    def generate(self, system, payload, schema, budget):
        self.budget.check()
        cached = self.has_receipt(system, payload, schema)
        if not cached and self.remaining_calls() <= 0:
            raise DocumentError('task_budget_exhausted', 'The PDF task model budget was reached.', 409)
        if not cached:
            self.budget.calls_left -= 1
        system, schema = self._request(system, payload, schema)
        result = self.delegate.generate(system, self._payload(payload), schema, budget)
        if self.extract_products and 'product_identifiers' in schema.get('properties', {}):
            result = deepcopy(result)
            self.products = result.pop('product_identifiers', [])
        self.budget.check()
        return result

    def has_receipt(self, system, payload, schema):
        check = getattr(self.delegate, 'has_receipt', None)
        system, schema = self._request(system, payload, schema)
        return bool(check and check(system, self._payload(payload), schema))

    def remaining_calls(self):
        remaining = getattr(self.delegate, 'remaining_calls', None)
        return min(self.budget.calls_left, remaining()) if remaining else self.budget.calls_left


class _PerDocumentRetriever:
    """Retain the validated retriever while allocating candidate space per file."""
    def __init__(self, delegate):
        self.delegate = delegate

    def retrieve(self, question, document_ids, **kwargs):
        outputs = [self.delegate.retrieve(question, [identity], **kwargs) for identity in document_ids]
        records = []
        for index in range(max((len(o['records']) for o in outputs), default=0)):
            records.extend(o['records'][index] for o in outputs if index < len(o['records']))
        return {'document_ids': document_ids, 'records': records,
            'warnings': [w for o in outputs for w in o.get('warnings', [])],
            'routes': {'per_document': [o.get('routes', {}) for o in outputs]},
            'diagnostics': {'strategy': 'per_document', 'selected_count': len(records),
                'documents': {identity: o.get('diagnostics', {}) for identity, o in zip(document_ids, outputs)}}}


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
        model = _Model(self.answers.model, budget, task.task_id, task.extract_product_identifiers)
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
            if task.pdf_mode != 'facts':
                return {'answer': analyze(task, self.answers.tools.documents, model, budget)}
            answers = AnswerService(QuestionTools(self.answers.tools.documents,
                _PerDocumentRetriever(self.answers.tools.retriever)), model)
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
            return {'output': self._collect(task, {**state['answer'], 'product_identifiers': model.products})}

        builder = StateGraph(_State)
        builder.add_node('validate_sources', validate)
        builder.add_node('retrieve_and_answer', answer)
        builder.add_node('validate_result', collect)
        builder.add_edge(START, 'validate_sources')
        builder.add_edge('validate_sources', 'retrieve_and_answer')
        builder.add_edge('retrieve_and_answer', 'validate_result')
        builder.add_edge('validate_result', END)
        try:
            output = builder.compile(checkpointer=False).invoke(
                {'task': task.model_dump(mode='json')}, durability='exit')['output']
        except DocumentError as exc:
            if exc.code.startswith('generation_invalid_'):
                raise DocumentError(exc.code.replace('generation_invalid_', 'invalid_pdf_', 1),
                                    str(exc), exc.status_code, exc.retryable) from None
            raise
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
        products = []
        if task.extract_product_identifiers:
            citations = {c['citation_id']: c for c in answer['citations']}
            for raw in answer.get('product_identifiers', []):
                try:
                    product = ProductIdentifier.model_validate_json(json.dumps(raw))
                except ValueError:
                    raise DocumentError('invalid_pdf_products', 'PDF product identifiers are malformed.', 502) from None
                # Boundary checks reject substring matches such as 001 inside 1001.
                pattern = r'(?<![\w-])' + re.escape(product.value) + r'(?![\w-])'
                if any(identity not in citations or not re.search(pattern, citations[identity].get('text', ''))
                       for identity in product.evidence_ids):
                    raise DocumentError('invalid_pdf_products', 'PDF product identifier is not present in its cited source.', 502)
                products.append(ProductIdentifier(value=product.value, evidence_ids=tuple(
                    f'{task.task_id}:{identity}' for identity in product.evidence_ids)))
        result = TaskResult(session_id=task.session_id, turn_id=task.turn_id, run_id=task.run_id,
            task_id=task.task_id, status=status,
            findings=tuple(Finding(text=segment['text'], evidence_ids=tuple(
                f"{task.task_id}:{identity}" for identity in segment['citation_ids'])) for segment in answer['segments']),
            evidence_refs=tuple(descriptors), product_identifiers=tuple(products), gaps=gaps, clarification=clarification,
            coverage=tuple(Coverage.model_validate_json(json.dumps(item)) for item in answer['coverage'])
                if 'coverage' in answer else tuple(Coverage(source=ref, processed=tuple(
                    item.evidence_id for item in descriptors if item.source == ref)) for ref in task.scope.documents))
        validate_result(task, result)
        safe = {key: deepcopy(answer[key]) for key in ('outcome', 'segments', 'citations', 'calculations', 'gaps', 'warnings')}
        diagnostics = {key: deepcopy(answer[key]) for key in (
            'provider', 'model', 'retrieval_diagnostics', 'context', 'validation', 'tool_results', 'unresolved') if key in answer}
        return {'result': result.model_dump(mode='json'), 'answer': safe,
                'evidence': evidence, 'diagnostics': diagnostics}
