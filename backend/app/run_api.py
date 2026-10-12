"""Conversation graph endpoints; developer observations have a separate channel."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agent_protocol import DocumentVersion

router = APIRouter(prefix='/api/sessions/{session_id}/runs')
developer_router = APIRouter(prefix='/api/developer/sessions/{session_id}/runs')


class Submission(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    request_id: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=8000)
    expected_data_version: int = Field(ge=0)
    expected_rule_version: int = Field(ge=0)
    explicit_sources: list[DocumentVersion] | None = None


class Resume(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    reply: str | None = Field(default=None, min_length=1, max_length=8000)


def schedule(request, run):
    if run['status'] == 'queued':
        state = request.app.state
        with state.run_schedule_lock:
            if run['run_id'] not in state.scheduled_runs:
                state.scheduled_runs.add(run['run_id'])
                def execute():
                    try:
                        while True:
                            state.runs.execute(run['run_id'])
                            with state.run_schedule_lock:
                                # A resume may arrive after the graph releases its
                                # session lock but before this worker leaves.
                                current = state.runs.inspect(run['session_id'], run['run_id'])
                                if current['status'] == 'queued':
                                    continue
                                state.scheduled_runs.discard(run['run_id'])
                                break
                    except Exception:
                        with state.run_schedule_lock:
                            state.scheduled_runs.discard(run['run_id'])
                        raise
                    finally:
                        from app.run_cleanup import retry_purges
                        retry_purges(state.runs)
                state.run_executor.submit(execute)
    return run


@router.post('', status_code=202)
def submit(session_id: str, body: Submission, request: Request):
    run = request.app.state.runs.submit(session_id, body.request_id, body.question,
        expected_data_version=body.expected_data_version, expected_rule_version=body.expected_rule_version,
        explicit_sources=None if body.explicit_sources is None else tuple(body.explicit_sources))
    return schedule(request, run)


@router.get('')
def list_runs(session_id: str, request: Request):
    return request.app.state.runs.list(session_id)


@router.get('/{run_id}')
def get_run(session_id: str, run_id: str, request: Request):
    return request.app.state.runs.inspect(session_id, run_id)


@router.post('/{run_id}/resume', status_code=202)
def resume(session_id: str, run_id: str, body: Resume, request: Request):
    return schedule(request, request.app.state.runs.resume(session_id, run_id, reply=body.reply))


@router.post('/{run_id}/stop')
def stop(session_id: str, run_id: str, request: Request):
    return request.app.state.runs.stop(session_id, run_id)


@router.get('/{run_id}/events')
def events(session_id: str, run_id: str, request: Request):
    return request.app.state.runs.events(session_id, run_id)


@developer_router.get('/{run_id}/events')
def developer_events(session_id: str, run_id: str, request: Request):
    return request.app.state.runs.events(session_id, run_id, developer=True)
