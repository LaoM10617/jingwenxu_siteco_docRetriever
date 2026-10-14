"""Exploration cards and explicit selection, separate from conversational runs."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix='/api/sessions/{session_id}/explorations')
developer_router = APIRouter(prefix='/api/developer/sessions/{session_id}/explorations')


class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


class Selection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    artifact_id: str = Field(min_length=1, max_length=300)


@router.get('')
def list_explorations(session_id: str, request: Request):
    return request.app.state.exploration.list(session_id)


@router.put('/settings')
def configure(session_id: str, body: Settings, request: Request):
    return request.app.state.exploration.configure(session_id, body.enabled)


@router.get('/{identity}')
def get(session_id: str, identity: str, request: Request):
    return request.app.state.exploration.get(session_id, identity)


@router.post('/{identity}/stop')
def stop(session_id: str, identity: str, request: Request):
    return request.app.state.exploration.stop(session_id, identity)


@router.post('/{identity}/resume', status_code=202)
def resume(session_id: str, identity: str, request: Request):
    return request.app.state.exploration.resume(session_id, identity)


@router.post('/{identity}/select')
def select(session_id: str, identity: str, body: Selection, request: Request):
    return request.app.state.exploration.select(session_id, identity, body.artifact_id)


@developer_router.get('/{identity}')
def diagnostics(session_id: str, identity: str, request: Request):
    return request.app.state.exploration.get(session_id, identity, developer=True)
