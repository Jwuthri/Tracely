"""Generate an evaluator config from a natural-language description ("Use AI" in Add Column).

One `create_agent` call (LangChain on OpenRouter, see `infrastructure.llm.provider`) with a
structured response schema. The output is a DRAFT: the UI pre-fills the manual form with it
for review/editing — generation never creates the evaluator directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tracely.infrastructure.llm import provider

LEVELS = ("CONVERSATION", "AGENT_RUN", "SPAN")
OUTPUT_TYPES = ("score", "boolean", "category", "text", "json")

_SYSTEM = """You design LLM-as-judge evaluation metrics for an AI-agent observability platform.
A metric grades agent traces at exactly one level:
- "CONVERSATION": one grade for a whole multi-turn conversation (goal achievement, frustration, drift).
- "AGENT_RUN": one grade per agent run / assistant turn (answer quality, tone, hallucination).
- "SPAN": one grade per step inside a run — a tool call or model generation (tool choice, argument quality).

And produces exactly one output type:
- "score": a 0..1 quality score with a pass threshold (most metrics).
- "boolean": a pass/fail judgment.
- "category": one label from a fixed set (classification metrics, e.g. intent).
- "text": a short free-text observation (no pass/fail).

Write the grading rubric like a strict senior reviewer would: second person, specific, naming
the failure modes to look for, and concrete about what earns a high vs low grade. Do NOT
mention JSON or output formatting in the rubric — the platform handles that."""


class GeneratedEvaluatorDraft(BaseModel):
    """The structured response schema for metric generation."""

    name: str = Field(description="short metric name, 2-5 words")
    description: str = Field(default="", description="one sentence: what this metric checks")
    level: str = Field(description='one of "CONVERSATION", "AGENT_RUN", "SPAN"')
    output_type: str = Field(description='one of "score", "boolean", "category", "text"')
    prompt: str = Field(description="the grading rubric the judge LLM will receive")
    threshold: float | None = Field(default=None, description='0..1 pass threshold, only for "score"')
    categories: list[str] | None = Field(default=None, description='the labels, only for "category"')


def generate_evaluator_config(description: str) -> dict[str, Any]:
    """Returns a normalized draft `{name, description, kind, level, config{prompt, output_type,
    threshold?, categories?}}`. Raises on transport errors (caller maps to HTTP 502)."""
    draft = provider.run_structured_agent(
        f"Design an evaluation metric for: {description.strip()[:2000]}",
        response_format=GeneratedEvaluatorDraft,
        system_prompt=_SYSTEM,
    )
    level = draft.level.upper().strip()
    if level not in LEVELS:
        level = "AGENT_RUN"
    output_type = draft.output_type.lower().strip()
    if output_type not in OUTPUT_TYPES:
        output_type = "score"
    config: dict[str, Any] = {
        "prompt": draft.prompt.strip(),
        "output_type": output_type,
    }
    if output_type == "score":
        try:
            config["threshold"] = min(max(float(draft.threshold if draft.threshold is not None else 0.6), 0.0), 1.0)
        except (TypeError, ValueError):
            config["threshold"] = 0.6
    if output_type == "category":
        cats = [str(c).strip() for c in (draft.categories or []) if str(c).strip()]
        config["categories"] = cats or ["good", "bad", "other"]
    return {
        "name": draft.name.strip()[:120] or "Custom metric",
        "description": draft.description.strip()[:400],
        "kind": "llm_judge",
        "level": level,
        "config": config,
    }
