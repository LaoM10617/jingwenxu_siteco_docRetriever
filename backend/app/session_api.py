"""Deterministic session API; language interpretation belongs to the later graph."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agent_protocol import DocumentVersion, ResolvedReference


router = APIRouter(prefix='/api/sessions')


class Body(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class SourceChange(Body):
    source: DocumentVersion
    expected_data_version: int = Field(ge=0)


class RulesChange(Body):
    expected_rule_version: int = Field(ge=0)
    default_sources: list[DocumentVersion] | None = None
    purpose_sources: dict[str, list[DocumentVersion]] = Field(default_factory=dict)


class FocusChange(Body):
    focus: ResolvedReference | None = None


class SnapshotRequest(Body):
    request_id: str = Field(min_length=1)
    expected_data_version: int = Field(ge=0)
    expected_rule_version: int = Field(ge=0)
    purpose: str | None = None
    explicit_sources: list[DocumentVersion] | None = None
    filters: list[str] = Field(default_factory=list)


class UserMessage(Body):
    message_id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class ReuseRequest(Body):
    snapshot_id: str = Field(min_length=1)


@router.post('', status_code=201)
def create_session(request: Request):
    return request.app.state.sessions.create()


@router.get('')
def list_sessions(request: Request):
    return request.app.state.sessions.list()


@router.get('/{session_id}')
def get_session(session_id: str, request: Request):
    return request.app.state.sessions.get(session_id)


@router.delete('/{session_id}')
def delete_session(session_id: str, request: Request):
    from app.run_cleanup import delete_session as delete_with_runs
    delete_with_runs(request.app.state.runs, session_id)
    return {'deleted': True}


@router.post('/{session_id}/sources')
def attach_source(session_id: str, body: SourceChange, request: Request):
    return request.app.state.sessions.attach(session_id, body.source,
                                            expected_data_version=body.expected_data_version)


@router.post('/{session_id}/sources/remove')
def remove_source(session_id: str, body: SourceChange, request: Request):
    return request.app.state.sessions.remove(session_id, body.source,
                                            expected_data_version=body.expected_data_version)


@router.put('/{session_id}/rules')
def update_rules(session_id: str, body: RulesChange, request: Request):
    return request.app.state.sessions.set_rules(
        session_id, expected_rule_version=body.expected_rule_version,
        default_sources=None if body.default_sources is None else tuple(body.default_sources),
        purpose_sources={key: tuple(values) for key, values in body.purpose_sources.items()})


@router.put('/{session_id}/focus')
def update_focus(session_id: str, body: FocusChange, request: Request):
    return request.app.state.sessions.set_focus(session_id, body.focus)


@router.post('/{session_id}/snapshots', status_code=201)
def create_snapshot(session_id: str, body: SnapshotRequest, request: Request):
    return request.app.state.sessions.snapshot(
        session_id, body.request_id, purpose=body.purpose,
        explicit_sources=None if body.explicit_sources is None else tuple(body.explicit_sources),
        expected_data_version=body.expected_data_version, expected_rule_version=body.expected_rule_version,
        filters=tuple(body.filters))


@router.get('/{session_id}/snapshots/{snapshot_id}')
def read_snapshot(session_id: str, snapshot_id: str, request: Request):
    return request.app.state.sessions.read_snapshot(session_id, snapshot_id)


@router.post('/{session_id}/messages', status_code=201)
def append_message(session_id: str, body: UserMessage, request: Request):
    return request.app.state.sessions.append_message(session_id, body.message_id, 'user', body.content)


@router.get('/{session_id}/messages')
def list_messages(session_id: str, request: Request):
    return request.app.state.sessions.messages(session_id)


@router.get('/{session_id}/events')
def list_events(session_id: str, request: Request):
    return request.app.state.sessions.events(session_id)


@router.get('/{session_id}/artifacts/{artifact_id}')
def get_artifact(session_id: str, artifact_id: str, request: Request):
    return request.app.state.artifacts.get(session_id, artifact_id)


@router.post('/{session_id}/artifacts/{artifact_id}/reuse')
def reuse_artifact(session_id: str, artifact_id: str, body: ReuseRequest, request: Request):
    return request.app.state.artifacts.reuse(session_id, artifact_id, body.snapshot_id)
