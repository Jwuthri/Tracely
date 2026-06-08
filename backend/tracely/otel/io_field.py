"""Resolve a span's `input`/`output` column from the on-the-wire attributes.

Manual `tracely.*` wins; then reassembled instrumentor messages; then the single-value string
conventions. Drops messages whose content is structurally empty so the read-side aggregation
(which picks the earliest non-empty input) doesn't pin the conversation title to a placeholder
framework wrapper.
"""

from __future__ import annotations

import json
from typing import Any

from tracely.otel.attributes import _first, _to_str
from tracely.otel.messages import (
    _has_text,
    _io_messages,
    _looks_like_messages,
    _normalize_parsed,
    _parse_litellm_attr,
)
from tracely.otel.types import EMBEDDING, GENERATION

# Single-value I/O keys (escape hatches + legacy string conventions). The richer structured /
# flattened message shapes are reassembled separately (see `_io_field`).
_IO_KEYS = frozenset({
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
})

# Prefixes/keys of flattened-or-structured message attributes — excluded from the lossless
# metadata passthrough so we don't duplicate (often huge) message content into every row.
_MSG_PREFIXES = (
    "llm.input_messages.",
    "llm.output_messages.",
    "gen_ai.prompt.",
    "gen_ai.completion.",
)
_MSG_KEYS = frozenset({"gen_ai.input.messages", "gen_ai.output.messages"})


_USAGE_KEYS_TO_STRIP_FROM_NON_LLM = (
    "gen_ai.usage.",
    "llm.token_count.",
    "llm.openai.usage",
)


def _is_msg_attr(k: str) -> bool:
    return k in _IO_KEYS or k in _MSG_KEYS or k.startswith(_MSG_PREFIXES)


def _is_strippable_usage_for_non_llm(k: str, otype: str) -> bool:
    """Token-usage attrs that a framework callback (LiteLLM, etc.) may have accidentally stamped
    on a non-LLM span (AGENT, CHAIN, TOOL, …). Already captured in `usage_details` for real LLM
    spans — keeping them in metadata for non-LLM spans causes the frontend's per-span usage cell
    to double-count tokens against the enclosing GENERATION children."""
    if otype in (GENERATION, EMBEDDING):
        return False
    return k.startswith(_USAGE_KEYS_TO_STRIP_FROM_NON_LLM)


def _normalize_io_value(v: Any) -> str | None:
    """Coerce an arbitrary I/O value to a stored JSON string, with three best-effort transforms:
    Python-repr (`{'k':'v'}`) → JSON, LangChain's `{type:"tool", data:{...}}` envelope → inner
    content, and recursive normalization of chat-message `content` fields."""
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


def _io_field(attrs: dict[str, Any], direction: str) -> str | None:
    manual = _first(attrs, [f"tracely.{direction}", f"langfuse.observation.{direction}"])
    if manual is not None:
        return _normalize_io_value(manual)
    msgs = _io_messages(attrs, direction)
    if msgs is not None and _has_text(msgs):
        # Walk message contents to normalize Python-repr tool results re-injected by frameworks
        # (OpenAI Agents SDK, etc.) — otherwise the conversation popover shows `{'k':'v'}` blobs.
        return _to_str(_normalize_parsed(msgs))
    # LiteLLM's `otel` callback stores OpenAI-shaped IO as Python-repr strings under
    # `llm.openai.{messages,choices}`. Pull out the message list (for choices: choice.message)
    # so we end up with the same `[{role,content}, …]` shape every other path produces.
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
    # `input.value` from OpenInference is often a JSON string for tool/chain spans (e.g.
    # LangGraph roots) — peek into it before discarding, and normalize Python-repr (`{'k':'v'}`)
    # into JSON. CrewAI's tools and the OpenAI Agents SDK's conversation-history tool messages
    # both emit the Python-repr shape; normalizing here means the UI never has to deal with
    # single-quote dicts.
    if isinstance(raw, str) and raw.startswith(("[", "{")):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            parsed = _parse_litellm_attr(raw)
        if parsed is not None:
            # Only drop when this *looks like* a message structure with no text — a tool's
            # `{"status": "out_for_delivery", ...}` is a legitimate structured payload even
            # though it has no `text`/`content`/`value` key.
            if _looks_like_messages(parsed) and not _has_text(parsed):
                return None
            return _to_str(_normalize_parsed(parsed))
    return _to_str(raw)
