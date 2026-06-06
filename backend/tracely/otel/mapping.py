"""OTLP traces -> Tracely `events` rows.

Ports the load-bearing parts of Langfuse's OtelIngestionProcessor / ObservationTypeMapper
(see design 07 + 12 + 92 facts) into Python: span -> event, type classification across
langfuse.* / OpenInference / GenAI gen_ai.* conventions, plus Tracely's first-class
`tracely.*` semantic attributes. JSON+protobuf OTLP supported by the caller.

PRD 12 (automatic tracing) widened this to ingest **real instrumentor output** — the two
provider conventions are mapped *independently* (D3): OTel GenAI `gen_ai.*` and OpenInference
`llm.*`/`openinference.*`. Messages arrive in three shapes and are normalized to Tracely's
`{role, content:[blocks]}` here (R5):
  - structured  `gen_ai.input.messages` / `gen_ai.output.messages`  (JSON string or complex value)
  - OpenInference flattened  `llm.input_messages.<i>.message.{role,content,tool_calls.<j>...}`
  - OpenLLMetry legacy flattened  `gen_ai.{prompt,completion}.<i>.{role,content,tool_calls.<j>...}`
plus the single-value escape hatches (`tracely.*`, `input.value`, legacy `gen_ai.prompt`).
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
THINKING = "THINKING"
SPAN = "SPAN"
_KNOWN_TYPES = {
    GENERATION,
    AGENT,
    TOOL,
    CHAIN,
    RETRIEVER,
    EMBEDDING,
    GUARDRAIL,
    THINKING,
    SPAN,
    "EVENT",
    "EVALUATOR",
    "REASONING",
}

_GENAI_GEN_OPS = {"chat", "completion", "text_completion", "generate_content", "generate"}

# Single-value I/O keys (escape hatches + legacy string conventions). The richer structured /
# flattened message shapes are reassembled separately (see `_io_field`).
_IO_KEYS = frozenset(
    {
        "tracely.input",
        "langfuse.observation.input",
        "input.value",
        "gen_ai.prompt",
        "input",
        "tracely.output",
        "langfuse.observation.output",
        "output.value",
        "gen_ai.completion",
        "output",
    }
)
# Prefixes/keys of flattened-or-structured message attributes — excluded from the lossless
# metadata passthrough so we don't duplicate (often huge) message content into every row.
_MSG_PREFIXES = (
    "llm.input_messages.",
    "llm.output_messages.",
    "gen_ai.prompt.",
    "gen_ai.completion.",
)
_MSG_KEYS = frozenset({"gen_ai.input.messages", "gen_ai.output.messages"})


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
    """Observation type, derived defensively (R15): tracely.observation.type -> gen_ai.operation.name
    -> openinference.span.kind -> tool/model heuristics -> SPAN. OpenInference span-kind is NOT a
    hard-coded closed enum — unknown kinds fall through to the heuristics, ultimately SPAN."""
    explicit = _first(attrs, ["tracely.observation.type", "langfuse.observation.type"])
    if explicit and str(explicit).upper() in _KNOWN_TYPES:
        return str(explicit).upper()

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

    oi = attrs.get("openinference.span.kind")
    if oi:
        m = {
            "LLM": GENERATION,
            "TOOL": TOOL,
            "AGENT": AGENT,
            "CHAIN": CHAIN,
            "RETRIEVER": RETRIEVER,
            "EMBEDDING": EMBEDDING,
            "GUARDRAIL": GUARDRAIL,
        }
        if str(oi).upper() in m:  # known kind; unknown kinds intentionally fall through (R15)
            return m[str(oi).upper()]

    if _first(attrs, ["gen_ai.tool.name", "tool.name"]):
        return TOOL
    if _first(attrs, ["gen_ai.request.model", "gen_ai.response.model", "llm.model_name"]):
        return GENERATION
    return SPAN


def _usage(attrs: dict[str, Any]) -> dict[str, int]:
    """Additive token map. `usage_details` is summed leaf-wise downstream
    (`arraySum(mapValues(usage_details))` in reads/gate), so it must hold only *non-overlapping*
    counts: `input` + `output`. `total` is stored only as a fallback when neither component is
    present (else it would double-count). Reasoning/cache breakdowns are subsets of input/output
    (and provider-dependent — §13), so they stay out of this map and ride along in `metadata`."""
    out: dict[str, int] = {}
    inp = _first(
        attrs, ["gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt"]
    )
    outp = _first(
        attrs,
        [
            "gen_ai.usage.output_tokens",
            "gen_ai.usage.completion_tokens",
            "llm.token_count.completion",
        ],
    )
    total = _first(attrs, ["gen_ai.usage.total_tokens", "llm.token_count.total"])
    for name, v in (("input", inp), ("output", outp)):
        if v is not None:
            try:
                out[name] = int(v)
            except (TypeError, ValueError):
                pass
    if total is not None and "input" not in out and "output" not in out:
        try:
            out["total"] = int(total)
        except (TypeError, ValueError):
            pass
    return out


def _model_parameters(attrs: dict[str, Any]) -> str:
    """Sampling params as JSON. Merges OTel `gen_ai.request.*` with OpenInference's single-blob
    `llm.invocation_parameters` (JSON); scalar values only, to avoid dumping nested messages."""
    params: dict[str, Any] = {}
    for k in (
        "gen_ai.request.temperature",
        "gen_ai.request.max_tokens",
        "gen_ai.request.top_p",
        "gen_ai.request.frequency_penalty",
        "gen_ai.request.presence_penalty",
        "gen_ai.request.seed",
    ):
        if k in attrs:
            params[k.rsplit(".", 1)[-1]] = attrs[k]
    inv = _as_obj(attrs.get("llm.invocation_parameters"))
    if isinstance(inv, dict):
        for k, v in inv.items():
            if isinstance(v, (str, int, float, bool)):
                params.setdefault(str(k), v)
    return json.dumps(params) if params else ""


# ── message normalization ──────────────────────────────────────────────────
# Reassemble the three on-the-wire message shapes into Tracely's `{role, content:[blocks]}`.


def _as_obj(v: Any) -> Any:
    """A structured value may arrive already decoded (list/dict, from an OTLP complex AnyValue) or
    as a JSON string (the common case — OTLP attributes are usually primitives). Decode the string."""
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in ("{", "["):
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return v
    return v


def _normalize_content(raw: Any) -> Any:
    """A message body -> a plain string or a list of content blocks (`{type:'text', text}` …)."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, list):
        blocks: list[Any] = []
        for p in raw:
            if isinstance(p, str):
                blocks.append({"type": "text", "text": p})
            elif isinstance(p, dict):
                if isinstance(p.get("text"), str):
                    blocks.append({"type": "text", "text": p["text"]})
                elif isinstance(p.get("content"), str) and p.get("type", "text") in ("text", None):
                    # OTel structured part: {type:'text', content:'…'}
                    blocks.append({"type": "text", "text": p["content"]})
                else:
                    blocks.append(p)  # images / files / tool parts pass through
        return blocks
    return _to_str(raw) or ""


def _normalize_message(m: Any) -> dict[str, Any]:
    if not isinstance(m, dict):
        return {"role": "", "content": _to_str(m) or ""}
    role = m.get("role") or m.get("author") or ""
    raw = m.get("content")
    if raw is None and m.get("parts") is not None:  # OTel structured uses `parts`
        raw = m.get("parts")
    msg: dict[str, Any] = {"role": str(role), "content": _normalize_content(raw)}
    tcs = m.get("tool_calls")
    if isinstance(tcs, list) and tcs:
        msg["tool_calls"] = tcs
    return msg


def _structured_messages(val: Any) -> list[dict[str, Any]] | None:
    obj = _as_obj(val)
    if isinstance(obj, dict):
        obj = [obj]
    if not isinstance(obj, list):
        return None
    msgs = [_normalize_message(m) for m in obj]
    return msgs or None


def _indices(attrs: dict[str, Any], prefix: str) -> list[int]:
    """Sorted distinct integer indices `i` for keys shaped `{prefix}{i}.…`."""
    seen: set[int] = set()
    for k in attrs:
        if k.startswith(prefix):
            head = k[len(prefix) :].split(".", 1)[0]
            if head.isdigit():
                seen.add(int(head))
    return sorted(seen)


def _flat_tool_calls(attrs: dict[str, Any], prefix: str, wrapped: bool) -> list[dict[str, Any]]:
    """Reassemble flattened tool calls under `prefix` (`{prefix}{j}.…`). OpenInference wraps each
    in a `tool_call.` segment (wrapped=True): `…{j}.tool_call.function.{name,arguments}`,`…id`;
    OpenLLMetry does not (wrapped=False): `…{j}.{name,arguments,id}`."""
    out: list[dict[str, Any]] = []
    for j in _indices(attrs, prefix):
        b = f"{prefix}{j}." + ("tool_call." if wrapped else "")
        name = attrs.get(b + "function.name") if wrapped else attrs.get(b + "name")
        args = attrs.get(b + "function.arguments") if wrapped else attrs.get(b + "arguments")
        cid = attrs.get(b + "id")
        if name or args or cid:
            out.append(
                {
                    "id": str(cid or ""),
                    "type": "function",
                    "function": {
                        "name": str(name or ""),
                        "arguments": args if args is not None else "",
                    },
                }
            )
    return out


def _oi_contents(attrs: dict[str, Any], prefix: str) -> list[Any] | None:
    """OpenInference multi-part contents: `{prefix}{j}.message_content.{type,text,image.image.url}`."""
    blocks: list[Any] = []
    for j in _indices(attrs, prefix):
        b = f"{prefix}{j}.message_content."
        if attrs.get(b + "text") is not None:
            blocks.append({"type": "text", "text": attrs[b + "text"]})
        elif attrs.get(b + "image.image.url") is not None:
            blocks.append({"type": "image_url", "image_url": {"url": attrs[b + "image.image.url"]}})
        else:
            blocks.append({"type": str(attrs.get(b + "type", "text"))})
    return blocks or None


def _flat_messages(attrs: dict[str, Any], prefix: str, wrapped: bool) -> list[dict[str, Any]]:
    """Reassemble flattened messages under `prefix`. OpenInference wraps fields in `message.`
    (wrapped=True): `{prefix}{i}.message.{role,content}`; OpenLLMetry does not."""
    msgs: list[dict[str, Any]] = []
    for i in _indices(attrs, prefix):
        base = f"{prefix}{i}." + ("message." if wrapped else "")
        content = attrs.get(base + "content")
        if content is None and wrapped:
            content = _oi_contents(attrs, base + "contents.")
        msg: dict[str, Any] = {
            "role": str(attrs.get(base + "role", "") or ""),
            "content": _normalize_content(content),
        }
        tcs = _flat_tool_calls(attrs, base + "tool_calls.", wrapped)
        if tcs:
            msg["tool_calls"] = tcs
        msgs.append(msg)
    return msgs


def _io_messages(attrs: dict[str, Any], direction: str) -> list[dict[str, Any]] | None:
    """Normalized message list for `direction` ∈ {input, output}, trying each convention in turn:
    OTel structured -> OpenInference flattened -> OpenLLMetry legacy flattened."""
    structured = attrs.get(f"gen_ai.{direction}.messages")
    if structured is not None:
        msgs = _structured_messages(structured)
        if msgs:
            return msgs
    oi = _flat_messages(attrs, f"llm.{direction}_messages.", wrapped=True)
    if oi:
        return oi
    genai = _flat_messages(
        attrs, f"gen_ai.{'prompt' if direction == 'input' else 'completion'}.", wrapped=False
    )
    return genai or None


def _io_field(attrs: dict[str, Any], direction: str) -> str | None:
    """Resolve the `input`/`output` column. Manual `tracely.*` wins; then reassembled instrumentor
    messages; then the single-value string conventions."""
    manual = _first(attrs, [f"tracely.{direction}", f"langfuse.observation.{direction}"])
    if manual is not None:
        return _to_str(manual)
    msgs = _io_messages(attrs, direction)
    if msgs is not None:
        return _to_str(msgs)
    fallback = {
        "input": ["input.value", "gen_ai.prompt", "input"],
        "output": ["output.value", "gen_ai.completion", "output"],
    }[direction]
    return _to_str(_first(attrs, fallback))


def _tool_call_names(attrs: dict[str, Any], otype: str) -> list[str]:
    """Tools the model requested. Explicit `tracely.tool_calls` (array) wins; else the function
    names reassembled from output-message tool calls (any convention); else the tool name on a
    TOOL span."""
    tc = attrs.get("tracely.tool_calls")
    if isinstance(tc, list):
        return [str(x) for x in tc if x]
    names: list[str] = []
    for m in _io_messages(attrs, "output") or []:
        for call in m.get("tool_calls") or []:
            fn = (call.get("function") or {}).get("name") if isinstance(call, dict) else None
            if fn:
                names.append(str(fn))
    if names:
        return names
    name = _first(attrs, ["gen_ai.tool.name", "tool.name"])
    return [str(name)] if (otype == TOOL and name) else []


def _is_msg_attr(k: str) -> bool:
    return k in _IO_KEYS or k in _MSG_KEYS or k.startswith(_MSG_PREFIXES)


def _convention(attrs: dict[str, Any]) -> str:
    """The message convention a span used — recorded for drift tracking (R14/D4). `gen_ai.*` is
    experimental and migrating from legacy flat to structured; this labels which shape we ingested."""

    def pre(*prefixes: str) -> bool:
        return any(k.startswith(prefixes) for k in attrs)

    if "gen_ai.input.messages" in attrs or "gen_ai.output.messages" in attrs:
        return "gen_ai/structured"
    if pre("gen_ai.prompt", "gen_ai.completion"):  # bare legacy string or .<i> indexed
        return "gen_ai/legacy"
    if (
        pre("llm.input_messages.", "llm.output_messages.")
        or "llm.model_name" in attrs
        or "openinference.span.kind" in attrs
    ):
        return "openinference"
    if pre("gen_ai."):  # gen_ai.* present but no recognizable message shape
        return "gen_ai/other"
    if pre("tracely.input", "tracely.output", "tracely.observation.type"):
        return "tracely/manual"
    return "unknown"


def _completion_start(attrs: dict[str, Any]) -> datetime | None:
    """Time-to-first-token marker (R2/§8) — `tracely.completion_start_time` as epoch nanoseconds,
    if an instrumentor / the SDK emitted it. Best-effort; absent for most spans."""
    v = _first(attrs, ["tracely.completion_start_time"])
    if v is None:
        return None
    try:
        return _ns_to_dt(int(v))
    except (TypeError, ValueError):
        return None


def _map_span(
    resource_attrs: dict[str, Any],
    scope_name: str,
    scope_version: str,
    span: Any,
    project_id: str,
    schema_url: str = "",
) -> dict[str, Any]:
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
    # OpenInference/LangChain packs node info into a `metadata` JSON attr; promote LangGraph's
    # node name + step number to first-class step columns (R11; §13 LangGraph shape).
    lc_meta = _as_obj(a.get("metadata")) if "metadata" in a else None
    lc_meta = lc_meta if isinstance(lc_meta, dict) else {}

    return {
        "project_id": project_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "start_time": _ns_to_dt(span.start_time_unix_nano),
        "end_time": _ns_to_dt(span.end_time_unix_nano),
        "completion_start_time": _completion_start(a),
        "name": span.name or "",
        "type": otype,
        "environment": str(
            _first(a, ["deployment.environment", "langfuse.environment"]) or "default"
        ),
        "env": str(_first(a, ["tracely.env"]) or "prod"),
        "version": str(_first(a, ["tracely.version", "service.version"]) or ""),
        "level": level,
        "status_message": status_message,
        "is_app_root": parent_span_id == ""
        or _truthy(_first(a, ["tracely.is_app_root", "langfuse.internal.as_root"]) or ""),
        "trace_name": str(_first(a, ["tracely.trace.name"]) or ""),
        "user_id": str(_first(a, ["tracely.user.id", "user.id", "langfuse.user.id"]) or ""),
        "session_id": str(
            _first(a, ["session.id", "tracely.session.id", "langfuse.session.id"]) or ""
        ),
        "agent_slug": str(_first(a, ["tracely.agent.id", "langfuse.agent.id"]) or ""),
        "agent_version_ref": str(
            _first(a, ["tracely.agent.version", "tracely.agent.version_id"]) or ""
        ),
        "agent_run_id": agent_run_id,
        "conversation_id": str(_first(a, ["tracely.conversation.id", "session.id"]) or ""),
        "turn_id": str(_first(a, ["tracely.turn.id"]) or ""),
        "turn_index": int(_first(a, ["tracely.turn.index"]) or 0),
        "step_id": str(
            _first(a, ["tracely.step.id", "langgraph_step"]) or lc_meta.get("langgraph_step") or ""
        ),
        "step_name": str(
            _first(a, ["tracely.step.name", "langgraph_node"])
            or lc_meta.get("langgraph_node")
            or ""
        ),
        "tool_call_id": str(_first(a, ["tracely.tool_call.id", "gen_ai.tool.call.id"]) or ""),
        "caller_agent_id": str(_first(a, ["tracely.handoff.caller_agent_id"]) or ""),
        "callee_agent_id": str(_first(a, ["tracely.handoff.callee_agent_id"]) or ""),
        "edge_type": str(_first(a, ["tracely.edge.type"]) or ""),
        # model / usage
        "model_id": str(
            _first(
                a,
                [
                    "gen_ai.response.model",
                    "gen_ai.request.model",
                    "llm.model_name",
                    "tracely.model",
                ],
            )
            or ""
        ),
        "model_parameters": _model_parameters(a),
        "usage_details": _usage(a),
        "tool_call_names": _tool_call_names(a, otype),
        # io — single-value escape hatches + reassembled structured/flattened messages (R5)
        "input": _io_field(a, "input"),
        "output": _io_field(a, "output"),
        # metadata: keep everything (lossless), stringified — except the I/O + message attrs, which
        # have their own columns (and would otherwise duplicate large message bodies into every row);
        # plus convention-version provenance (R14): semconv schema_url, instrumentor version, shape.
        "metadata": {
            **{k: _to_str(v) or "" for k, v in a.items() if not _is_msg_attr(k)},
            "tracely.otel.gen_ai_convention": _convention(a),
            **({"tracely.otel.schema_url": schema_url} if schema_url else {}),
            **({"tracely.otel.scope_version": scope_version} if scope_version else {}),
        },
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
            # OTLP schema_url = the semantic-convention version (D4). Prefer scope-level (the
            # instrumentor's semconv), fall back to the resource's.
            schema_url = ss.schema_url or rs.schema_url
            for span in ss.spans:
                events.append(
                    _map_span(
                        resource_attrs, scope_name, scope_version, span, project_id, schema_url
                    )
                )
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
