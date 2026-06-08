"""SDK automatic-tracing tests (PRD 12): trace() context + processor, @observe, init(instrument=).

These use a single in-memory exporter on the global provider (set once — OTel allows one global
provider per process). The real-instrumentor end-to-end test is skipped unless
`openinference-instrumentation-openai` + `openai` are installed (the `[openai]` extra)."""

from __future__ import annotations

import sys
import types

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import tracely_sdk as tracely


@pytest.fixture(scope="module")
def exporter() -> InMemorySpanExporter:
    tracely.init(env="prod", instrument=False)  # builds the global provider (once)
    exp = InMemorySpanExporter()
    tracely._provider.add_span_processor(SimpleSpanProcessor(exp))
    return exp


@pytest.fixture(autouse=True)
def _clear(exporter: InMemorySpanExporter):
    exporter.clear()
    yield
    exporter.clear()


def _attrs(exporter: InMemorySpanExporter, name: str) -> dict:
    return dict(next(s for s in exporter.get_finished_spans() if s.name == name).attributes)


# ── trace() + TracelyContextSpanProcessor (R9/R4) ───────────────────────────


def test_trace_stamps_context_onto_every_span(exporter: InMemorySpanExporter) -> None:
    tr = tracely._t()
    with tracely.trace(
        agent="planner",
        conversation="c1",
        turn=2,
        user="u_7",
        trace_name="demo",
        env="staging",
        tenant="acme",
    ):
        with tr.start_as_current_span("auto-ish-span"):  # a span our code didn't author
            pass
    a = _attrs(exporter, "auto-ish-span")
    assert a["tracely.agent.id"] == "planner"
    assert a["tracely.conversation.id"] == "c1" and a["session.id"] == "c1"
    assert a["tracely.turn.index"] == 2 and a["tracely.user.id"] == "u_7"
    assert a["tracely.trace.name"] == "demo" and a["tracely.env"] == "staging"
    assert a["tracely.metadata.tenant"] == "acme"


def test_env_default_outside_trace(exporter: InMemorySpanExporter) -> None:
    with tracely._t().start_as_current_span("bare"):
        pass
    a = _attrs(exporter, "bare")
    assert a["tracely.env"] == "prod"  # init() default, stamped by the processor
    assert "tracely.agent.id" not in a


def test_trace_decorator_and_nested_merge(exporter: InMemorySpanExporter) -> None:
    @tracely.trace(agent="outer", conversation="C")
    def handler() -> None:
        with tracely.trace(turn=5):  # inherits agent/conversation, adds turn
            with tracely._t().start_as_current_span("inner"):
                pass

    handler()
    a = _attrs(exporter, "inner")
    assert a["tracely.agent.id"] == "outer" and a["tracely.conversation.id"] == "C"
    assert a["tracely.turn.index"] == 5


# ── @observe (R8) ────────────────────────────────────────────────────────────


def test_observe_tree_types_io(exporter: InMemorySpanExporter) -> None:
    @tracely.observe(as_type="generation")
    def call_llm(prompt: str) -> dict:
        return {"role": "assistant", "content": "ok"}

    @tracely.observe(as_type="tool")
    def get_weather(city: str) -> dict:
        return {"tempF": 64}

    @tracely.observe(as_type="agent")
    def planner(goal: str) -> str:
        call_llm("a")
        get_weather("Paris")
        call_llm("b")
        return "done"

    with tracely.trace(agent="planner", conversation="conv-9"):
        planner("plan a trip")

    spans = exporter.get_finished_spans()
    assert sorted(s.name for s in spans) == ["call_llm", "call_llm", "get_weather", "planner"]
    root = next(s for s in spans if s.name == "planner")
    children = [s for s in spans if s.parent and s.parent.span_id == root.context.span_id]
    assert len(children) == 3  # 4-span tree: agent -> 2 generations + tool
    types = {s.name: dict(s.attributes).get("tracely.observation.type") for s in spans}
    assert types["planner"] == "AGENT" and types["get_weather"] == "TOOL"
    ra = dict(root.attributes)
    assert "plan a trip" in ra["tracely.input"] and ra["tracely.output"] == "done"
    for s in spans:  # trace() context on every span
        assert dict(s.attributes)["tracely.agent.id"] == "planner"


def test_observe_exception_marks_error(exporter: InMemorySpanExporter) -> None:
    @tracely.observe()
    def boom() -> None:
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        boom()
    span = next(s for s in exporter.get_finished_spans() if s.name == "boom")
    assert span.status.status_code.name == "ERROR"


async def test_observe_async(exporter: InMemorySpanExporter) -> None:
    @tracely.observe(as_type="generation")
    async def acall() -> str:
        return "async-out"

    @tracely.observe(as_type="agent")
    async def aagent() -> str:
        return await acall()

    assert await aagent() == "async-out"
    names = {s.name for s in exporter.get_finished_spans()}
    assert {"aagent", "acall"} <= names


# ── threads (R10) ────────────────────────────────────────────────────────────


def test_run_in_thread_copies_context(exporter: InMemorySpanExporter) -> None:
    def work() -> int:
        with tracely._t().start_as_current_span("threaded"):
            return 7

    with tracely.trace(agent="T"):
        with tracely._t().start_as_current_span("parent") as parent:
            pid = parent.context.span_id
            th = tracely.run_in_thread(work)
            th.join()
            assert th.result == 7 and th.exc is None
    threaded = next(s for s in exporter.get_finished_spans() if s.name == "threaded")
    assert threaded.parent and threaded.parent.span_id == pid
    assert dict(threaded.attributes)["tracely.agent.id"] == "T"


# ── init(instrument=) activation + guards (R1/R7) ───────────────────────────


def test_instrument_false_activates_nothing(exporter: InMemorySpanExporter) -> None:
    before = set(tracely._instrumented)
    tracely._activate_instrumentors(False)
    assert tracely._instrumented == before


def test_fake_instrumentor_activation_is_idempotent(exporter: InMemorySpanExporter) -> None:
    calls: list = []
    fake = types.ModuleType("fakeinst_test")

    class FakeInstrumentor:
        def instrument(self, tracer_provider=None):
            calls.append(tracer_provider)

    fake.FakeInstrumentor = FakeInstrumentor
    sys.modules["fakeinst_test"] = fake
    # first candidate is unimportable -> falls through to the second (first-importable wins)
    tracely._INSTRUMENTORS["fakeprov_test"] = [
        ("nope.nope", "X"),
        ("fakeinst_test", "FakeInstrumentor"),
    ]
    try:
        assert tracely._activate_one("fakeprov_test") is True
        assert calls == [tracely._provider]  # activated against Tracely's provider
        assert tracely._activate_one("fakeprov_test") is True  # idempotent: no second call
        assert calls == [tracely._provider]
    finally:
        tracely._INSTRUMENTORS.pop("fakeprov_test", None)
        tracely._instrumented.discard("fakeprov_test")
        sys.modules.pop("fakeinst_test", None)


def test_litellm_excluded_from_auto() -> None:
    assert "litellm" not in tracely._AUTO_PROVIDERS  # opt-in only (double-instrument guard, R7)


def test_resolve_targets_langchain_dedup_guard(monkeypatch) -> None:
    """In "auto", when the LangChain instrumentor is installed it owns LLM spans → provider
    instrumentors are dropped to avoid duplicate spans (R7). Explicit lists are never suppressed."""
    monkeypatch.setattr(tracely, "_module_available", lambda name: True)  # all SDKs "installed"
    monkeypatch.setattr(tracely, "_has_instrumentor", lambda name: name == "langchain")
    assert tracely._resolve_targets("auto") == ["langchain"]  # all providers dropped
    # without the langchain instrumentor, all auto providers are kept
    monkeypatch.setattr(tracely, "_has_instrumentor", lambda name: False)
    assert tracely._resolve_targets("auto") == list(tracely._AUTO_PROVIDERS)
    # explicit list is honored as-is (override) + False/None disables
    assert tracely._resolve_targets(["openai", "langchain"]) == ["openai", "langchain"]
    assert tracely._resolve_targets(False) == [] and tracely._resolve_targets(None) == []


def test_provider_map_and_aliases() -> None:
    """The providers/harnesses the examples target are in the instrumentor map; aliases normalize."""
    for name in (
        "openai",
        "anthropic",
        "google",
        "mistral",
        "bedrock",
        "groq",
        "langchain",
        "llama-index",
        "crewai",
        "openai-agents",
        "google-adk",
        "claude-agent-sdk",
    ):
        assert name in tracely._INSTRUMENTORS, name
    assert tracely._ALIASES["gemini"] == "google"
    assert tracely._ALIASES["llama_index"] == "llama-index"
    assert tracely._ALIASES["adk"] == "google-adk"
    assert tracely._ALIASES["claude_agent_sdk"] == "claude-agent-sdk"
    # provider keys (suppressed under the auto LangChain guard) exclude harnesses + agent SDKs
    assert "openai" in tracely._PROVIDER_KEYS
    assert (
        "langchain" not in tracely._PROVIDER_KEYS and "openai-agents" not in tracely._PROVIDER_KEYS
    )


def test_litellm_callback_wiring(monkeypatch) -> None:
    """init(instrument=["litellm"]) wires litellm.callbacks=["otel"] idempotently (R12)."""
    fake = types.ModuleType("litellm")
    fake.callbacks = []
    monkeypatch.setitem(sys.modules, "litellm", fake)
    monkeypatch.setattr(tracely, "_instrumented", set(tracely._instrumented) - {"litellm"})
    assert tracely._activate_litellm() is True
    assert fake.callbacks == ["otel"] and "litellm" in tracely._instrumented
    tracely._instrumented.discard("litellm")
    assert tracely._activate_litellm() is True  # re-run: no duplicate "otel"
    assert fake.callbacks == ["otel"]


# ── R13 drop-in wrapper (no global patching) ────────────────────────────────


def test_dropin_openai_no_global_patch(exporter: InMemorySpanExporter) -> None:
    # the drop-in needs only the OpenAI SDK — NOT the instrumentor (it's the non-patching path)
    pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    from tracely.otel import events_from_request
    from tracely_sdk.openai import OpenAI, wrap_openai

    resp = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-2024-08-06",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "hi there"},
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }
    client = OpenAI(
        api_key="sk-test",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=resp))
        ),
    )

    def dropin_spans():  # the wrapper emits via the manual llm() helper (scope "tracely-sdk"),
        return [
            s
            for s in exporter.get_finished_spans()  # isolating it from any global instrumentor
            if s.instrumentation_scope.name == "tracely-sdk"
        ]

    with tracely.trace(agent="dropin", conversation="conv-d"):
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    spans = dropin_spans()
    assert len(spans) == 1  # one span from the instance wrapper (no extra from global patching)
    ev = events_from_request(encode_spans(spans), "p")[0]
    assert ev["type"] == "GENERATION" and ev["usage_details"] == {"input": 11, "output": 3}
    assert ev["agent_slug"] == "dropin" and ev["output"] and "hi there" in ev["output"]

    exporter.clear()
    wrap_openai(client)  # idempotent — wrapping again must not double-span
    with tracely.trace(agent="dropin"):
        client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "again"}]
        )
    assert len(dropin_spans()) == 1


def test_dropin_anthropic_no_global_patch(exporter: InMemorySpanExporter) -> None:
    pytest.importorskip("anthropic")
    httpx = pytest.importorskip("httpx")
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    from tracely.otel import events_from_request
    from tracely_sdk.anthropic import Anthropic, wrap_anthropic

    resp = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet-20241022",
        "content": [{"type": "text", "text": "hello there"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 9, "output_tokens": 3},
    }
    client = Anthropic(
        api_key="sk-ant-test",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=resp))
        ),
    )

    def dropin_spans():
        return [
            s
            for s in exporter.get_finished_spans()
            if s.instrumentation_scope.name == "tracely-sdk"
        ]

    with tracely.trace(agent="dropin-ant", conversation="conv-a"):
        client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=64,
            messages=[{"role": "user", "content": "hi"}],
        )
    spans = dropin_spans()
    assert len(spans) == 1  # one span from the instance wrapper, no global patch
    ev = events_from_request(encode_spans(spans), "p")[0]
    assert ev["type"] == "GENERATION" and ev["usage_details"] == {"input": 9, "output": 3}
    assert ev["agent_slug"] == "dropin-ant" and ev["output"] and "hello there" in ev["output"]

    exporter.clear()
    wrap_anthropic(client)  # idempotent
    with tracely.trace(agent="dropin-ant"):
        client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=64,
            messages=[{"role": "user", "content": "again"}],
        )
    assert len(dropin_spans()) == 1


# ── R11 LangChain integration (needs the [langchain] extra) ─────────────────


def test_langchain_invoke_traced(exporter: InMemorySpanExporter) -> None:
    pytest.importorskip("openinference.instrumentation.langchain")
    fake_models = pytest.importorskip("langchain_core.language_models.fake_chat_models")

    tracely.init(env="prod", instrument=["langchain"])
    assert "langchain" in tracely._instrumented
    model = fake_models.FakeListChatModel(responses=["hello from langchain"])
    with tracely.trace(agent="lc-agent", conversation="conv-lc"):
        model.invoke("hi there")
    gens = [
        s
        for s in exporter.get_finished_spans()
        if dict(s.attributes).get("openinference.span.kind") == "LLM"
    ]
    assert gens, "expected a LangChain LLM span"
    assert dict(gens[0].attributes)["tracely.agent.id"] == "lc-agent"


# ── real instrumentor end-to-end (R1/R2/R5) — needs the [openai] extra ──────


def test_openai_instrumentor_through_backend_mapping(exporter: InMemorySpanExporter) -> None:
    pytest.importorskip("openinference.instrumentation.openai")
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("tracely.otel")
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans

    from tracely.otel import events_from_request

    tracely.init(env="prod", instrument=["openai"])
    assert "openai" in tracely._instrumented

    resp = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-2024-08-06",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50},
    }
    client = openai.OpenAI(
        api_key="sk-test",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=resp))
        ),
    )
    with tracely.trace(agent="weather-agent", conversation="conv-42", user="u_7"):
        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "weather in Paris?"}],
        )

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    ev = events_from_request(encode_spans(spans), "p")[0]
    assert ev["type"] == "GENERATION"
    assert ev["model_id"] in ("gpt-4o-2024-08-06", "gpt-4o")
    assert ev["usage_details"] == {"input": 42, "output": 8}  # total dropped (no double count)
    assert ev["agent_slug"] == "weather-agent" and ev["conversation_id"] == "conv-42"
    assert ev["tool_call_names"] == ["get_weather"]
    assert ev["input"] and "Paris" in ev["input"]
