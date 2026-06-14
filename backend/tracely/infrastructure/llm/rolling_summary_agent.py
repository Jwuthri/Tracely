"""The LLM half of the rolling summary: compress a step's components into ~10-20 word summaries.

Only invoked for steps too large to keep verbatim (the service applies the verbatim shortcut
first). Returns one short summary per component, in order; the service rebuilds the typed items
(preserving role/type/tool linkage) so the model can never corrupt the structure. Goes through the
provider seam; any failure degrades to a truncation fallback in the service.
"""

from __future__ import annotations

import structlog
from pydantic import BaseModel, Field

from tracely.config import settings

log = structlog.get_logger()


class StepSummaries(BaseModel):
    summaries: list[str] = Field(
        default_factory=list,
        description="one ~10-20 word summary per input component, in the same order",
    )


_SYSTEM = (
    "You are a summarizer for conversation history. You receive the components of ONE step of an "
    "AI agent run (thinking, tool calls, tool results, or outputs). Return one EXTREMELY SHORT "
    "summary per component, in the same order — ~10-20 words each, capturing the essential "
    "information only. For tool calls, preserve the tool name and key parameters. Never add "
    "commentary. Return exactly as many summaries as there are components."
)


def summarize_components(components: list) -> list[str] | None:
    """`[summary, …]` aligned to `components`, or None on failure (caller falls back to truncation).
    `components` are `domain.evaluation.rolling_summary.Component` instances."""
    if not components:
        return []
    from tracely.infrastructure.llm import provider

    listing = "\n".join(
        f"{i + 1}. [{c.role}:{c.type}] {c.content}" for i, c in enumerate(components)
    )
    prompt = (
        f"Summarize each of these {len(components)} step components (one summary each, in order):\n\n"
        f"{listing}"
    )
    try:
        res = provider.run_structured_agent(
            prompt,
            response_format=StepSummaries,
            system_prompt=_SYSTEM,
            model=settings.rolling_summary_model,
            temperature=0.0,
        )
        return list(res.summaries)
    except Exception as exc:
        log.warning("rolling_summary_summarize_failed", error=str(exc), n=len(components))
        return None


_COMPACT_SYSTEM = (
    "You are compacting the EARLIER part of a conversation history that has grown too long. "
    "Rewrite it into a single, dense summary that preserves what later turns may need: the user's "
    "goals, key facts and decisions, tools called and their important results, and unresolved "
    "threads. Drop pleasantries and redundancy. Be compact but lossless on anything load-bearing. "
    "Return only the summary text."
)


def compact_items(history_text: str) -> str | None:
    """Compress a block of older history (already rendered to text) into one dense summary, or None
    on failure (the service then falls back to a naive truncation)."""
    if not history_text.strip():
        return ""
    from tracely.infrastructure.llm import provider

    try:
        return provider.run_text_agent(
            f"Compact this earlier conversation history:\n\n{history_text}",
            system_prompt=_COMPACT_SYSTEM,
            model=settings.rolling_summary_model,
            temperature=0.0,
        ).strip()
    except Exception as exc:
        log.warning("rolling_summary_compact_failed", error=str(exc))
        return None
