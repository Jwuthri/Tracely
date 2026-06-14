"""Rolling-summary generation: the per-span accumulate loop over a thread.

Two rules, applied as each step (span) is folded in (in thread order):

  RULE 1 — represent the step: components ≤ `step_max_tokens` (512) are kept VERBATIM (no LLM);
           larger steps are summarized to ~10-20 words by `rolling_summary_agent`.
  RULE 2 — keep the whole summary under `max_tokens` (20k): whenever the accumulated summary
           exceeds the budget, the older items (everything but the last 2, which stay verbatim) are
           recursively compacted into ONE dense block. This bounds memory and keeps `@HISTORY`
           coherent on long conversations instead of hard-clipping it.

One row per span holds the full accumulated (possibly compacted) summary at that point — so the
conversation view is the last row, a message view is its turn's last step, a step view is that
exact row. Generation is idempotent (one row per span) and incremental (a single up-front read
seeds the cache), so the ingest hook re-runs cheaply as new turns arrive. `history_override` is the
read side `@HISTORY` uses (FULL compacted summary; never raises).

Sync (same `TraceReader` + `SyncSessionLocal` as the eval engine); the API/worker run it in a
threadpool / task.
"""

from __future__ import annotations

import structlog

from tracely.config import settings
from tracely.domain.evaluation.rolling_summary import (
    compacted_item,
    components_token_total,
    format_summary_as_history,
    items_from_components,
    step_components,
    summary_token_total,
    user_input_component,
)
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db import repositories
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.llm import provider
from tracely.infrastructure.llm.rolling_summary_agent import compact_items, summarize_components

log = structlog.get_logger()

_KEEP_LAST = 2  # the most-recent items always stay verbatim during compaction
_COMPACT_MAX_PASSES = 6  # recursion backstop (a huge un-shrinkable tail can't loop forever)
_LEVEL_CLIP = 4000  # per-row render budget for the table's summary column (cell shows top 512)


def _group_turns(spans: list[dict]) -> list[tuple[str, list[dict]]]:
    """Spans grouped by trace_id in first-seen (start_time) order."""
    by_trace: dict[str, list[dict]] = {}
    order: list[str] = []
    for s in spans:
        tid = s.get("trace_id") or ""
        if tid not in by_trace:
            by_trace[tid] = []
            order.append(tid)
        by_trace[tid].append(s)
    return [(tid, by_trace[tid]) for tid in order]


def _naive_compact(text: str, budget_tokens: int) -> str:
    """Fallback compaction when no LLM is configured: bound the head to ~half the budget so the
    summary still shrinks (lossy, but keeps the budget invariant)."""
    max_chars = max(400, budget_tokens * 2)  # ≈ budget/2 tokens
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


class RollingSummaryService:
    def __init__(self, trace_reader: TraceReader | None = None) -> None:
        self.trace_reader = trace_reader or TraceReader()

    def build_for_thread(
        self, project_id: str, thread_id: str, *, force: bool = False, source: str = "on_demand"
    ) -> dict:
        """Generate (or refresh with `force`) the per-span rolling summary for a thread. Idempotent
        + incremental. Returns the final accumulated summary + counts."""
        spans = self.trace_reader.read_thread_spans(project_id, thread_id)
        if not spans:
            return {"thread_id": thread_id, "steps": 0, "items": [], "token_count": 0, "llm_steps": 0}

        # flatten to thread order, tagging each span's trace + whether it's the turn's root wrapper
        flat: list[tuple[str, dict, bool, bool]] = []
        for trace_id, tspans in _group_turns(spans):
            root_id = root_span(tspans).get("span_id")
            multi = len(tspans) > 1
            for span in tspans:
                flat.append((trace_id, span, span.get("span_id") == root_id, multi))

        running: list[dict] = []
        llm_steps = 0
        with SyncSessionLocal() as s:
            if force:
                repositories.rolling_summary_delete_for_thread(s, project_id, thread_id)
                existing: dict[str, list] = {}
            else:
                # one read up front → in-memory idempotent skip (no per-span query)
                existing = {
                    r.span_id: list(r.summary or [])
                    for r in repositories.rolling_summary_list_for_thread(s, project_id, thread_id)
                }

            for step_order, (trace_id, span, is_root, multi) in enumerate(flat):
                span_id = span.get("span_id") or ""
                if not span_id:
                    continue
                if span_id in existing:  # already summarized → carry its accumulated state forward
                    running = existing[span_id]
                    continue

                # decompose: the agent-root wrapper contributes only the user input (its answer is
                # captured by the child generation) unless the turn is a single span.
                comps = []
                if is_root:
                    uc = user_input_component(span)
                    if uc:
                        comps.append(uc)
                    if not multi:
                        comps += step_components(span)
                else:
                    comps += step_components(span)

                verbatim = True
                if comps:
                    # RULE 1 — represent the step
                    summaries = None
                    if (
                        components_token_total(comps) > settings.rolling_summary_step_max_tokens
                        and provider.llm_enabled()
                    ):
                        summaries = summarize_components(comps)
                        if summaries is not None:
                            verbatim = False
                            llm_steps += 1
                    new_items = items_from_components(comps, summaries)
                    running = running + [it.model_dump() for it in new_items]

                # RULE 2 — keep the whole summary under budget (recursive compaction)
                running, compactions = self._compact_to_budget(running)
                llm_steps += compactions

                repositories.rolling_summary_create(
                    s,
                    project_id,
                    thread_id=thread_id,
                    trace_id=trace_id,
                    span_id=span_id,
                    step_order=step_order,
                    summary=running,
                    token_count=summary_token_total(running),
                    meta={
                        "model": "" if verbatim else settings.rolling_summary_model,
                        "verbatim": verbatim,
                        "step_order": step_order,
                        "source": source,
                    },
                )

        return {
            "thread_id": thread_id,
            "steps": len(flat),
            "items": running,
            "token_count": summary_token_total(running),
            "llm_steps": llm_steps,
        }

    def _compact_to_budget(self, running: list[dict]) -> tuple[list[dict], int]:
        """Fold `items[:-2]` into one compacted block while the summary exceeds the token budget,
        keeping the last 2 items verbatim. Recursive (loops) with a progress guard + pass cap so a
        huge un-shrinkable tail can't spin. Returns (items, number_of_compactions)."""
        budget = settings.rolling_summary_max_tokens
        compactions = 0
        passes = 0
        while (
            summary_token_total(running) > budget
            and len(running) > _KEEP_LAST
            and passes < _COMPACT_MAX_PASSES
        ):
            passes += 1
            head, tail = running[:-_KEEP_LAST], running[-_KEEP_LAST:]
            head_text = format_summary_as_history(head, max_chars=0)
            compacted = compact_items(head_text) if provider.llm_enabled() else None
            if not compacted:
                compacted = _naive_compact(head_text, budget)
            candidate = [compacted_item(compacted)] + tail
            if summary_token_total(candidate) >= summary_token_total(running):
                break  # no progress (compaction didn't shrink, or the tail alone exceeds budget)
            running = candidate
            compactions += 1
        return running, compactions

    @staticmethod
    def get_for_thread(project_id: str, thread_id: str) -> dict:
        """The conversation-level rolling summary (final accumulated items + @HISTORY rendering),
        or an empty shell when none has been generated."""
        with SyncSessionLocal() as s:
            rows = repositories.rolling_summary_list_for_thread(s, project_id, thread_id)
        latest = rows[-1] if rows else None
        items = latest.summary if latest else []
        return {
            "thread_id": thread_id,
            "steps": len(rows),
            "items": items,
            "token_count": latest.token_count if latest else 0,
            "history": format_summary_as_history(items, max_chars=0) if items else "",
            "generated_at": (
                latest.updated_at.isoformat() if latest and latest.updated_at else None
            ),
        }

    @staticmethod
    def by_level(project_id: str, thread_id: str, *, clip: int = _LEVEL_CLIP) -> dict:
        """Per-row rendered summaries for the table's 3 levels:
        `conversation` (full thread), `traces[trace_id]` (through that turn's last step), and
        `spans[span_id]` (through that step). Each clipped for display; the cell shows the top 512
        chars and expands to this."""
        with SyncSessionLocal() as s:
            rows = repositories.rolling_summary_list_for_thread(s, project_id, thread_id)
        if not rows:
            return {"thread_id": thread_id, "steps": 0, "conversation": "", "traces": {}, "spans": {}}
        spans: dict[str, str] = {}
        traces: dict[str, str] = {}
        for r in rows:  # ordered by step_order → traces[tid] ends at that trace's last step
            rendered = format_summary_as_history(r.summary or [], max_chars=clip)
            spans[r.span_id] = rendered
            traces[r.trace_id] = rendered
        return {
            "thread_id": thread_id,
            "steps": len(rows),
            "conversation": format_summary_as_history(rows[-1].summary or [], max_chars=clip),
            "traces": traces,
            "spans": spans,
        }

    @staticmethod
    def history_override(project_id: str, thread_id: str) -> str | None:
        """The FULL compacted history string for `@HISTORY` (bounded by the 20k budget, not clipped),
        or None when no summary exists (caller falls back to the raw transcript). Guarded — a lookup
        / format failure never blocks a grade."""
        if not thread_id:
            return None
        try:
            with SyncSessionLocal() as s:
                row = repositories.rolling_summary_latest_for_thread(s, project_id, thread_id)
            if row and row.summary:
                return format_summary_as_history(row.summary, max_chars=0) or None
        except Exception as exc:  # never break the eval path on a cache miss/error
            log.warning("rolling_summary_history_override_failed", error=str(exc))
        return None
