"""Tracely SDK — automatic + manual tracing, exported to Tracely over OTLP.

Automatic (the default path — zero span code):

    import tracely_sdk as tracely
    tracely.init(env="prod")                       # activates OpenAI/Anthropic/… instrumentors

    with tracely.trace(agent="planner", conversation="conv-1", user="u_7"):
        OpenAI().chat.completions.create(model="gpt-4o", messages=[...])   # traced, no span code

    @tracely.observe(as_type="agent")              # function-level spans, auto-nested
    def plan(goal): ...

Manual (the escape hatch — full control):

    with tracely.agent("planner", version="v1") as a:
        with tracely.llm("gpt-4o") as g:
            tracely.set_io(g, input=prompt, output=completion)
            tracely.set_usage(g, input_tokens=812, output_tokens=96)
    tracely.flush()

Emits standard gen_ai.* / OpenInference-compatible attributes plus Tracely's first-class
`tracely.*` hints (agent id, version, run, conversation, turn, step, env) so the backend
populates the first-class span columns. Thin wrapper over the OpenTelemetry SDK: a custom
`SpanProcessor` stamps the active `tracely.trace()` context onto every span — including the
zero-touch provider spans created by the auto-instrumentors, which know nothing about Tracely.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from typing import Any, Callable, Iterator

from opentelemetry import trace as otel_trace  # `trace` is our public run-context API (below)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

__all__ = [
    "init",
    "trace",
    "observe",
    "agent",
    "turn",
    "step",
    "llm",
    "tool",
    "thinking",
    "retriever",
    "embedding",
    "guardrail",
    "chain",
    "set_io",
    "set_usage",
    "set_metadata",
    "set_agents",
    "error",
    "flush",
    "run_in_thread",
    "fixtures",
    "fixture",
    "call_llm",
    "call_tool",
    "ToolError",
]

log = logging.getLogger("tracely")


class ToolError(RuntimeError):
    """Raised by call_tool/call_llm in hermetic replay when the recorded call errored — so the
    agent's own error handling (try/except) runs exactly as it would against the live tool."""


_tracer: otel_trace.Tracer | None = None
_provider: TracerProvider | None = None
_env: str = "prod"
_initialized: bool = False
# the active tracely.trace() run context (agent/conversation/turn/user/trace_name/env/metadata),
# stamped onto every span by TracelyContextSpanProcessor — including auto-instrumentor spans.
_run_ctx: ContextVar[dict | None] = ContextVar("tracely_run_ctx", default=None)
# recorded tool/LLM outputs for hermetic replay; set by `with fixtures(bundle): ...`
_fixtures: ContextVar[dict | None] = ContextVar("tracely_fixtures", default=None)


class TracelyContextSpanProcessor(SpanProcessor):
    """The linchpin (PRD §6, R4). Auto-instrumentor spans are created by *their* code and know
    nothing about Tracely — so on every span's `on_start` we read the active `tracely.trace()`
    context (a contextvar) and stamp `tracely.*` hints onto the span. That's how zero-touch
    provider spans inherit the run's agent/conversation/turn/user/env without the instrumentor
    knowing Tracely exists. Manual spans set the same attributes after start, so they win on
    conflict; `tracely.env` is owned here (run-ctx value, else the init() default)."""

    def on_start(self, span: Span, parent_context: Any = None) -> None:  # noqa: ARG002
        ctx = _run_ctx.get()
        env = (ctx or {}).get("env") or _env
        if env:
            span.set_attribute("tracely.env", str(env))
        if not ctx:
            return
        if ctx.get("agent"):
            span.set_attribute("tracely.agent.id", str(ctx["agent"]))
        if ctx.get("conversation"):
            span.set_attribute("tracely.conversation.id", str(ctx["conversation"]))
            span.set_attribute("session.id", str(ctx["conversation"]))
        if ctx.get("turn") is not None:
            span.set_attribute("tracely.turn.index", int(ctx["turn"]))
        if ctx.get("user"):
            span.set_attribute("tracely.user.id", str(ctx["user"]))
        if ctx.get("trace_name"):
            span.set_attribute("tracely.trace.name", str(ctx["trace_name"]))
        for k, v in (ctx.get("metadata") or {}).items():
            if v is not None:
                span.set_attribute(
                    f"tracely.metadata.{k}",
                    v if isinstance(v, (str, int, float, bool)) else json.dumps(v, default=str),
                )
        # Conversation agent catalog (declared by the user) — stamped as one JSON attribute. The
        # backend extracts it per conversation (and strips it before ClickHouse) for the Agents
        # panel + @LIST_AGENT. Typically set once on the first turn; the redundancy is harmless.
        agents = ctx.get("agents")
        if agents:
            span.set_attribute("tracely.agents", json.dumps(agents, default=str))

    def on_end(self, span: Any) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: ARG002
        return True


# ── redaction (PII / sensitive content) ──────────────────────────────────────
# Scrub on the EXPORT path: every span — manual or auto-instrumentor — passes through the exporter,
# so this is the one place that covers prompts/completions/tool args captured by zero-touch
# instrumentors (which never call set_io). Off by default; opt in via init(redact=...).

# Conservative built-in patterns for init(redact=True). Deliberately high-precision (few false
# positives) rather than exhaustive — pass your own patterns/callable for stricter policies.
_DEFAULT_PII_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b(?:\d[ -]?){13,16}\b"),  # credit-card-shaped digit run
    re.compile(r"\b(?:\+?\d{1,2}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"),  # phone
]

_REDACTED = "[REDACTED]"


def _build_redactor(
    redact: bool | list[str] | Callable[[str, str], str] | None,
) -> Callable[[str, str], str] | None:
    """Resolve the `redact` argument into a `(attr_key, value) -> value` function, or None (off)."""
    if not redact:
        return None
    if callable(redact):
        return redact
    patterns = _DEFAULT_PII_PATTERNS if redact is True else [re.compile(p) for p in redact]

    def _scrub(_key: str, value: str) -> str:
        out = value
        for pat in patterns:
            out = pat.sub(_REDACTED, out)
        return out

    return _scrub


def _scrub_mapping(attrs: Any, redactor: Callable[[str, str], str]) -> None:
    """Apply `redactor` to every string (or string-sequence) value in a span/event attribute map,
    in place. Best-effort: a read-only/immutable map is silently skipped (never crash export)."""
    if not attrs:
        return
    for k, v in list(attrs.items()):
        try:
            if isinstance(v, str):
                nv = redactor(k, v)
                if nv != v:
                    attrs[k] = nv
            elif isinstance(v, (list, tuple)) and v and all(isinstance(x, str) for x in v):
                nv_list = [redactor(k, x) for x in v]
                if nv_list != list(v):
                    attrs[k] = nv_list
        except Exception:  # noqa: BLE001 — redaction must never break the export path
            continue


class _RedactingSpanExporter:
    """Decorates the OTLP exporter: scrubs span + event attributes through `redactor` just before
    handing spans to the wrapped exporter. Implements the SpanExporter duck-type (export/shutdown/
    force_flush) so BatchSpanProcessor treats it as the exporter."""

    def __init__(self, inner: Any, redactor: Callable[[str, str], str]) -> None:
        self._inner = inner
        self._redactor = redactor

    def export(self, spans: Any) -> Any:
        for span in spans:
            _scrub_mapping(getattr(span, "_attributes", None), self._redactor)
            for ev in getattr(span, "events", None) or ():
                _scrub_mapping(getattr(ev, "attributes", None), self._redactor)
        return self._inner.export(spans)

    def shutdown(self) -> Any:
        return self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)


def init(
    endpoint: str = "http://localhost:8000",
    api_key: str = "tracely_dev_key",
    service_name: str = "agent",
    env: str = "prod",
    instrument: str | list[str] | bool = "auto",
    redact: bool | list[str] | Callable[[str, str], str] | None = None,
) -> otel_trace.Tracer:
    """One-call setup (R1). Configures the OTel provider + OTLP exporter pointing at Tracely,
    registers the context-stamping processor, and activates the matching auto-instrumentors so your
    existing OpenAI/Anthropic/… code is traced with zero span code.

    `instrument`:
      - "auto" (default) — activate instrumentors for whatever provider SDKs are importable.
      - ["openai", "anthropic", "litellm", …] — activate exactly these.
      - False — set up export only; no auto-instrumentation (use the manual API / @observe).

    `redact` — scrub sensitive content from span/event attributes BEFORE they leave the process
    (applied at export, so it covers both manual `set_io`/metadata AND zero-touch auto-instrumentor
    prompts/completions/args). For regulated data this is the adoption gate; off by default.
      - None / False (default) — no redaction; payloads ship verbatim.
      - True — apply the built-in PII patterns (email, phone, SSN, credit-card-shaped digit runs).
      - ["regex", …] — replace every match of these patterns with `[REDACTED]`.
      - callable `(attr_key, value) -> value` — full control; return the scrubbed string.
    Set it on the FIRST `init()` call (the exporter is built once).

    Call once at startup; idempotent (provider built once; instrumentor activation de-duped, R7).
    Streaming token usage requires `stream_options={"include_usage": True}` on OpenAI calls (R3)."""
    global _tracer, _provider, _env, _initialized
    _env = env
    if not (_initialized and _provider is not None):
        resource = Resource.create(
            {"service.name": service_name, "telemetry.sdk.language": "python"}
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(TracelyContextSpanProcessor())  # stamps tracely.* on every span
        exporter: Any = OTLPSpanExporter(
            endpoint=f"{endpoint.rstrip('/')}/v1/traces",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        redactor = _build_redactor(redact)
        if redactor is not None:
            # Wrap the OTLP exporter so EVERY span (manual + auto-instrumentor) is scrubbed on the
            # way out — the one chokepoint all spans pass through.
            exporter = _RedactingSpanExporter(exporter, redactor)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)
        _provider = provider
        _tracer = otel_trace.get_tracer("tracely-sdk")
        _initialized = True
    _activate_instrumentors(instrument)  # idempotent; re-runnable to add providers later
    return _tracer  # type: ignore[return-value]


def _t() -> otel_trace.Tracer:
    if _tracer is None:
        init()
    assert _tracer is not None
    return _tracer


# ── auto-instrumentation (L1) ────────────────────────────────────────────────
# Adopt the OTel ecosystem (D1): per provider, try OpenInference (Arize) then OpenLLMetry
# (Traceloop) — the first importable wins, so a provider is instrumented by exactly ONE path (no
# double spans, R7). Backend ingests both gen_ai.* and llm.* independently (D3), so either works.

# canonical provider/harness -> ordered (module, class) instrumentor candidates; first importable
# activates. OpenInference (Arize) is primary; OpenLLMetry (Traceloop) secondary where it ships one.
_INSTRUMENTORS: dict[str, list[tuple[str, str]]] = {
    # frontier providers
    "openai": [
        ("openinference.instrumentation.openai", "OpenAIInstrumentor"),
        ("opentelemetry.instrumentation.openai_v2", "OpenAIInstrumentor"),
        ("opentelemetry.instrumentation.openai", "OpenAIInstrumentor"),
    ],
    "anthropic": [
        ("openinference.instrumentation.anthropic", "AnthropicInstrumentor"),
        ("opentelemetry.instrumentation.anthropic", "AnthropicInstrumentor"),
    ],
    "google": [
        ("openinference.instrumentation.google_genai", "GoogleGenAIInstrumentor"),
        ("opentelemetry.instrumentation.google_generativeai", "GoogleGenerativeAiInstrumentor"),
    ],
    "mistral": [("openinference.instrumentation.mistralai", "MistralAIInstrumentor")],
    "bedrock": [("openinference.instrumentation.bedrock", "BedrockInstrumentor")],
    "groq": [("openinference.instrumentation.groq", "GroqInstrumentor")],
    # harnesses (orchestration frameworks)
    "langchain": [  # also covers LangGraph (built on LangChain's callback system)
        ("openinference.instrumentation.langchain", "LangChainInstrumentor"),
        ("opentelemetry.instrumentation.langchain", "LangchainInstrumentor"),
    ],
    "llama-index": [("openinference.instrumentation.llama_index", "LlamaIndexInstrumentor")],
    "crewai": [("openinference.instrumentation.crewai", "CrewAIInstrumentor")],
    # first-party agent SDKs (each emits AGENT/TOOL/LLM spans via its OpenInference instrumentor)
    "openai-agents": [("openinference.instrumentation.openai_agents", "OpenAIAgentsInstrumentor")],
    "google-adk": [("openinference.instrumentation.google_adk", "GoogleADKInstrumentor")],
    "claude-agent-sdk": [
        ("openinference.instrumentation.claude_agent_sdk", "ClaudeAgentSDKInstrumentor")
    ],
}
# provider/harness keys that wrap an LLM provider directly (vs. harnesses that route through them) —
# used by the LangChain de-dup guard to know what to suppress under "auto".
_PROVIDER_KEYS = frozenset({"openai", "anthropic", "google", "mistral", "bedrock", "groq"})
# aliases normalized to a canonical key
_ALIASES = {
    "gemini": "google",
    "google-genai": "google",
    "googleai": "google",
    "genai": "google",
    "mistralai": "mistral",
    "llama_index": "llama-index",
    "llamaindex": "llama-index",
    "aws": "bedrock",
    "bedrock-runtime": "bedrock",
    "openai_agents": "openai-agents",
    "openai-agents-sdk": "openai-agents",
    "agents": "openai-agents",
    "adk": "google-adk",
    "google_adk": "google-adk",
    "claude-agent": "claude-agent-sdk",
    "claude_agent_sdk": "claude-agent-sdk",
}
# SDK import name used to detect a provider for instrument="auto". Only providers whose SDK presence
# strongly implies intent to trace them (litellm/bedrock are opt-in: a router / boto3 is too common).
_PROVIDER_SDK: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google.genai",
    "mistral": "mistralai",
    "langchain": "langchain_core",
}
_AUTO_PROVIDERS = ("openai", "anthropic", "google", "mistral", "langchain")
_instrumented: set[str] = set()


def _module_available(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _import_attr(module: str, attr: str) -> Any:
    import importlib

    try:
        return getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError):
        return None


def _activate_litellm() -> bool:
    """Route LiteLLM's 100+ providers through OTel via its `otel` callback (R12). LiteLLM is
    opt-in (not part of "auto") because instrumenting both LiteLLM and a provider SDK double-traces
    calls LiteLLM makes to that provider — disable the overlap with OTEL_PYTHON_DISABLED_INSTRUMENTATIONS (R7)."""
    import importlib

    try:
        litellm = importlib.import_module("litellm")
    except ImportError:
        log.warning('tracely: instrument=["litellm"] requested but litellm is not installed')
        return False
    cbs = list(getattr(litellm, "callbacks", None) or [])
    if "otel" not in cbs:
        cbs.append("otel")
    litellm.callbacks = cbs
    _instrumented.add("litellm")
    log.info("tracely: enabled litellm otel callback")
    return True


def _has_instrumentor(name: str) -> bool:
    """Is an instrumentor package for `name` importable (not just the provider SDK)?"""
    return any(_module_available(mod) for mod, _ in _INSTRUMENTORS.get(name, []))


def _activate_one(name: str) -> bool:
    name = _ALIASES.get(name, name)  # gemini -> google, etc.
    if name in _instrumented:
        return True  # idempotent — one path per provider (R7)
    if name == "litellm":
        return _activate_litellm()
    for module, cls in _INSTRUMENTORS.get(name, []):
        instr_cls = _import_attr(module, cls)
        if instr_cls is None:
            continue
        try:
            instr_cls().instrument(tracer_provider=_provider)
            _instrumented.add(name)
            log.info("tracely: instrumented %s via %s", name, module)
            return True
        except Exception as e:  # a broken/older instrumentor shouldn't crash startup
            log.warning("tracely: failed to instrument %s via %s: %s", name, module, e)
    if _module_available(_PROVIDER_SDK.get(name, name)):  # SDK present but instrumentor missing
        log.warning(
            'tracely: %s is installed but no instrumentor found — pip install "tracely-sdk[%s]"',
            name,
            name,
        )
    return False


def _resolve_targets(instrument: str | list[str] | bool) -> list[str]:
    """Which providers to activate. "auto"/True → installed SDKs (with the LangChain de-dup guard);
    a list → exactly those (honored as-is — the override); False/None → none."""
    if instrument in (False, None):
        return []
    if instrument in ("auto", True):
        targets = [p for p in _AUTO_PROVIDERS if _module_available(_PROVIDER_SDK[p])]
        # De-dup guard (R7): LangChain routes through the provider SDKs, so running the LangChain
        # instrumentor AND a provider instrumentor double-traces LangChain→provider calls (sibling
        # spans). In "auto", when the LangChain instrumentor is installed, it owns LLM spans — skip
        # the provider instrumentors. Override by passing an explicit list (honored as-is).
        if "langchain" in targets and _has_instrumentor("langchain"):
            dropped = [p for p in targets if p in _PROVIDER_KEYS]
            if dropped:
                log.warning(
                    "tracely: LangChain instrumentation active — skipping %s auto-instrumentation to "
                    "avoid duplicate spans. Pass instrument=%r to force both.",
                    dropped,
                    ["langchain", *dropped],
                )
                targets = [p for p in targets if p not in dropped]
        return targets
    if isinstance(instrument, str):
        return [instrument]
    return [str(x) for x in instrument]


def _activate_instrumentors(instrument: str | list[str] | bool) -> None:
    for name in _resolve_targets(instrument):
        _activate_one(name.lower())


# ── run context (L3) ─────────────────────────────────────────────────────────
# `tracely.trace(...)` sets the run-level tracely.* hints once; the span processor flows them onto
# every child span (auto or manual), replacing today's per-span agent=/conversation= plumbing (R9).


class _Trace:
    """The object returned by `tracely.trace(...)`. Usable three ways — as a context manager
    (`with tracely.trace(...):`), a sync decorator, or an async decorator. Each entry merges its
    fields over the enclosing run context (so nested traces inherit + override), and resets on
    exit. It sets context only — it does not open a span (an `@observe`/`agent()` span, or the
    auto-instrumentor's own span, becomes the root)."""

    __slots__ = ("_fields", "_token")

    def __init__(self, fields: dict[str, Any]):
        self._fields = {k: v for k, v in fields.items() if v not in (None, {})}
        self._token: Any = None

    def __enter__(self) -> dict[str, Any]:
        parent = _run_ctx.get() or {}
        merged = {**parent, **self._fields}
        merged["metadata"] = {**parent.get("metadata", {}), **self._fields.get("metadata", {})}
        self._token = _run_ctx.set(merged)
        return merged

    def __exit__(self, *exc: Any) -> bool:
        if self._token is not None:
            _run_ctx.reset(self._token)
            self._token = None
        return False

    def __call__(self, fn: Callable) -> Callable:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*a: Any, **k: Any) -> Any:
                with _Trace(self._fields):
                    return await fn(*a, **k)

            return awrapper

        @functools.wraps(fn)
        def wrapper(*a: Any, **k: Any) -> Any:
            with _Trace(self._fields):
                return fn(*a, **k)

        return wrapper


def trace(
    agent: str | None = None,
    *,
    conversation: str | None = None,
    turn: int | None = None,
    user: str | None = None,
    trace_name: str | None = None,
    env: str | None = None,
    agents: list[dict] | None = None,
    **metadata: Any,
) -> _Trace:
    """Open a run context: set `agent`/`conversation`/`turn`/`user`/`trace_name`/`env` (+ arbitrary
    `metadata`) once, and every span started inside — including zero-touch provider spans from the
    auto-instrumentors — inherits them via the context processor (R9/R4). Use as a context manager
    or a (sync/async) decorator. Nested `trace()`s merge over the enclosing one.

    `agents` declares the conversation's agent catalog — a list of
    `{name, description, tools: {tool_name: {name, description, parameters}}}` — surfaced in the
    Conversation Agents panel and usable in evaluation (`@LIST_AGENT`). Set it once on the first
    turn (or every turn; the backend keeps the latest per conversation)."""
    return _Trace(
        {
            "agent": agent,
            "conversation": conversation,
            "turn": turn,
            "user": user,
            "trace_name": trace_name,
            "env": env,
            "agents": agents,
            "metadata": {k: v for k, v in metadata.items()},
        }
    )


# ── @observe (L2) ────────────────────────────────────────────────────────────


def _capture_args(span: Span, func: Callable, a: tuple, k: dict) -> dict:
    """Bind call args to parameter names → `tracely.input` (best effort; drops self/cls). Returns the
    bound dict so the caller can reuse it (e.g. fixture arg-matching in hermetic replay)."""
    try:
        bound = inspect.signature(func).bind(*a, **k)
        bound.apply_defaults()
        args = dict(bound.arguments)
        args.pop("self", None)
        args.pop("cls", None)
    except (TypeError, ValueError):
        args = {"args": list(a), **({"kwargs": k} if k else {})}
    if args:
        set_io(span, input=args)
    return args


def _replay_observed_tool(span: Span, name: str, args: Any) -> tuple[bool, Any]:
    """The hermetic-replay bridge for `@observe(as_type="tool")` — the decorator twin of `call_tool`.

    In a `with fixtures(bundle):` block, serve the next recorded entry for this tool instead of
    running it: stamp `tracely.replay.fixture`, set the recorded output, and (if the production call
    errored) mark the span ERROR + raise `ToolError` so the agent's own error handling runs. Returns
    `(handled, output)` — `handled=False` means "no fixture active / none recorded for this tool",
    so the caller runs the real function (this is a strict no-op in production, where `_fixtures` is
    unset). This is what lets an auto-instrumented agent whose tools are merely `@observe`-decorated
    replay deterministically in CI, with no `call_tool` rewrite."""
    entry = _pop_fixture("tools", name, args)
    if entry is None:
        return False, None
    span.set_attribute("tracely.replay.fixture", True)
    if entry.get("output") is not None:
        set_io(span, output=entry.get("output"))
    if entry.get("error"):
        error(span, str(entry["error"]))
        raise ToolError(str(entry["error"]))
    return True, entry.get("output")


def observe(
    fn: Callable | None = None,
    *,
    name: str | None = None,
    as_type: str = "span",
    capture_input: bool = True,
    capture_output: bool = True,
) -> Callable:
    """Wrap any sync/async function as a span (R8): args→input, return→output, latency, and
    exceptions (→ level=ERROR) captured automatically; auto-nests via OTel context — no manual
    parent wiring. `as_type` (span | generation | agent | tool | chain | retriever | embedding |
    guardrail | …) becomes `tracely.observation.type`. Usable as `@observe` or `@observe(...)`."""

    def decorate(func: Callable) -> Callable:
        span_name = name or getattr(func, "__name__", "observed")
        otype = str(as_type).upper()

        @functools.wraps(func)
        def sync_wrapper(*a: Any, **k: Any) -> Any:
            with _t().start_as_current_span(span_name) as span:
                span.set_attribute("tracely.observation.type", otype)
                bound = _capture_args(span, func, a, k) if capture_input else None
                if otype == "TOOL":  # hermetic-replay bridge: serve a fixture instead of running
                    handled, replayed = _replay_observed_tool(span, span_name, bound)
                    if handled:
                        return replayed
                try:
                    out = func(*a, **k)
                except Exception as e:
                    error(span, str(e))
                    raise
                if capture_output and out is not None:
                    set_io(span, output=out)
                return out

        @functools.wraps(func)
        async def async_wrapper(*a: Any, **k: Any) -> Any:
            with _t().start_as_current_span(span_name) as span:
                span.set_attribute("tracely.observation.type", otype)
                bound = _capture_args(span, func, a, k) if capture_input else None
                if otype == "TOOL":  # hermetic-replay bridge: serve a fixture instead of running
                    handled, replayed = _replay_observed_tool(span, span_name, bound)
                    if handled:
                        return replayed
                try:
                    out = await func(*a, **k)
                except Exception as e:
                    error(span, str(e))
                    raise
                if capture_output and out is not None:
                    set_io(span, output=out)
                return out

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper

    return decorate(fn) if callable(fn) else decorate


# ── threads (R10) ────────────────────────────────────────────────────────────
# Auto-nesting is contextvar-based and in-process: a raw threading.Thread starts with a fresh,
# detached context, so spans it creates would NOT nest under the current span or see trace().


class _ContextThread(threading.Thread):
    def __init__(self, ctx: Any, fn: Callable, args: tuple, kwargs: dict):
        super().__init__()
        self._ctx, self._fn, self._args, self._kwargs = ctx, fn, args, kwargs
        self.result: Any = None
        self.exc: BaseException | None = None

    def run(self) -> None:
        try:
            self.result = self._ctx.run(self._fn, *self._args, **self._kwargs)
        except BaseException as e:  # surfaced to the caller via `.exc` after join()
            self.exc = e


def run_in_thread(fn: Callable, *args: Any, **kwargs: Any) -> _ContextThread:
    """Run `fn` in a new thread that inherits the current trace context, so spans it creates nest
    under the active span / `tracely.trace(...)` (R10). Returns the started Thread — `join()` it,
    then read `.result` (or `.exc`). For thread pools, wrap the callable with
    `contextvars.copy_context().run` per task the same way."""
    th = _ContextThread(copy_context(), fn, args, kwargs)
    th.start()
    return th


@contextmanager
def agent(
    slug: str,
    *,
    version: str | None = None,
    run_id: str | None = None,
    role: str | None = None,
    conversation: str | None = None,
    turn: int | None = None,
    user: str | None = None,
    trace_name: str | None = None,
    handoff_from: str | None = None,
    edge: str = "delegate",
) -> Iterator[Span]:
    """An agent run. `conversation` groups runs into a thread (a multi-turn session); `version`
    is auto-registered for the regression gate. On the run's root, set `user` (end-user id) and
    `trace_name` (a human label). For a sub-agent invoked by another, pass `handoff_from` (the
    caller's slug) to record the delegation edge (caller → this agent, `edge` = relationship)."""
    with _t().start_as_current_span(slug) as span:
        span.set_attribute("tracely.agent.id", slug)
        span.set_attribute("tracely.observation.type", "AGENT")
        # tracely.env is stamped by TracelyContextSpanProcessor (run-ctx value, else init() default)
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
        if user:
            span.set_attribute("tracely.user.id", user)
        if trace_name:
            span.set_attribute("tracely.trace.name", trace_name)
        if handoff_from:  # this agent was delegated to by `handoff_from` (a handoff edge)
            span.set_attribute("tracely.handoff.caller_agent_id", handoff_from)
            span.set_attribute("tracely.handoff.callee_agent_id", slug)
            span.set_attribute("tracely.edge.type", edge)
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
    tool_calls: list[str] | None = None,
) -> Iterator[Span]:
    """An LLM generation. Pass the sampling parameters (temperature/top_p/max_tokens/…) — they're
    recorded as standard `gen_ai.request.*` attributes and surfaced in the generation's Metadata.
    `metadata` attaches arbitrary key/values (e.g. prompt version, tenant). `tool_calls` records the
    tools the model REQUESTED this turn (even if a tool never runs — the silent-failure signal)."""
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
        if tool_calls:
            span.set_attribute("tracely.tool_calls", list(tool_calls))
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
def thinking(
    name: str = "thinking", *, agent: str | None = None, model: str | None = None
) -> Iterator[Span]:
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


@contextmanager
def retriever(name: str = "retrieve", *, agent: str | None = None) -> Iterator[Span]:
    """A retrieval step (vector / keyword / web search). Put the query in `set_io(input=...)` and
    the hits in `set_io(output=...)`; tag the store/index with `set_metadata`."""
    with _t().start_as_current_span(name) as span:
        span.set_attribute("tracely.observation.type", "RETRIEVER")
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        yield span


@contextmanager
def embedding(model: str, *, agent: str | None = None) -> Iterator[Span]:
    """An embedding call. Record token usage with `set_usage(input_tokens=...)`; the embedded text
    goes in `set_io(input=...)`."""
    with _t().start_as_current_span(model) as span:
        span.set_attribute("tracely.observation.type", "EMBEDDING")
        span.set_attribute("gen_ai.request.model", model)
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        yield span


@contextmanager
def guardrail(name: str = "guardrail", *, agent: str | None = None) -> Iterator[Span]:
    """A safety / policy check. Put the input in `set_io(input=...)` and the verdict in
    `set_io(output={"action": "allow" | "block", ...})`."""
    with _t().start_as_current_span(name) as span:
        span.set_attribute("tracely.observation.type", "GUARDRAIL")
        if agent:
            span.set_attribute("tracely.agent.id", agent)
        yield span


@contextmanager
def chain(name: str, *, agent: str | None = None) -> Iterator[Span]:
    """A grouping span (a named sub-pipeline, e.g. a RAG pipeline). Nest other spans inside it."""
    with _t().start_as_current_span(name) as span:
        span.set_attribute("tracely.observation.type", "CHAIN")
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


def set_agents(span: Span, agents: list[dict]) -> None:
    """Declare the conversation's agent catalog on a span: a list of
    `{name, description, tools: {tool_name: {name, description, parameters}}}`. Surfaced in the
    Conversation Agents panel and usable in evaluation (`@LIST_AGENT`). Prefer
    `tracely.trace(..., agents=[...])`, which flows it onto every span; use this to set it on one
    specific (e.g. the root) span."""
    if agents:
        span.set_attribute("tracely.agents", json.dumps(agents, default=str))


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
    provider = otel_trace.get_tracer_provider()
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


def call_tool(
    name: str, fn: Callable[[], Any], *, args: Any = None, agent: str | None = None
) -> Any:
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
    model: str,
    fn: Callable[[], Any],
    *,
    input: Any = None,
    usage: tuple[int, int] | None = None,
    agent: str | None = None,
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
