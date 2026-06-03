"""OTLP traces -> Tracely `events` rows.

Ports the load-bearing parts of Langfuse's OtelIngestionProcessor / ObservationTypeMapper
(see design 07 + 12 + 92 facts) into Python: span -> event, type classification across
langfuse.* / OpenInference / GenAI gen_ai.* conventions, plus Tracely's first-class
`tracely.*` semantic attributes. JSON+protobuf OTLP supported by the caller.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue

GENERATION = "GENERATION"
AGENT = "AGENT"
TOOL = "TOOL"
CHAIN = "CHAIN"
RETRIEVER = "RETRIEVER"
EMBEDDING = "EMBEDDING"
GUARDRAIL = "GUARDRAIL"
SPAN = "SPAN"
_KNOWN_TYPES = {GENERATION, AGENT, TOOL, CHAIN, RETRIEVER, EMBEDDING, GUARDRAIL, SPAN, "EVENT", "EVALUATOR"}

_GENAI_GEN_OPS = {"chat", "completion", "text_completion", "generate_content", "generate"}


def _any_value(v: AnyValue) -> Any:
    kind = v.WhichOneof("value")
    if kind == "string_value":
        return v.string_value
    if kind == "bool_value":
        return v.bool_value
    if kind == "int_value":
        return v.int_value
    if kind == "double_value":
        return v.double_value
    if kind == "bytes_value":
        return v.bytes_value.hex()
    if kind == "array_value":
        return [_any_value(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _any_value(kv.value) for kv in v.kvlist_value.values}
    return None


def _attrs(kvs: list[KeyValue]) -> dict[str, Any]:
    return {kv.key: _any_value(kv.value) for kv in kvs}


def _ns_to_dt(ns: int) -> datetime | None:
    if not ns:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _first(attrs: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in attrs and attrs[k] not in (None, ""):
            return attrs[k]
    return None


def _truthy(v: Any) -> bool:
    return str(v).lower() in ("1", "true", "yes")


def map_observation_type(attrs: dict[str, Any]) -> str:
    explicit = _first(attrs, ["tracely.observation.type", "langfuse.observation.type"])
    if explicit and str(explicit).upper() in _KNOWN_TYPES:
        return str(explicit).upper()

    oi = attrs.get("openinference.span.kind")
    if oi:
        m = {"LLM": GENERATION, "TOOL": TOOL, "AGENT": AGENT, "CHAIN": CHAIN,
             "RETRIEVER": RETRIEVER, "EMBEDDING": EMBEDDING, "GUARDRAIL": GUARDRAIL}
        if str(oi).upper() in m:
            return m[str(oi).upper()]

    op = attrs.get("gen_ai.operation.name")
    if op:
        op = str(op).lower()
        if op in _GENAI_GEN_OPS:
            return GENERATION
        if op == "execute_tool":
            return TOOL
        if op in ("invoke_agent", "create_agent"):
            return AGENT
        if op in ("embeddings", "embedding"):
            return EMBEDDING

    if _first(attrs, ["gen_ai.tool.name", "tool.name"]):
        return TOOL
    if _first(attrs, ["gen_ai.request.model", "gen_ai.response.model", "llm.model_name"]):
        return GENERATION
    return SPAN


def _usage(attrs: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    pairs = [
        ("input", ["gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt"]),
        ("output", ["gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens", "llm.token_count.completion"]),
        ("total", ["gen_ai.usage.total_tokens", "llm.token_count.total"]),
    ]
    for name, keys in pairs:
        v = _first(attrs, keys)
        if v is not None:
            try:
                out[name] = int(v)
            except (TypeError, ValueError):
                pass
    return out


def _model_parameters(attrs: dict[str, Any]) -> str:
    params = {}
    for k in ("gen_ai.request.temperature", "gen_ai.request.max_tokens", "gen_ai.request.top_p"):
        if k in attrs:
            params[k.rsplit(".", 1)[-1]] = attrs[k]
    return json.dumps(params) if params else ""


def _map_span(resource_attrs: dict[str, Any], scope_name: str, scope_version: str,
              span: Any, project_id: str) -> dict[str, Any]:
    a = {**resource_attrs, **_attrs(list(span.attributes))}
    trace_id = span.trace_id.hex()
    span_id = span.span_id.hex()
    parent_span_id = span.parent_span_id.hex() if span.parent_span_id else ""

    level = "DEFAULT"
    status_message = ""
    if span.status.code == 2:  # ERROR
        level = "ERROR"
        status_message = span.status.message or ""

    otype = map_observation_type(a)
    agent_run_id = str(_first(a, ["tracely.agent.run_id", "tracely.run.id"]) or trace_id)

    return {
        "project_id": project_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "start_time": _ns_to_dt(span.start_time_unix_nano),
        "end_time": _ns_to_dt(span.end_time_unix_nano),
        "name": span.name or "",
        "type": otype,
        "environment": str(_first(a, ["deployment.environment", "langfuse.environment"]) or "default"),
        "env": str(_first(a, ["tracely.env"]) or "prod"),
        "version": str(_first(a, ["tracely.version", "service.version"]) or ""),
        "level": level,
        "status_message": status_message,
        "is_app_root": parent_span_id == "" or _truthy(_first(a, ["tracely.is_app_root", "langfuse.internal.as_root"]) or ""),
        "trace_name": str(_first(a, ["tracely.trace.name"]) or ""),
        "user_id": str(_first(a, ["tracely.user.id", "user.id", "langfuse.user.id"]) or ""),
        "session_id": str(_first(a, ["session.id", "tracely.session.id", "langfuse.session.id"]) or ""),
        # tracely first-class semantic columns (agent_slug/agent_version_ref are resolved
        # to registry UUIDs in the worker; agent_id/agent_version_id columns filled there)
        "agent_slug": str(_first(a, ["tracely.agent.id", "langfuse.agent.id"]) or ""),
        "agent_version_ref": str(_first(a, ["tracely.agent.version", "tracely.agent.version_id"]) or ""),
        "agent_run_id": agent_run_id,
        "conversation_id": str(_first(a, ["tracely.conversation.id", "session.id"]) or ""),
        "turn_id": str(_first(a, ["tracely.turn.id"]) or ""),
        "turn_index": int(_first(a, ["tracely.turn.index"]) or 0),
        "step_id": str(_first(a, ["tracely.step.id", "langgraph_step"]) or ""),
        "step_name": str(_first(a, ["tracely.step.name", "langgraph_node"]) or ""),
        "tool_call_id": str(_first(a, ["tracely.tool_call.id", "gen_ai.tool.call.id"]) or ""),
        "caller_agent_id": str(_first(a, ["tracely.handoff.caller_agent_id"]) or ""),
        "callee_agent_id": str(_first(a, ["tracely.handoff.callee_agent_id"]) or ""),
        "edge_type": str(_first(a, ["tracely.edge.type"]) or ""),
        # model / usage
        "model_id": str(_first(a, ["gen_ai.response.model", "gen_ai.request.model", "llm.model_name", "tracely.model"]) or ""),
        "model_parameters": _model_parameters(a),
        "usage_details": _usage(a),
        "tool_call_names": [str(_first(a, ["gen_ai.tool.name", "tool.name"]))] if otype == TOOL and _first(a, ["gen_ai.tool.name", "tool.name"]) else [],
        # io
        "input": _to_str(_first(a, ["tracely.input", "langfuse.observation.input", "input.value", "gen_ai.prompt", "input"])),
        "output": _to_str(_first(a, ["tracely.output", "langfuse.observation.output", "output.value", "gen_ai.completion", "output"])),
        # metadata: keep everything (lossless), stringified
        "metadata": {k: _to_str(v) or "" for k, v in a.items()},
        # instrumentation provenance
        "source": "otel",
        "service_name": str(resource_attrs.get("service.name", "")),
        "scope_name": scope_name,
        "telemetry_sdk_language": str(resource_attrs.get("telemetry.sdk.language", "")),
        "telemetry_sdk_name": str(resource_attrs.get("telemetry.sdk.name", "")),
        "telemetry_sdk_version": str(resource_attrs.get("telemetry.sdk.version", "")),
    }


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)


def events_from_request(req: ExportTraceServiceRequest, project_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for rs in req.resource_spans:
        resource_attrs = _attrs(list(rs.resource.attributes))
        for ss in rs.scope_spans:
            scope_name = ss.scope.name if ss.scope else ""
            scope_version = ss.scope.version if ss.scope else ""
            for span in ss.spans:
                events.append(_map_span(resource_attrs, scope_name, scope_version, span, project_id))
    return events


def parse_otlp_traces(raw: bytes, project_id: str) -> list[dict[str, Any]]:
    """Parse an OTLP/protobuf ExportTraceServiceRequest into Tracely event dicts."""
    req = ExportTraceServiceRequest()
    req.ParseFromString(raw)
    return events_from_request(req, project_id)


def parse_otlp_traces_json(raw: bytes, project_id: str) -> list[dict[str, Any]]:
    """Parse OTLP/JSON into Tracely event dicts."""
    from google.protobuf import json_format

    req = ExportTraceServiceRequest()
    json_format.Parse(raw.decode("utf-8"), req)
    return events_from_request(req, project_id)
