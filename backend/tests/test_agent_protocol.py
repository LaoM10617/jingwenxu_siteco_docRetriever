import pytest
from pydantic import ValidationError

from app.agent_protocol import DocumentVersion, ScopeSnapshot, TaskPackage


def task():
    return TaskPackage(session_id='s1', turn_id='t1', run_id='r1', task_id='pdf1',
        objective='Find the voltage', specialist='pdf',
        scope=ScopeSnapshot(documents=(DocumentVersion(document_id='d1', version_id='v1'),)))


def test_task_is_a_stable_snapshot_without_shared_chat_state():
    package = task()
    restored = TaskPackage.model_validate_json(package.model_dump_json())
    assert restored == package
    with pytest.raises(ValidationError):
        package.scope.documents = ()
    with pytest.raises(ValidationError):
        TaskPackage.model_validate({**package.model_dump(), 'messages': ['private chat']})


def test_result_rejects_other_task_and_sources_outside_snapshot():
    from app.agent_protocol import EvidenceDescriptor, TaskResult, validate_result

    package = task()
    fields = dict(session_id='s1', turn_id='t1', run_id='r1', task_id='pdf1', status='completed')
    evidence = EvidenceDescriptor(evidence_id='e1', source=package.scope.documents[0],
        location='page 2', scope=package.scope)
    result = TaskResult(**fields, evidence_refs=(evidence,))
    assert validate_result(package, result) == result
    with pytest.raises(ValueError, match='identity'):
        validate_result(package, TaskResult(**{**fields, 'session_id': 's2'}))
    with pytest.raises(ValueError, match='scope'):
        validate_result(package, TaskResult(**fields, evidence_refs=(
            EvidenceDescriptor(evidence_id='e2', source=DocumentVersion(document_id='d1', version_id='v2'),
                location='page 2', scope=package.scope),)))


def test_clarification_requires_a_question_and_user_events_reject_technical_state():
    from app.agent_protocol import DeveloperEvent, TaskResult, UserEvent

    fields = dict(session_id='s1', turn_id='t1', run_id='r1', task_id='pdf1')
    with pytest.raises(ValidationError, match='question'):
        TaskResult(**fields, status='clarification')
    result = TaskResult(**fields, status='clarification', clarification='Which unit?')
    assert result.clarification == 'Which unit?'
    developer = DeveloperEvent(**fields, kind='node', node='retrieve', detail='diagnostic only')
    with pytest.raises(ValidationError):
        UserEvent.model_validate(developer.model_dump())
    with pytest.raises(ValidationError):
        UserEvent(**fields, kind='progress', message='Reading', internal_state={'secret': 'x'})
    assert UserEvent(**fields, kind='progress', message='Reading').channel == 'user'


@pytest.mark.parametrize('scope', [
    ScopeSnapshot(documents=(DocumentVersion(document_id='d2', version_id='v1'),),
        purpose='price', filters=('year=2026',)),
    ScopeSnapshot(documents=(DocumentVersion(document_id='d1', version_id='v1'),),
        purpose='specification', filters=('year=2026',)),
    ScopeSnapshot(documents=(DocumentVersion(document_id='d1', version_id='v1'),), purpose='price'),
])
def test_artifact_cannot_drop_filters_change_purpose_or_add_sources(scope):
    from app.agent_protocol import ArtifactDescriptor, TaskResult, validate_result

    package = TaskPackage(**{**task().model_dump(), 'scope': ScopeSnapshot(
        documents=task().scope.documents, purpose='price', filters=('year=2026',))})
    result = TaskResult(session_id='s1', turn_id='t1', run_id='r1', task_id='pdf1',
        status='completed', artifact_refs=(ArtifactDescriptor(artifact_id='a1', version_id='av1',
            kind='table', scope=scope, storage_ref='artifacts/a1/av1'),))
    with pytest.raises(ValueError, match='scope'):
        validate_result(package, result)


def test_protocol_rejects_unknown_version_and_coerced_budget():
    from app.agent_protocol import ExecutionBudget

    with pytest.raises(ValidationError):
        TaskPackage(**{**task().model_dump(), 'protocol_version': 2})
    with pytest.raises(ValidationError):
        ExecutionBudget(max_steps='8')
