"""Authenticated worker transport. No caller can choose host paths or Docker options."""
from hmac import compare_digest
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator


router = APIRouter(prefix='/api/execution-worker', tags=['execution-worker'])


def authorized(request: Request):
    secret = request.app.state.settings.execution_worker_token
    token = secret.get_secret_value() if secret else ''
    received = request.headers.get('authorization', '')
    if not token or not compare_digest(received.encode(), ('Bearer ' + token).encode()):
        raise HTTPException(401, 'Worker authentication required')
    return request.app.state.execution_jobs


class WorkerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    worker_id: str = Field(min_length=1, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')
    image: str = Field(pattern=r'^(?:[a-zA-Z0-9./:_-]+@)?sha256:[a-f0-9]{64}$')


class LeaseRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    lease_token: str = Field(min_length=32, max_length=32)


class Result(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    status: Literal['completed', 'failed', 'cancelled', 'timed_out', 'output_limit', 'invalid_output', 'interrupted']
    value: dict | None
    seconds: dict[str, float]
    cleaned_up: bool
    diagnostic: str = Field(default='', max_length=16_777_216)

    @model_validator(mode='after')
    def valid_result(self):
        if self.status == 'completed' and (self.value is None or not self.cleaned_up):
            raise ValueError('Completed output requires cleanup and a JSON object')
        if self.status != 'completed' and self.value is not None:
            raise ValueError('Failed execution cannot carry a value')
        if any(not math.isfinite(v) or v < 0 for v in self.seconds.values()):
            raise ValueError('Invalid timing')
        return self


class Completion(LeaseRequest):
    result: Result


@router.post('/claim')
def claim(body: WorkerRequest, jobs=Depends(authorized)):
    return {'job': jobs.claim(body.worker_id, body.image)}


@router.post('/{job_id}/heartbeat')
def heartbeat(job_id: str, body: LeaseRequest, jobs=Depends(authorized)):
    return {'continue': jobs.heartbeat(job_id, body.lease_token)}


@router.post('/{job_id}/complete')
def complete(job_id: str, body: Completion, jobs=Depends(authorized)):
    try:
        accepted = jobs.complete(job_id, body.lease_token, body.result.model_dump())
    except ValueError:
        raise HTTPException(422, 'Invalid execution result') from None
    return {'accepted': accepted}
