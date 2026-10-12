"""Versioned messages at the main graph / specialist graph interface.

These snapshots carry references, never mutable graph state or chat history.
Document availability and scope resolution belong to the session store.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1)]


class ProtocolModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


class DocumentVersion(ProtocolModel):
    document_id: Identifier
    version_id: Identifier


class ScopeSnapshot(ProtocolModel):
    documents: tuple[DocumentVersion, ...]
    purpose: str | None = None
    filters: tuple[str, ...] = ()


class TaskIdentity(ProtocolModel):
    session_id: Identifier
    turn_id: Identifier
    run_id: Identifier
    task_id: Identifier


class ExecutionBudget(ProtocolModel):
    max_steps: int = Field(default=8, gt=0)
    max_model_calls: int = Field(default=4, ge=0)
    timeout_seconds: int = Field(default=60, gt=0)


class ResolvedReference(ProtocolModel):
    kind: Literal['product', 'document', 'artifact', 'row_set']
    reference_id: Identifier
    description: str


class TaskPackage(TaskIdentity):
    protocol_version: Literal[1] = 1
    objective: Annotated[str, Field(min_length=1)]
    specialist: Literal['pdf', 'csv']
    scope: ScopeSnapshot
    resolved_references: tuple[ResolvedReference, ...] = ()
    input_artifacts: tuple[Identifier, ...] = ()
    constraints: tuple[str, ...] = ()
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)


class EvidenceDescriptor(ProtocolModel):
    evidence_id: Identifier
    source: DocumentVersion
    location: Identifier
    scope: ScopeSnapshot


class ArtifactDescriptor(ProtocolModel):
    artifact_id: Identifier
    version_id: Identifier
    kind: Literal['table', 'numeric', 'chart', 'answer']
    scope: ScopeSnapshot
    storage_ref: Identifier
    calculation: str | None = None
    unit: str | None = None


class Finding(ProtocolModel):
    text: Identifier
    evidence_ids: tuple[Identifier, ...] = ()
    artifact_ids: tuple[Identifier, ...] = ()


class Coverage(ProtocolModel):
    source: DocumentVersion
    processed: tuple[str, ...] = ()
    omitted: tuple[str, ...] = ()
    semantic_sufficiency: Literal['sufficient', 'limited', 'unknown'] = 'unknown'


class TaskResult(TaskIdentity):
    protocol_version: Literal[1] = 1
    status: Literal['completed', 'partial', 'clarification', 'failed']
    findings: tuple[Finding, ...] = ()
    evidence_refs: tuple[EvidenceDescriptor, ...] = ()
    artifact_refs: tuple[ArtifactDescriptor, ...] = ()
    coverage: tuple[Coverage, ...] = ()
    gaps: tuple[str, ...] = ()
    clarification: str | None = None

    @model_validator(mode='after')
    def check_clarification(self):
        if self.status == 'clarification' and not (self.clarification or '').strip():
            raise ValueError('clarification requires a question')
        if self.status != 'clarification' and self.clarification is not None:
            raise ValueError('question requires clarification status')
        return self


class UserEvent(TaskIdentity):
    protocol_version: Literal[1] = 1
    channel: Literal['user'] = 'user'
    kind: Literal['progress', 'answer', 'artifact', 'clarification', 'error']
    message: str
    artifact_ids: tuple[Identifier, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()


class DeveloperEvent(TaskIdentity):
    protocol_version: Literal[1] = 1
    channel: Literal['developer'] = 'developer'
    kind: Literal['node', 'model_call', 'execution', 'error']
    node: Identifier
    detail: str
    elapsed_ms: float | None = Field(default=None, ge=0)


def validate_result(task: TaskPackage, result: TaskResult) -> TaskResult:
    """Check the returned identity and declared provenance before collecting it.

    Filter strings are opaque at this seam: require every original constraint,
    rather than guessing that a specialist's rewritten expression is equivalent.
    """
    for field in TaskIdentity.model_fields:
        if getattr(task, field) != getattr(result, field):
            raise ValueError('result identity does not match task')
    allowed = set(task.scope.documents)
    for descriptor in (*result.evidence_refs, *result.artifact_refs):
        scope = descriptor.scope
        if (not set(scope.documents) <= allowed or scope.purpose != task.scope.purpose
                or not set(task.scope.filters) <= set(scope.filters)):
            raise ValueError('result scope exceeds task scope')
    for evidence in result.evidence_refs:
        if evidence.source not in allowed or evidence.source not in evidence.scope.documents:
            raise ValueError('evidence source exceeds scope')
    if any(item.source not in allowed for item in result.coverage):
        raise ValueError('coverage source exceeds scope')
    evidence_ids = {item.evidence_id for item in result.evidence_refs}
    artifact_ids = {item.artifact_id for item in result.artifact_refs}
    for finding in result.findings:
        if not set(finding.evidence_ids) <= evidence_ids or not set(finding.artifact_ids) <= artifact_ids:
            raise ValueError('finding references unknown evidence or artifact')
    return result
