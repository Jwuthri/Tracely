"""Tracely SDK — instrument an agent and export traces to Tracely over OTLP.

    import tracely_sdk as tracely
    tracely.init(endpoint="http://localhost:8000", api_key="tracely_dev_key", service_name="my-agent")

    with tracely.agent("planner", version="v1") as a:
        with tracely.llm("gpt-4o") as g:
            tracely.set_io(g, input=prompt, output=completion)
            tracely.set_usage(g, input_tokens=812, output_tokens=96)
        with tracely.tool("get_weather") as t:
            ...                      # on failure: tracely.error(t, "upstream timeout")
    tracely.flush()

Emits standard gen_ai.* / OpenInference-compatible attributes plus Tracely's first-class
`tracely.*` hints (agent id, version, run, conversation, turn, step, env) so the backend
populates the first-class span columns. Thin wrapper over the OpenTelemetry SDK.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

__all__ = [
    "init", "agent", "turn", "step", "llm", "tool", "set_io", "set_usage", "error", "flush",
]

_tracer: trace.Tracer | None = None
_env: str = "prod"


def init(
    endpoint: str = "http://localhost:8000",
    api_key: str = "tracely_dev_key",
    service_name: str = "agent",
    env: str = "prod",
) -> trace.Tracer:
    """Configure the OTLP exporter pointing at Tracely. Call once at startup."""
    global _tracer, _env
    _env = env
    resource = Resource.create({"service.name": service_name, "telemetry.sdk.language": "python"})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=f"{endpoint.rstrip('/')}/v1/traces",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("tracely-sdk")
    return _tracer


def _t() -> trace.Tracer:
    if _tracer is None:
        init()
    assert _tracer is not None
    return _tracer


@contextmanager
def agent(
    slug: str, *, version: str | None = None, run_id: str | None = None, role: str | None = None
) -> Iterator[Span]:
    with _t().start_as_current_span(slug) as span:
        span.set_attribute("tracely.agent.id", slug)
        span.set_attribute("tracely.observation.type", "AGENT")
        span.set_attribute("tracely.env", _env)
        if version:
            span.set_attribute("tracely.agent.version", version)
        if run_id:
            span.set_attribute("tracely.agent.run_id", run_id)
        if role:
            span.set_attribute("tracely.agent.role", role)
        yield span


@contextmanager
def turn(turn_id: str, *, index: int | None = None) -> Iterator[Span]:
    with _t().start_as_current_span(f"turn:{turn_id}") as span:
        span.set_attribute("tracely.turn.id", turn_id)
        if index is not None:
            span.set_attribute("tracely.turn.index", index)
        yield span


@contextmanager
def step(name: str, *, step_id: str | None = None) -> Iterator[Span]:
    with _t().start_as_current_span(name) as span:
        span.set_attribute("tracely.step.name", name)
        if step_id:
            span.set_attribute("tracely.step.id", step_id)
        yield span


@contextmanager
def llm(model: str, *, agent: str | None = None) -> Iterator[Span]:
    with _t().start_as_current_span(model) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        yield span


@contextmanager
def tool(name: str, *, agent: str | None = None) -> Iterator[Span]:
    with _t().start_as_current_span(name) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        yield span


def _as_str(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, default=str)


def set_io(span: Span, *, input: Any = None, output: Any = None) -> None:
    if input is not None:
        span.set_attribute("tracely.input", _as_str(input))
    if output is not None:
        span.set_attribute("tracely.output", _as_str(output))


def set_usage(span: Span, *, input_tokens: int | None = None, output_tokens: int | None = None) -> None:
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", int(input_tokens))
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))


def error(span: Span, message: str = "") -> None:
    """Mark a span as failed (level=ERROR + status_message) — the failure-detection signal."""
    span.set_status(Status(StatusCode.ERROR, message))


def flush() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
