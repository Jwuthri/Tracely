"""Token usage + model parameter extraction.

`_usage` returns an additive token map; `usage_details` is summed leaf-wise downstream
(`arraySum(mapValues(usage_details))` in reads/gate), so it must hold only *non-overlapping*
counts (`input` + `output`). `total` is stored only as a fallback when neither component is
present (else it would double-count). Reasoning/cache breakdowns are subsets of input/output
(and provider-dependent — §13), so they stay out of this map and ride along in `metadata`.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from tracely.otel.attributes import _first, _ns_to_dt
from tracely.otel.messages import _as_obj
from tracely.otel.types import EMBEDDING, GENERATION


def _usage(attrs: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    # When the user explicitly set the span's observation type to something non-LLM (AGENT, CHAIN,
    # THINKING, TOOL, etc.), skip auto-extracting `gen_ai.*`/`llm.*` token counts. Callbacks like
    # LiteLLM's `otel` dump completion attrs onto the CURRENT span — if that's an enclosing AGENT
    # wrapper, we'd double-count tokens (parent + each GENERATION child).
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
    inp = _first(attrs, [
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.prompt_tokens",
        "llm.token_count.prompt",
        "llm.openai.usage.prompt_tokens",
    ])
    outp = _first(attrs, [
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.completion_tokens",
        "llm.token_count.completion",
        "llm.openai.usage.completion_tokens",
    ])
    total = _first(attrs, [
        "gen_ai.usage.total_tokens", "llm.token_count.total", "llm.openai.usage.total_tokens",
    ])
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
