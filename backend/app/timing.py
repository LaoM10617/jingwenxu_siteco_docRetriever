"""Small diagnostic spans, independent of business identities and model payloads.

Buffers belong to one invocation. Only completed spans are exported; a crash can
leave missing spans, never fabricated zero durations. Persistence is owned by runs.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class TimingEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1
    run_id: str
    turn_id: str | None = None
    task_id: str | None = None
    job_id: str | None = None
    attempt_id: str
    span_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_span_id: str | None = None
    stage: str
    clock_domain: str = 'backend'
    started_at: float = Field(default_factory=time.time)
    duration_ms: float = Field(default=0, ge=0)
    status: Literal['completed', 'failed', 'cancelled', 'timed_out', 'interrupted', 'waiting',
                    'output_limit', 'invalid_output', 'stopped', 'partial', 'clarification'] = 'completed'
    cache_hit: bool | None = None
    row_count: int | None = Field(default=None, ge=0)
    input_bytes: int | None = Field(default=None, ge=0)


@dataclass
class Capture:
    run_id: str
    turn_id: str | None
    attempt_id: str = field(default_factory=lambda: uuid4().hex)
    entries: list = field(default_factory=list)


_capture = ContextVar('timing_capture', default=None)
_parent = ContextVar('timing_parent', default=None)


@contextmanager
def capture(run_id, turn_id=None):
    current = _capture.get()
    if current is not None and current.run_id == run_id:
        yield current
        return
    recorder = Capture(run_id, turn_id)
    token = _capture.set(recorder)
    parent_token = _parent.set(None)
    try:
        yield recorder
    finally:
        _parent.reset(parent_token)
        _capture.reset(token)


@contextmanager
def span(stage, *, task_id=None, job_id=None, attempt_id=None, cache_hit=None):
    recorder = _capture.get()
    parent = _parent.get()
    event = TimingEvent(run_id=recorder.run_id if recorder else '',
        turn_id=recorder.turn_id if recorder else None,
        task_id=task_id or (parent.task_id if parent else None),
        job_id=job_id or (parent.job_id if parent else None),
        attempt_id=attempt_id or (parent.attempt_id if parent else recorder.attempt_id if recorder else uuid4().hex),
        parent_span_id=parent.span_id if parent else None, stage=stage, cache_hit=cache_hit)
    token = _parent.set(event)
    started = time.monotonic()
    try:
        yield event
    except BaseException as error:
        code = getattr(error, 'code', '')
        event.status = ('cancelled' if code in ('run_stopped', 'source_unavailable') else
                        'timed_out' if 'timeout' in code else
                        'waiting' if type(error).__name__ == 'GraphInterrupt' else 'failed')
        raise
    finally:
        event.duration_ms = (time.monotonic() - started) * 1000
        _parent.reset(token)
        if recorder is not None:
            recorder.entries.append(event.model_dump(mode='json'))


def record(stage, seconds, *, clock_domain):
    """Attach a duration measured elsewhere (e.g. on the host) under the current span.

    Only the duration is known, so started_at is this receipt time, not the
    measuring clock's start; order such events by their parent, not by started_at.
    """
    recorder, parent = _capture.get(), _parent.get()
    if recorder is None:
        return
    recorder.entries.append(TimingEvent(run_id=recorder.run_id, turn_id=recorder.turn_id,
        task_id=parent.task_id if parent else None, job_id=parent.job_id if parent else None,
        attempt_id=parent.attempt_id if parent else recorder.attempt_id,
        parent_span_id=parent.span_id if parent else None, stage=stage,
        clock_domain=clock_domain, duration_ms=seconds * 1000).model_dump(mode='json'))


def timed(stage):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            with span(stage):
                return function(*args, **kwargs)
        return measured
    return decorate
