"""Pydantic v2 API schemas (request/response). Telemetry rows live in events.py."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class IngestResponse(BaseModel):
    batch_id: str
    accepted: bool = True


class AgentOut(BaseModel):
    id: str
    slug: str
    display_name: str
    kind: str
    role: str


class SpanOut(BaseModel):
    span_id: str
    parent_span_id: str
    name: str
    type: str
    level: str
    status_message: str
    start_time: datetime
    end_time: datetime | None = None
    latency_ms: float | None = None
    agent_id: str = ""
    agent_run_id: str = ""
    turn_id: str = ""
    step_name: str = ""
    model_id: str = ""
    input: str | None = None
    output: str | None = None


class TraceDetail(BaseModel):
    trace_id: str
    spans: list[SpanOut]
