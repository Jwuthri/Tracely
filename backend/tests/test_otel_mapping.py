"""Unit tests for the OTLP -> events mapping (no infra needed)."""

from __future__ import annotations

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, InstrumentationScope, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

from tracely.events import EVENT_COLUMNS, to_rows
from tracely.otel.mapping import events_from_request, map_observation_type


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
    rs = ResourceSpans(
        resource=Resource(attributes=[_kv("service.name", "svc")]), scope_spans=[ss]
    )
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
