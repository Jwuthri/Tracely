"""Message normalization — reassemble the three on-the-wire shapes into Tracely's
`{role, content:[blocks]}`:
  - structured  `gen_ai.input.messages` / `gen_ai.output.messages`  (JSON / complex AnyValue)
  - OpenInference flattened `llm.input_messages.<i>.message.{role,content,tool_calls.<j>...}`
  - OpenLLMetry legacy flattened `gen_ai.{prompt,completion}.<i>.{role,content,tool_calls.<j>...}`
plus the single-value escape hatches (`tracely.*`, `input.value`, legacy `gen_ai.prompt`).
"""

from __future__ import annotations

import ast
import json
from typing import Any


def _as_obj(v: Any) -> Any:
    """A structured value may arrive already decoded (list/dict, from an OTLP complex AnyValue) or
    as a JSON string. Decode the string."""
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
    # Fall back to string coercion (used to be `_to_str`); local to avoid a cycle with attributes.
    try:
        return json.dumps(raw)
    except (TypeError, ValueError):
        return str(raw)


def _normalize_message(m: Any) -> dict[str, Any]:
    if not isinstance(m, dict):
        # Coerce to a single string content with empty role.
        try:
            return {"role": "", "content": json.dumps(m)}
        except (TypeError, ValueError):
            return {"role": "", "content": str(m)}
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
            out.append({
                "id": str(cid or ""),
                "type": "function",
                "function": {
                    "name": str(name or ""),
                    "arguments": args if args is not None else "",
                },
            })
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
    re-injection, CrewAI's `str(dict)` returns) into a real Python object."""
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    try:
        return ast.literal_eval(s)
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
    text. Used to drop structurally-present-but-semantically-empty messages."""
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


def _looks_like_messages(v: Any) -> bool:
    """True if `v` is a chat-message array or a single message-shaped dict."""
    if isinstance(v, list):
        return any(isinstance(m, dict) and ("role" in m or "content" in m) for m in v)
    if isinstance(v, dict):
        return "role" in v or "content" in v
    return False


def _unwrap_langchain_tool_message(v: Any) -> Any:
    """LangChain's `output.value` on a TOOL span is a serialized ToolMessage:
    `{"type": "tool", "data": {"content": "<actual result>", "name": ..., "tool_call_id": ...}}`.
    Unwrap to the inner content."""
    if isinstance(v, dict) and v.get("type") == "tool" and isinstance(v.get("data"), dict):
        inner = v["data"]
        content = inner.get("content")
        if isinstance(content, str):
            try:
                return json.loads(content)
            except (json.JSONDecodeError, ValueError):
                return content
        if content is not None:
            return content
    return v


def _normalize_message_content(m: Any) -> Any:
    """Walk a chat-message dict and normalize its `content` field."""
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


def _normalize_parsed(v: Any) -> Any:
    """Apply LangChain-envelope unwrap and chat-message-content normalization to an already-parsed
    value (dict / list / scalar). Idempotent."""
    v = _unwrap_langchain_tool_message(v)
    if isinstance(v, list) and v and any(isinstance(x, dict) and ("role" in x or "content" in x) for x in v):
        return [_normalize_message_content(x) for x in v]
    if isinstance(v, dict) and ("role" in v or "content" in v):
        return _normalize_message_content(v)
    return v
