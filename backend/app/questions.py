"""Validated question scope and bounded evidence preparation; no answer generation."""
from copy import deepcopy
import re
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.documents import DocumentError


Identity = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class QuestionRequest(StrictModel):
    conversation_id: Identity
    question: Annotated[str, StringConstraints(min_length=1, max_length=8000, strip_whitespace=True)]
    document_ids: Annotated[list[Identity], Field(min_length=1, max_length=10)]


class PdfLookup(StrictModel):
    tool: Literal['retrieve_pdf']
    document_ids: Annotated[list[Identity], Field(min_length=1, max_length=10)]


class CsvLookup(StrictModel):
    tool: Literal['lookup_orders']
    document_ids: Annotated[list[Identity], Field(min_length=1, max_length=10)]
    order_ids: Annotated[list[Identity], Field(min_length=1, max_length=50)]


class ToolPlan(StrictModel):
    tools: Annotated[list[Annotated[PdfLookup | CsvLookup, Field(discriminator='tool')]],
                     Field(max_length=2)]


def validated(schema, value, code):
    try:
        return schema.model_validate(value)
    except ValidationError:
        raise DocumentError(code, 'Invalid structured question or tool parameters.', 422) from None


class QuestionBudget:
    """One monotonic deadline; providers must also bound their own blocking I/O."""
    def __init__(self, *, now=time.monotonic):
        self.now = now
        self.deadline = now() + 240

    def remaining(self):
        return max(0, self.deadline - self.now())

    def is_set(self):
        return self.remaining() <= 0

    def check(self):
        if self.is_set():
            raise DocumentError('question_timeout', 'The question deadline expired.', 504, True)


class QuestionTools:
    def __init__(self, documents, retriever):
        self.documents, self.retriever = documents, retriever

    def prepare(self, request, *, planner=None, budget=None, on_wait=None, on_stage=None):
        budget = budget if budget is not None else QuestionBudget()
        budget.check()
        request = validated(QuestionRequest, deepcopy(request), 'invalid_question')
        scope = list(dict.fromkeys(request.document_ids))
        documents = {}
        for identity in scope:
            document = self.documents.get(identity)
            if document is None:
                raise DocumentError('document_not_found', 'Unknown document ID.', 404)
            if document['status'] != 'ready':
                raise DocumentError('document_not_ready', 'The document is not available for queries.', 409)
            suffix = document['original_filename'].lower().rsplit('.', 1)[-1]
            if suffix not in ('pdf', 'csv'):
                raise DocumentError('invalid_question', 'Unsupported document type.', 422)
            documents[identity] = {**document, 'media_type': 'application/pdf' if suffix == 'pdf' else 'text/csv'}
        question = {'conversation_id': request.conversation_id, 'question': request.question,
                    'document_ids': scope}
        if planner is None:
            if any(d['media_type'] == 'text/csv' for d in documents.values()):
                raise DocumentError('planning_not_configured', 'A structured query planner is required.', 503)
            raw_plan = {'tools': [{'tool': 'retrieve_pdf', 'document_ids': scope}]}
        else:
            metadata = [{'document_id': identity, 'media_type': d['media_type'],
                         'original_filename': d['original_filename']} for identity, d in documents.items()]
            raw_plan = planner(deepcopy(question), metadata, budget)
        budget.check()
        plan = validated(ToolPlan, raw_plan, 'invalid_tool_plan')
        routes = set()
        for tool in plan.tools:
            expected = 'application/pdf' if tool.tool == 'retrieve_pdf' else 'text/csv'
            if (tool.tool in routes or any(identity not in documents or
                    documents[identity]['media_type'] != expected for identity in tool.document_ids)
                    or set(tool.document_ids) != {identity for identity, d in documents.items()
                                                  if d['media_type'] == expected}):
                raise DocumentError('invalid_tool_plan', 'Tool scope or route is invalid.', 422)
            routes.add(tool.tool)
            if isinstance(tool, CsvLookup):
                for order in tool.order_ids:
                    if not re.search(r'(?<![\w./-])' + re.escape(order) + r'(?![\w./-])', request.question):
                        raise DocumentError('invalid_tool_plan', 'Order IDs must be explicit in the question.', 422)
        result = {**question, 'stage': 'evidence_prepared', 'tools': [], 'evidence': [],
                  'warnings': [{'document_id': identity, **warning}
                               for identity, d in documents.items()
                               for warning in (d.get('parse_result') or {}).get('warnings', [])],
                  'unresolved': []}
        if not plan.tools:
            result['unresolved'].append({'code': 'needs_clarification'})
        for tool in plan.tools:
            budget.check()
            if on_stage:
                on_stage('retrieving' if isinstance(tool, PdfLookup) else 'querying_csv')
            ids = list(dict.fromkeys(tool.document_ids))
            if isinstance(tool, CsvLookup):
                output = self.documents.lookup_orders(tool.order_ids, ids, limit=50)
                if output['unmatched_order_ids']:
                    result['unresolved'].append({'code': 'exact_not_found',
                                                'order_ids': output['unmatched_order_ids'], 'document_ids': ids})
                if output['has_more']:
                    result['unresolved'].append({'code': 'results_paginated', 'total': output['total']})
            else:
                try:
                    callbacks = {'on_start': lambda: on_stage('retrieving')} if on_stage else {}
                    output = self.retriever.retrieve(request.question, ids, stop=budget, on_wait=on_wait, **callbacks)
                except DocumentError:
                    budget.check()
                    raise
                if not output['records']:
                    result['unresolved'].append({'code': 'insufficient_evidence', 'document_ids': ids})
            result['tools'].append({'tool': tool.tool, 'document_ids': ids, 'result': output})
            for source in output['records']:
                result['evidence'].append({'citation_id': f'S{len(result["evidence"]) + 1}',
                                           'source': {**deepcopy(source), 'original_filename':
                                                      documents[source['document_id']]['original_filename']}})
            budget.check()
        return deepcopy(result)
