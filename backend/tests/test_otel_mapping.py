"""Unit tests for the OTLP -> events mapping (no infra needed)."""

from __future__ import annotations

import json

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, InstrumentationScope, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

from tracely.infrastructure.clickhouse.events_schema import EVENT_COLUMNS, to_rows
from tracely.otel import events_from_request
from tracely.otel.convention import _convention
from tracely.otel.types import map_observation_type


def _kv(k: str, v) -> KeyValue:
    if isinstance(v, bool):
        return KeyValue(key=k, value=AnyValue(bool_value=v))
    if isinstance(v, int):
        return KeyValue(key=k, value=AnyValue(int_value=v))
    return KeyValue(key=k, value=AnyValue(string_value=str(v)))


def _request() -> ExportTraceServiceRequest:
    span = Span(
        name="gpt-4o call",
        trace_id=b"\x01" * 16,
        span_id=b"\x02" * 8,
        start_time_unix_nano=1_000,
        end_time_unix_nano=2_000,
    )
    span.attributes.extend(
        [
            _kv("gen_ai.operation.name", "chat"),
            _kv("gen_ai.request.model", "gpt-4o"),
            _kv("gen_ai.usage.input_tokens", 812),
            _kv("gen_ai.usage.output_tokens", 96),
            _kv("tracely.agent.id", "planner"),
            _kv("session.id", "sess-1"),
        ]
    )
    ss = ScopeSpans(scope=InstrumentationScope(name="test"), spans=[span])
    rs = ResourceSpans(resource=Resource(attributes=[_kv("service.name", "svc")]), scope_spans=[ss])
    return ExportTraceServiceRequest(resource_spans=[rs])


def test_generation_mapping() -> None:
    events = events_from_request(_request(), "proj1")
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "GENERATION"
    assert e["model_id"] == "gpt-4o"
    assert e["agent_slug"] == "planner"
    assert e["conversation_id"] == "sess-1"
    assert e["project_id"] == "proj1"
    assert e["is_app_root"] is True  # no parent span
    assert e["usage_details"] == {"input": 812, "output": 96}


def test_type_classification() -> None:
    assert map_observation_type({"gen_ai.operation.name": "execute_tool"}) == "TOOL"
    assert map_observation_type({"openinference.span.kind": "RETRIEVER"}) == "RETRIEVER"
    assert map_observation_type({"tracely.observation.type": "AGENT"}) == "AGENT"
    assert map_observation_type({"foo": "bar"}) == "SPAN"


def test_to_rows_shape() -> None:
    rows = to_rows(events_from_request(_request(), "p"))
    assert len(rows) == 1
    assert len(rows[0]) == len(EVENT_COLUMNS)


# ── PRD 12: ingest real instrumentor output (R5/R15/§8) ─────────────────────


def _event(attrs: dict, *, status_code: int = 0, name: str = "span") -> dict:
    """Build one span from a flat {key: value} attr dict and return its mapped event."""
    span = Span(
        name=name,
        trace_id=b"\x01" * 16,
        span_id=b"\x02" * 8,
        start_time_unix_nano=1_000,
        end_time_unix_nano=2_000,
    )
    span.attributes.extend([_kv(k, v) for k, v in attrs.items()])
    if status_code:
        span.status.code = status_code
    ss = ScopeSpans(scope=InstrumentationScope(name="instr"), spans=[span])
    rs = ResourceSpans(resource=Resource(attributes=[_kv("service.name", "svc")]), scope_spans=[ss])
    return events_from_request(ExportTraceServiceRequest(resource_spans=[rs]), "p")[0]


def test_openinference_flattened_messages_and_usage() -> None:
    """Arize OpenInference emits flattened llm.* — model, usage, params, messages, tool calls."""
    e = _event(
        {
            "openinference.span.kind": "LLM",
            "llm.model_name": "gpt-4o",
            "llm.invocation_parameters": '{"temperature": 0.7, "max_tokens": 256, "model": "gpt-4o"}',
            "llm.token_count.prompt": 812,
            "llm.token_count.completion": 96,
            "llm.token_count.total": 908,
            "llm.input_messages.0.message.role": "user",
            "llm.input_messages.0.message.content": "What is the weather in Paris?",
            "llm.output_messages.0.message.role": "assistant",
            "llm.output_messages.0.message.content": "",
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": "call_1",
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "get_weather",
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments": '{"city": "Paris"}',
        }
    )
    assert e["type"] == "GENERATION"
    assert e["model_id"] == "gpt-4o"
    # total dropped because input+output present -> additive sum stays correct (no double count)
    assert e["usage_details"] == {"input": 812, "output": 96}
    params = json.loads(e["model_parameters"])
    assert params["temperature"] == 0.7 and params["max_tokens"] == 256
    msgs_in = json.loads(e["input"])
    assert msgs_in == [{"role": "user", "content": "What is the weather in Paris?"}]
    msgs_out = json.loads(e["output"])
    assert msgs_out[0]["role"] == "assistant"
    assert msgs_out[0]["tool_calls"][0]["function"]["name"] == "get_weather"
    assert e["tool_call_names"] == ["get_weather"]
    # message attrs must NOT leak into the lossless metadata map
    assert not any(k.startswith("llm.input_messages") for k in e["metadata"])
    assert "gen_ai.input.messages" not in e["metadata"]


def test_genai_structured_messages() -> None:
    """OTel GenAI structured messages arrive as a JSON-string attribute (the common OTLP shape)."""
    e = _event(
        {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": "claude-3-5-sonnet",
            "gen_ai.usage.input_tokens": 40,
            "gen_ai.usage.output_tokens": 12,
            "gen_ai.input.messages": json.dumps(
                [{"role": "user", "parts": [{"type": "text", "content": "hi"}]}]
            ),
            "gen_ai.output.messages": json.dumps([{"role": "assistant", "content": "hello!"}]),
        }
    )
    assert e["type"] == "GENERATION"
    assert e["model_id"] == "claude-3-5-sonnet"
    assert json.loads(e["input"]) == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    assert json.loads(e["output"]) == [{"role": "assistant", "content": "hello!"}]


def test_openllmetry_legacy_flattened_messages() -> None:
    """OpenLLMetry legacy flattened gen_ai.prompt.<i>.* / gen_ai.completion.<i>.* + tool calls."""
    e = _event(
        {
            "gen_ai.request.model": "gpt-5.4-mini",
            "gen_ai.prompt.0.role": "system",
            "gen_ai.prompt.0.content": "You are helpful.",
            "gen_ai.prompt.1.role": "user",
            "gen_ai.prompt.1.content": "Book a table.",
            "gen_ai.completion.0.role": "assistant",
            "gen_ai.completion.0.tool_calls.0.name": "book_table",
            "gen_ai.completion.0.tool_calls.0.arguments": '{"time": "7pm"}',
        }
    )
    msgs = json.loads(e["input"])
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert e["tool_call_names"] == ["book_table"]


def test_usage_total_fallback_only_when_components_absent() -> None:
    e = _event({"gen_ai.request.model": "m", "gen_ai.usage.total_tokens": 500})
    assert e["usage_details"] == {"total": 500}


def test_langgraph_node_metadata_maps_to_step() -> None:
    """OpenInference/LangChain packs LangGraph node info into a `metadata` JSON attr (R11)."""
    e = _event(
        {
            "openinference.span.kind": "CHAIN",
            "metadata": json.dumps(
                {"ls_integration": "langgraph", "langgraph_step": 1, "langgraph_node": "call"}
            ),
        },
        name="call",
    )
    assert e["type"] == "CHAIN"
    assert e["step_name"] == "call" and e["step_id"] == "1"


# ── PRD 12 P3: convention-version-aware ingestion (R14/D4) ──────────────────


def test_convention_detection() -> None:
    assert _convention({"gen_ai.input.messages": "[]"}) == "gen_ai/structured"
    assert _convention({"gen_ai.prompt.0.role": "user"}) == "gen_ai/legacy"
    assert _convention({"gen_ai.completion": "hi"}) == "gen_ai/legacy"
    assert _convention({"llm.model_name": "gpt-4o"}) == "openinference"
    assert _convention({"llm.input_messages.0.message.role": "user"}) == "openinference"
    assert _convention({"openinference.span.kind": "LLM"}) == "openinference"
    assert _convention({"gen_ai.request.model": "x"}) == "gen_ai/other"
    assert _convention({"tracely.observation.type": "AGENT"}) == "tracely/manual"
    assert _convention({"foo": "bar"}) == "unknown"


def test_convention_version_provenance_in_metadata() -> None:
    """schema_url (semconv version) + instrumentor scope version + detected shape are recorded."""
    span = Span(
        name="s",
        trace_id=b"\x01" * 16,
        span_id=b"\x02" * 8,
        start_time_unix_nano=1,
        end_time_unix_nano=2,
    )
    span.attributes.extend(
        [_kv("gen_ai.input.messages", "[]"), _kv("gen_ai.request.model", "gpt-4o")]
    )
    ss = ScopeSpans(
        scope=InstrumentationScope(name="openinference.instrumentation.openai", version="0.1.51"),
        spans=[span],
        schema_url="https://opentelemetry.io/schemas/1.27.0",
    )
    rs = ResourceSpans(resource=Resource(attributes=[_kv("service.name", "svc")]), scope_spans=[ss])
    e = events_from_request(ExportTraceServiceRequest(resource_spans=[rs]), "p")[0]
    md = e["metadata"]
    assert md["tracely.otel.gen_ai_convention"] == "gen_ai/structured"
    assert md["tracely.otel.schema_url"] == "https://opentelemetry.io/schemas/1.27.0"
    assert md["tracely.otel.scope_version"] == "0.1.51"


def test_unknown_openinference_kind_falls_through_to_span() -> None:
    # not a model/tool span and an unrecognized kind -> SPAN (R15: no hard-coded enum)
    assert map_observation_type({"openinference.span.kind": "SOMETHING_NEW"}) == "SPAN"
    # but gen_ai.operation.name still wins over an unknown kind
    assert (
        map_observation_type(
            {"openinference.span.kind": "SOMETHING_NEW", "gen_ai.operation.name": "chat"}
        )
        == "GENERATION"
    )


def test_langchain_serialized_messages_normalized() -> None:
    """LangChain ChatModel spans arrive with lc-constructor messages under `input.value` and a
    `{generations:[[…]]}` envelope under `output.value`; both must reduce to canonical messages so the
    UI (and evals) see the same `[{role, content}]` shape every other provider produces."""
    gen_in = json.dumps({"messages": [[
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "SystemMessage"],
         "kwargs": {"content": "You are helpful.", "type": "system"}},
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "HumanMessage"],
         "kwargs": {"content": "hi", "type": "human"}},
    ]]})
    gen_out = json.dumps({"generations": [[{"text": "", "type": "ChatGeneration", "message": {
        "lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "AIMessage"],
        "kwargs": {"content": "", "additional_kwargs": {"tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]}}}}]],
        "llm_output": {"token_usage": {}}})
    span = Span(name="ChatOpenAI", trace_id=b"\x03" * 16, span_id=b"\x04" * 8,
                start_time_unix_nano=1_000, end_time_unix_nano=2_000)
    span.attributes.extend([
        _kv("gen_ai.operation.name", "chat"),
        _kv("input.value", gen_in),
        _kv("output.value", gen_out),
    ])
    ss = ScopeSpans(scope=InstrumentationScope(name="test"), spans=[span])
    rs = ResourceSpans(resource=Resource(attributes=[_kv("service.name", "svc")]), scope_spans=[ss])
    e = events_from_request(ExportTraceServiceRequest(resource_spans=[rs]), "p")[0]
    inp, out = json.loads(e["input"]), json.loads(e["output"])
    assert [m["role"] for m in inp] == ["system", "user"]
    assert inp[1]["content"] == "hi"
    assert out[0]["role"] == "assistant"
    assert out[0]["tool_calls"][0]["function"]["name"] == "lookup"


def test_langchain_messages_to_dict_and_node_updates() -> None:
    """LangGraph CHAIN nodes serialize via `messages_to_dict` ({type, data}) and node updates as
    [{update:{messages:[…]}}]; the unwrap maps roles (human→user, ai→assistant) and keeps tool ids."""
    from tracely.otel.messages import _decode_langchain

    chain = {"messages": [{"type": "ai", "data": {"content": "ok", "type": "ai"}}]}
    assert _decode_langchain(chain) == [{"role": "assistant", "content": "ok"}]

    upd = [{"graph": None, "update": {"messages": [
        {"type": "tool", "data": {"content": '{"k": 1}', "type": "tool", "tool_call_id": "c1", "name": "t"}}]}}]
    out = _decode_langchain(upd)
    assert out[0]["role"] == "tool" and out[0]["tool_call_id"] == "c1" and out[0]["name"] == "t"
