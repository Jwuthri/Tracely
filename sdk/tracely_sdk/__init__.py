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
from contextvars import ContextVar
from typing import Any, Callable, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

__all__ = [
    "init", "agent", "turn", "step", "llm", "tool", "thinking", "set_io", "set_usage", "set_metadata",
    "error", "flush", "fixtures", "fixture", "call_llm", "call_tool", "ToolError",
]


class ToolError(RuntimeError):
    """Raised by call_tool/call_llm in hermetic replay when the recorded call errored — so the
    agent's own error handling (try/except) runs exactly as it would against the live tool."""

_tracer: trace.Tracer | None = None
_env: str = "prod"
# recorded tool/LLM outputs for hermetic replay; set by `with fixtures(bundle): ...`
_fixtures: ContextVar[dict | None] = ContextVar("tracely_fixtures", default=None)


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
    slug: str,
    *,
    version: str | None = None,
    run_id: str | None = None,
    role: str | None = None,
    conversation: str | None = None,
    turn: int | None = None,
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
        if conversation:  # groups runs into a thread (session)
            span.set_attribute("tracely.conversation.id", conversation)
            span.set_attribute("session.id", conversation)
        if turn is not None:
            span.set_attribute("tracely.turn.index", int(turn))
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
def llm(
    model: str,
    *,
    agent: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    seed: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """An LLM generation. Pass the sampling parameters (temperature/top_p/max_tokens/…) — they're
    recorded as standard `gen_ai.request.*` attributes and surfaced in the generation's Metadata.
    `metadata` attaches arbitrary key/values (e.g. prompt version, tenant)."""
    with _t().start_as_current_span(model) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        for key, val in (
            ("gen_ai.request.temperature", temperature),
            ("gen_ai.request.top_p", top_p),
            ("gen_ai.request.max_tokens", max_tokens),
            ("gen_ai.request.frequency_penalty", frequency_penalty),
            ("gen_ai.request.presence_penalty", presence_penalty),
            ("gen_ai.request.seed", seed),
        ):
            if val is not None:
                span.set_attribute(key, val)
        if metadata:
            set_metadata(span, **metadata)
        yield span


@contextmanager
def tool(name: str, *, agent: str | None = None) -> Iterator[Span]:
    with _t().start_as_current_span(name) as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        yield span


@contextmanager
def thinking(name: str = "thinking", *, agent: str | None = None, model: str | None = None) -> Iterator[Span]:
    """A reasoning step. First-class observation type THINKING — the model's chain-of-thought,
    emitted as its own span so it shows up distinctly from the GENERATION that follows. Put the
    reasoning text in `set_io(span, output=...)` and reasoning tokens in `set_usage(..., thinking_tokens=)`.
    Pass `model` to record which model produced the reasoning (shown in the Model column)."""
    with _t().start_as_current_span(name) as span:
        span.set_attribute("tracely.observation.type", "THINKING")
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        if model:
            span.set_attribute("gen_ai.request.model", model)
        yield span


def _as_str(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, default=str)


def set_io(span: Span, *, input: Any = None, output: Any = None) -> None:
    if input is not None:
        span.set_attribute("tracely.input", _as_str(input))
    if output is not None:
        span.set_attribute("tracely.output", _as_str(output))


def set_metadata(span: Span, **kv: Any) -> None:
    """Attach arbitrary metadata to a span as `tracely.metadata.<key>` attributes — surfaced in the
    UI's Metadata column / span panel (and searchable). Non-scalar values are JSON-encoded."""
    for k, v in kv.items():
        if v is None:
            continue
        span.set_attribute(
            f"tracely.metadata.{k}",
            v if isinstance(v, (str, int, float, bool)) else json.dumps(v, default=str),
        )


def set_usage(
    span: Span,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    thinking_tokens: int | None = None,
) -> None:
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", int(input_tokens))
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))
    if thinking_tokens is not None:
        span.set_attribute("gen_ai.usage.reasoning_tokens", int(thinking_tokens))


def error(span: Span, message: str = "") -> None:
    """Mark a span as failed (level=ERROR + status_message) — the failure-detection signal."""
    span.set_status(Status(StatusCode.ERROR, message))


def flush() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()


# ── hermetic replay ──────────────────────────────────────────────────────────
# In CI replay we want the agent to see the exact tool/LLM outputs the production trace saw —
# deterministic, offline, no live API keys or cost. `tracely replay` loads each case's recorded
# fixture bundle and activates it here; the agent's call_tool / call_llm then serve from it.


def _normalize_bundle(bundle: dict | None) -> dict:
    """Turn a fixture bundle into consumable FIFO queues keyed by tool/model name.

    Accepts both formats: v2 (`{"version":2, "tools":[{name,args,output,error,...}], "llm":[...]}`,
    ordered so repeated calls and per-call errors replay faithfully) and the legacy v1
    (`{"tools":{name:output}, "llm":{model:output}}`). Returns {"tools": {name:[entry,...]},
    "llm": {model:[entry,...]}} where each entry is {"args","output","error"}.
    """
    store: dict = {"tools": {}, "llm": {}}
    if not bundle:
        return store
    for kind, key_field in (("tools", "name"), ("llm", "model")):
        section = bundle.get(kind)
        if isinstance(section, list):  # v2: ordered list of entries
            for e in section:
                store[kind].setdefault(e.get(key_field), []).append(
                    {"args": e.get("args"), "output": e.get("output"), "error": e.get("error")}
                )
        elif isinstance(section, dict):  # v1: {name: output}
            for k, v in section.items():
                store[kind].setdefault(k, []).append({"args": None, "output": v, "error": None})
    return store


@contextmanager
def fixtures(bundle: dict | None) -> Iterator[None]:
    """Serve recorded outputs to call_tool/call_llm for the duration of this block. Entries are
    consumed in order (so N calls to a tool replay the N recorded outputs); pass None to leave
    calls live."""
    token = _fixtures.set(_normalize_bundle(bundle) if bundle else None)
    try:
        yield
    finally:
        _fixtures.reset(token)


def _pop_fixture(kind: str, key: str, args: Any = None) -> dict | None:
    """Consume the next recorded entry for a tool/model: an args-match if `args` is given and one
    exists, else the next in recorded order. Returns None if not replaying / nothing recorded."""
    store = _fixtures.get()
    if not store:
        return None
    queue = store.get(kind, {}).get(key)
    if not queue:
        return None
    if args is not None:
        for i, e in enumerate(queue):
            if e.get("args") == args:
                return queue.pop(i)
    return queue.pop(0)


def fixture(kind: str, name: str) -> Any:
    """Peek the next recorded output for a tool/llm by name (non-consuming), or None."""
    store = _fixtures.get()
    if not store:
        return None
    queue = store.get(kind, {}).get(name)
    return queue[0].get("output") if queue else None


def call_tool(name: str, fn: Callable[[], Any], *, args: Any = None, agent: str | None = None) -> Any:
    """Execute a tool inside a TOOL span — but in hermetic replay serve the recorded call and
    never call `fn`. Pass `args` to match a specific recorded call; without it, recorded calls are
    served in order. If the recorded call ERRORED in production, the replayed span is marked ERROR
    and a `ToolError` is raised — so the agent's own error handling runs and the gate sees the same
    failure (faithful error-condition replay). Errors propagate the same way under `--live`."""
    with tool(name, agent=agent) as span:
        if args is not None:
            set_io(span, input=args)
        entry = _pop_fixture("tools", name, args)
        if entry is None:
            out = fn()
            set_io(span, output=out)
            return out
        span.set_attribute("tracely.replay.fixture", True)
        if entry.get("output") is not None:
            set_io(span, output=entry.get("output"))
        if entry.get("error"):
            error(span, str(entry["error"]))
            raise ToolError(str(entry["error"]))
        return entry.get("output")


def call_llm(
    model: str, fn: Callable[[], Any], *, input: Any = None,
    usage: tuple[int, int] | None = None, agent: str | None = None,
) -> Any:
    """Execute an LLM call inside a GENERATION span — but in hermetic replay serve the recorded
    completion (in recorded order) and never call `fn`. A recorded error is reproduced on the span
    and raised as a `ToolError`. Pass `usage=(input_tokens, output_tokens)` to report token usage
    (feeds the gate's cost/token soft gate)."""
    with llm(model, agent=agent) as span:
        if input is not None:
            set_io(span, input=input)
        if usage is not None:
            set_usage(span, input_tokens=usage[0], output_tokens=usage[1])
        entry = _pop_fixture("llm", model)
        if entry is None:
            out = fn()
            set_io(span, output=out)
            return out
        span.set_attribute("tracely.replay.fixture", True)
        if entry.get("output") is not None:
            set_io(span, output=entry.get("output"))
        if entry.get("error"):
            error(span, str(entry["error"]))
            raise ToolError(str(entry["error"]))
        return entry.get("output")
