"""Observation type classification + canonical type constants.

`map_observation_type` resolves a span's type defensively (R15): tracely.observation.type ->
gen_ai.operation.name -> openinference.span.kind -> tool/model heuristics -> SPAN.
OpenInference span-kind is NOT a hard-coded closed enum — unknown kinds fall through to the
heuristics, ultimately SPAN.
"""

from __future__ import annotations

from typing import Any

from tracely.otel.attributes import _first

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


def map_observation_type(attrs: dict[str, Any]) -> str:
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
