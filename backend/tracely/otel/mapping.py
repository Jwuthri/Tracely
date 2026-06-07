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
}

# Synonyms collapsed to a canonical type at ingestion. Keeps the menu/filter surface minimal —
# e.g. OpenAI Agents' "reasoning" and Anthropic's "thinking" are the same notion.
_TYPE_ALIASES = {"REASONING": THINKING}

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
    if explicit:
        up = str(explicit).upper()
        if up in _TYPE_ALIASES:
            return _TYPE_ALIASES[up]
        if up in _KNOWN_TYPES:
            return up

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
    if _first(attrs, ["gen_ai.request.model", "gen_ai.response.model", "llm.model_name", "llm.openai.model"]):
        return GENERATION
    return SPAN


def _usage(attrs: dict[str, Any]) -> dict[str, int]:
    """Additive token map. `usage_details` is summed leaf-wise downstream
    (`arraySum(mapValues(usage_details))` in reads/gate), so it must hold only *non-overlapping*
    counts: `input` + `output`. `total` is stored only as a fallback when neither component is
    present (else it would double-count). Reasoning/cache breakdowns are subsets of input/output
    (and provider-dependent — §13), so they stay out of this map and ride along in `metadata`."""
    out: dict[str, int] = {}
    # When the user explicitly set the span's observation type to something non-LLM (AGENT, CHAIN,
    # THINKING, TOOL, etc.), skip auto-extracting `gen_ai.*`/`llm.*` token counts. Callbacks like
    # LiteLLM's `otel` dump completion attrs onto the CURRENT span — if that's an enclosing AGENT
    # wrapper, we'd double-count tokens (parent + each GENERATION child). The child GENERATION span
    # the callback also creates already carries the canonical numbers.
    explicit = _first(attrs, ["tracely.observation.type", "langfuse.observation.type"])
    if explicit and str(explicit).upper() not in {GENERATION, EMBEDDING}:
        return out
    # LiteLLM's `otel` callback packs the usage dict as a Python-repr string under `llm.openai.usage`
    # (e.g. "{'prompt_tokens':274,'completion_tokens':66,'total_tokens':340,...}"). Lift those fields
    # into the attrs map first so the lookups below pick them up like a normal flat key/value.
    raw_usage = attrs.get("llm.openai.usage")
    if raw_usage and isinstance(raw_usage, str):
        try:
            parsed_usage = json.loads(raw_usage.replace("'", '"'))
            if isinstance(parsed_usage, dict):
                attrs = {**attrs, **{f"llm.openai.usage.{k}": v for k, v in parsed_usage.items()}}
        except (ValueError, json.JSONDecodeError):
            pass
    inp = _first(
        attrs,
        [
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.prompt_tokens",
            "llm.token_count.prompt",
            "llm.openai.usage.prompt_tokens",
        ],
    )
    outp = _first(
        attrs,
        [
            "gen_ai.usage.output_tokens",
            "gen_ai.usage.completion_tokens",
            "llm.token_count.completion",
            "llm.openai.usage.completion_tokens",
        ],
    )
    total = _first(
        attrs,
        ["gen_ai.usage.total_tokens", "llm.token_count.total", "llm.openai.usage.total_tokens"],
    )
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
    # Preserve identifiers + extras so downstream evals + the UI can resolve tool messages back to
    # their requesting call (tool_call_id ↔ tool_calls[].id) and show structured metadata.
    for k in ("tool_call_id", "name", "id", "finish_reason"):
        if k in m and m[k] not in (None, "", []):
            msg[k] = m[k]
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
        # Preserve message identifiers so downstream evals (tool_consistency) and the UI can match
        # tool result messages back to the requesting `tool_calls[].id`.
        for k in ("tool_call_id", "name", "id", "finish_reason"):
            v = attrs.get(base + k)
            if v not in (None, ""):
                msg[k] = v
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


def _parse_litellm_attr(raw: Any) -> Any:
    """Parse a Python-repr blob (LiteLLM's `otel` callback, OpenAI Agents SDK's tool-result
    re-injection, CrewAI's `str(dict)` returns) into a real Python object. We try `ast.literal_eval`
    first — it understands nested quotes/escapes and Python literals (None/True/False) — and fall
    back to a cheap quote-swap+json.loads for the simple cases."""
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    try:
        import ast as _ast
        return _ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError):
        pass
    swapped = (
        s.replace("'", '"')
        .replace(": None", ": null")
        .replace(": True", ": true")
        .replace(": False", ": false")
    )
    try:
        return json.loads(swapped)
    except (json.JSONDecodeError, ValueError):
        return None


def _has_text(v: Any) -> bool:
    """True if `v` (a message-list / message-dict / content blocks / string) contains any non-empty
    text. Used to drop structurally-present-but-semantically-empty messages like LangGraph's root
    `[{"role":"user","content":""}]` where the real text lives one span deeper."""
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, list):
        return any(_has_text(x) for x in v)
    if isinstance(v, dict):
        for k in ("text", "content", "value"):
            if k in v and _has_text(v[k]):
                return True
        if "tool_calls" in v and v.get("tool_calls"):
            return True
    return False


def _io_field(attrs: dict[str, Any], direction: str) -> str | None:
    """Resolve the `input`/`output` column. Manual `tracely.*` wins; then reassembled instrumentor
    messages; then the single-value string conventions. Drops messages whose content is structurally
    empty so the read-side aggregation (which picks the earliest non-empty input) doesn't pin the
    conversation title to a placeholder framework wrapper."""
    manual = _first(attrs, [f"tracely.{direction}", f"langfuse.observation.{direction}"])
    if manual is not None:
        # Normalize Python-repr (`{'k':'v'}`) here too so manually-captured outputs (CrewAI's
        # `str(dict)` returns, `@observe(as_type="tool")` results) render as structured JSON.
        return _normalize_io_value(manual)
    msgs = _io_messages(attrs, direction)
    if msgs is not None and _has_text(msgs):
        # Walk message contents to normalize Python-repr tool results re-injected by frameworks
        # (OpenAI Agents SDK, etc.) — otherwise the conversation popover shows `{'k':'v'}` blobs.
        return _to_str(_normalize_parsed(msgs))
    # LiteLLM's `otel` callback stores OpenAI-shaped IO as Python-repr strings under
    # `llm.openai.{messages,choices}`. Pull out the message list (for choices: choice.message) so
    # we end up with the same `[{role,content}, …]` shape every other path produces.
    if direction == "input":
        raw_msgs = attrs.get("llm.openai.messages")
        if raw_msgs:
            parsed = _parse_litellm_attr(raw_msgs)
            if parsed:
                return _to_str(_normalize_parsed(parsed))
    else:  # output
        raw_choices = attrs.get("llm.openai.choices")
        if raw_choices:
            parsed = _parse_litellm_attr(raw_choices)
            if isinstance(parsed, list):
                msgs = [c.get("message") for c in parsed if isinstance(c, dict) and c.get("message")]
                if msgs:
                    return _to_str(_normalize_parsed(msgs))
    fallback = {
        "input": ["input.value", "gen_ai.prompt", "input"],
        "output": ["output.value", "gen_ai.completion", "output"],
    }[direction]
    raw = _first(attrs, fallback)
    if raw is None:
        return None
    # `input.value` from OpenInference is often a JSON string for tool/chain spans (e.g. LangGraph
    # roots) — peek into it before discarding, and normalize Python-repr (`{'k':'v'}`) into JSON.
    # CrewAI's tools and the OpenAI Agents SDK's conversation-history tool messages both emit the
    # Python-repr shape; normalizing here means the UI never has to deal with single-quote dicts.
    if isinstance(raw, str) and raw.startswith(("[", "{")):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            parsed = _parse_litellm_attr(raw)  # Python-repr → JSON best effort
        if parsed is not None:
            # Only drop when this *looks like* a message structure with no text — a tool's
            # `{"status": "out_for_delivery", ...}` is a legitimate structured payload even though
            # it has no `text`/`content`/`value` key.
            if _looks_like_messages(parsed) and not _has_text(parsed):
                return None
            return _to_str(_normalize_parsed(parsed))
    return _to_str(raw)


def _unwrap_langchain_tool_message(v: Any) -> Any:
    """LangChain's `output.value` on a TOOL span is a serialized ToolMessage:
    `{"type": "tool", "data": {"content": "<actual result>", "name": ..., "tool_call_id": ...}}`.
    Unwrap to the inner content (which itself is usually a JSON string) so the UI shows the real
    tool result, not the framework's envelope."""
    if isinstance(v, dict) and v.get("type") == "tool" and isinstance(v.get("data"), dict):
        inner = v["data"]
        content = inner.get("content")
        if isinstance(content, str):
            # try to parse the inner JSON string so we end up with structured data
            try:
                return json.loads(content)
            except (json.JSONDecodeError, ValueError):
                return content
        if content is not None:
            return content
    return v


def _normalize_message_content(m: Any) -> Any:
    """Walk a chat-message dict and normalize its `content` field: parse Python-repr strings into
    structured JSON, and unwrap LangChain ToolMessage envelopes. Tool messages frequently carry
    their result as a Python-repr string (`{'name': '...', 'in_stock': 3}`); rewriting the inner
    content to real JSON means the UI's chat pill and the conversation popover both render the
    result as a clean object, not a single-quote blob."""
    if not isinstance(m, dict):
        return m
    c = m.get("content")
    if isinstance(c, str):
        t = c.strip()
        if t.startswith(("{", "[")):
            try:
                parsed = json.loads(t)
            except (json.JSONDecodeError, ValueError):
                parsed = _parse_litellm_attr(t)
            if parsed is not None:
                m = {**m, "content": _unwrap_langchain_tool_message(parsed)}
    elif isinstance(c, list):
        m = {**m, "content": [
            _normalize_message_content(b) if isinstance(b, dict) and ("role" in b or "content" in b) else b
            for b in c
        ]}
    return m


def _normalize_io_value(v: Any) -> str | None:
    """Coerce an arbitrary I/O value to a stored JSON string, with three best-effort transforms:
    Python-repr (`{'k':'v'}`) → JSON, LangChain's `{type:"tool", data:{...}}` envelope → inner
    content, and recursive normalization of chat-message `content` fields so tool messages in
    a conversation history don't leave Python-repr substrings behind."""
    if v is None:
        return None
    if isinstance(v, str):
        t = v.strip()
        if t.startswith(("[", "{")):
            try:
                parsed = json.loads(t)
            except (json.JSONDecodeError, ValueError):
                parsed = _parse_litellm_attr(t)
            if parsed is not None:
                return _to_str(_normalize_parsed(parsed))
        return v
    return _to_str(_normalize_parsed(v))


def _normalize_parsed(v: Any) -> Any:
    """Apply LangChain-envelope unwrap and chat-message-content normalization to an already-parsed
    value (dict / list / scalar). Idempotent."""
    v = _unwrap_langchain_tool_message(v)
    if isinstance(v, list) and v and any(isinstance(x, dict) and ("role" in x or "content" in x) for x in v):
        return [_normalize_message_content(x) for x in v]
    if isinstance(v, dict) and ("role" in v or "content" in v):
        return _normalize_message_content(v)
    return v


def _looks_like_messages(v: Any) -> bool:
    """True if `v` is a chat-message array or a single message-shaped dict (has a `role` or
    `content` key). Distinguishes "this is conversation data" from "this is a tool args/result
    dict" so we don't accidentally drop the latter as 'empty messages'."""
    if isinstance(v, list):
        return any(isinstance(m, dict) and ("role" in m or "content" in m) for m in v)
    if isinstance(v, dict):
        return "role" in v or "content" in v
    return False


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


_USAGE_KEYS_TO_STRIP_FROM_NON_LLM = (
    "gen_ai.usage.",
    "llm.token_count.",
    "llm.openai.usage",
)


def _is_strippable_usage_for_non_llm(k: str, otype: str) -> bool:
    """Token-usage attrs that a framework callback (LiteLLM, etc.) may have accidentally stamped on
    a non-LLM span (AGENT, CHAIN, TOOL, …). Already captured in `usage_details` for real LLM spans
    — keeping them in metadata for non-LLM spans causes the frontend's per-span usage cell to
    double-count tokens against the enclosing GENERATION children."""
    if otype in (GENERATION, EMBEDDING):
        return False
    return k.startswith(_USAGE_KEYS_TO_STRIP_FROM_NON_LLM)


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
        # For TOOL spans, prefer the actual tool name from attrs over the framework's generic span
        # name (LlamaIndex uses `FunctionTool.acall`, etc.) — so the UI shows the tool name and the
        # tool_consistency eval can match "requested" against "executed".
        "name": (
            str(_first(a, ["tool.name", "gen_ai.tool.name"]) or span.name or "")
            if otype == TOOL
            else (span.name or "")
        ),
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
        # model / usage — only meaningful for spans that *are* an LLM call. Non-LLM spans (AGENT,
        # CHAIN, TOOL, ...) get a polluted `model_id` when a framework callback (LiteLLM, etc.)
        # accidentally stamps `llm.openai.model` on the enclosing span; strip it.
        "model_id": (
            str(
                _first(
                    a,
                    [
                        "gen_ai.response.model",
                        "gen_ai.request.model",
                        "llm.model_name",
                        "llm.openai.model",
                        "tracely.model",
                    ],
                )
                or ""
            )
            if otype in (GENERATION, EMBEDDING)
            else ""
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
            **{
                k: _to_str(v) or ""
                for k, v in a.items()
                if not _is_msg_attr(k) and not _is_strippable_usage_for_non_llm(k, otype)
            },
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
    _enrich_tool_io(events)
    return events


def _extract_tool_calls(output_str: str) -> list[dict[str, Any]]:
    """Pull a list of {id, name, arguments} from a GENERATION span's output. Args is the parsed
    JSON object (instrumentors store it as a JSON string)."""
    if not output_str:
        return []
    try:
        parsed = json.loads(output_str)
    except (json.JSONDecodeError, ValueError):
        return []
    msgs = parsed if isinstance(parsed, list) else [parsed]
    out: list[dict[str, Any]] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        for tc in m.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name")
            raw_args = fn.get("arguments") if isinstance(fn, dict) else None
            args: Any = raw_args
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except (json.JSONDecodeError, ValueError):
                    args = raw_args
            if name:
                out.append({"id": tc.get("id"), "name": str(name), "args": args})
    return out


def _tool_results_from_input(input_str: str) -> dict[str, str]:
    """Pull `{tool_call_id -> result_content}` from a GENERATION span's input (conversation
    history). The model that responds to tool dispatch carries the results as `{role:"tool",
    tool_call_id, content}` entries in its input messages."""
    if not input_str:
        return {}
    try:
        parsed = json.loads(input_str)
    except (json.JSONDecodeError, ValueError):
        return {}
    msgs = parsed if isinstance(parsed, list) else []
    out: dict[str, str] = {}
    pending: list[str] = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "").lower() == "tool":
            content = m.get("content")
            if isinstance(content, list):
                content = json.dumps(content)
            elif not isinstance(content, str):
                content = _to_str(content)
            cid = m.get("tool_call_id") or ""
            if cid:
                out[str(cid)] = str(content)
            else:
                pending.append(str(content))
    if pending and not out:
        # Anonymous tool results — keep them in order under positional keys so the caller can match
        # by index when no tool_call_id is available.
        for i, c in enumerate(pending):
            out[f"__pos_{i}"] = c
    return out


def _enrich_tool_io(events: list[dict[str, Any]]) -> None:
    """Reconstruct TOOL spans' input/output for instrumentors that don't capture them
    (OpenInference openai-agents, langchain TOOL spans). We walk parent_span_id from each TOOL to
    its nearest GENERATION ancestor/sibling, parse its tool_calls for arguments, and pull tool
    results out of the next GENERATION's input messages.

    Match strategy (best-first):
      1) tool_call_id on the TOOL span ↔ tool_call.id in the generation
      2) Tool name + positional order among TOOL siblings of the same parent
    """
    by_id: dict[str, dict[str, Any]] = {e["span_id"]: e for e in events if e.get("span_id")}
    if not by_id:
        return
    # children-by-parent for sibling-order matching
    children: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        children.setdefault(e.get("parent_span_id") or "", []).append(e)
    # Sort each parent's children by start_time so positional indices are stable.
    for siblings in children.values():
        siblings.sort(key=lambda x: x.get("start_time") or "")

    # Index GENERATION spans by trace_id so the lookup is per-trace.
    gens_by_trace: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e.get("type") == GENERATION and e.get("output") and e.get("start_time"):
            gens_by_trace.setdefault(e.get("trace_id") or "", []).append(e)
    for gens in gens_by_trace.values():
        gens.sort(key=lambda x: x["start_time"])

    def _nearest_gen(tool_ev: dict[str, Any]) -> dict[str, Any] | None:
        # The model that produced this tool dispatch is the LATEST GENERATION in the same trace
        # whose start_time is ≤ the tool's. Works across nested branches (LangGraph's "tools"
        # CHAIN sibling vs. "model" CHAIN sibling) without needing parent-walk logic.
        st = tool_ev.get("start_time")
        if not st:
            return None
        gens = gens_by_trace.get(tool_ev.get("trace_id") or "", [])
        match: dict[str, Any] | None = None
        for g in gens:
            if g["start_time"] <= st:
                match = g
            else:
                break
        return match

    def _next_gen_after(span: dict[str, Any]) -> dict[str, Any] | None:
        # Tool results land in the NEXT GENERATION's input (the model's response turn after the
        # tools ran). Walk forward in start_time across siblings + ancestors.
        st = span.get("start_time")
        if not st:
            return None
        candidates = [
            e
            for e in events
            if e.get("type") == GENERATION
            and e.get("input")
            and e.get("start_time")
            and e["start_time"] > st
        ]
        candidates.sort(key=lambda x: x["start_time"])
        return candidates[0] if candidates else None

    for ev in events:
        if ev.get("type") != TOOL:
            continue
        has_full_input = ev.get("input") and ev["input"].startswith("{")
        if has_full_input and ev.get("output"):
            continue  # already complete
        gen = _nearest_gen(ev)
        if not gen:
            continue
        calls = _extract_tool_calls(gen.get("output") or "")
        if not calls:
            continue
        # 1) try tool_call_id match (most precise)
        tcid = ev.get("tool_call_id") or ""
        match = next((c for c in calls if c.get("id") and str(c["id"]) == str(tcid)), None) if tcid else None
        # 2) fall back to name + positional order among same-parent TOOL siblings
        if match is None:
            name = (ev.get("name") or "").lower()
            same_parent_tools = [
                s for s in children.get(ev.get("parent_span_id") or "", []) if s.get("type") == TOOL
            ]
            idx_in_parent = same_parent_tools.index(ev) if ev in same_parent_tools else -1
            named = [c for c in calls if (c.get("name") or "").lower() == name]
            if named and 0 <= idx_in_parent < len(named):
                match = named[idx_in_parent]
            elif named:
                match = named[0]
            elif 0 <= idx_in_parent < len(calls):
                match = calls[idx_in_parent]
        if not match:
            continue
        if not has_full_input and match.get("args") is not None:
            args = match["args"]
            ev["input"] = _to_str(args) if not isinstance(args, str) else args
            if not isinstance(args, str):
                ev["input"] = json.dumps(args)
        # Reconstruct output from the NEXT generation's tool results
        if not ev.get("output"):
            next_gen = _next_gen_after(ev)
            if next_gen:
                results = _tool_results_from_input(next_gen.get("input") or "")
                cid = match.get("id")
                if cid and str(cid) in results:
                    ev["output"] = results[str(cid)]
                else:
                    # positional fallback (no tool_call_id propagation)
                    same_parent_tools = [
                        s for s in children.get(ev.get("parent_span_id") or "", []) if s.get("type") == TOOL
                    ]
                    idx_in_parent = same_parent_tools.index(ev) if ev in same_parent_tools else -1
                    pos_key = f"__pos_{idx_in_parent}"
                    if pos_key in results:
                        ev["output"] = results[pos_key]


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
