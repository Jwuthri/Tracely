"""Session/thread endpoints: traces grouped into conversations + per-turn rollups.

Pure HTTP shaping — all ClickHouse access lives in `infrastructure.clickhouse.async_reader`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.clickhouse import async_reader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.services.rolling_summary_service import RollingSummaryService

router = APIRouter(prefix="/api")


@router.get("/sessions")
async def list_sessions(
    limit: int = 50,
    offset: int = 0,
    from_ts: str | None = None,
    to_ts: str | None = None,
    project_id: str = Depends(get_project_id),
) -> list[dict]:
    """Traces grouped into threads by conversation/session (a trace with no conversation is its
    own 1-turn thread). Each row: first user input, last agent answer, turns, tokens, cost,
    status, and the thread's CONVERSATION-level eval scores (the C-row metric columns).

    `from_ts`/`to_ts` (ISO-8601, treated as UTC) bound the trace's `start_time`; `offset` pages
    the threads (newest first) for the UI's "Load more". Callers derive "has more" from
    `len(rows) == limit`."""
    rows = await async_reader.sessions_overview(project_id, limit, offset, from_ts, to_ts)
    conv_scores = await async_reader.conversation_scores_by_thread(
        project_id, [r["thread"] for r in rows]
    )
    for r in rows:
        r["scores"] = conv_scores.get(r["thread"], [])
    return rows


@router.get("/sessions/{thread_id}")
async def get_session(
    thread_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """The turns (traces) inside one thread, oldest-first — a simple conversation replay. Each
    turn carries its auto-eval scores (the same the trace page shows); the thread carries its
    own CONVERSATION-level scores."""
    turns = await async_reader.session_turns(project_id, thread_id)
    by_trace = await async_reader.scores_by_trace(project_id, [t["trace_id"] for t in turns])
    for t in turns:
        t["scores"] = by_trace.get(t["trace_id"], [])
        t["verdict"] = (
            "FAIL" if any(s["verdict"] == "FAIL" for s in t["scores"])
            else ("PASS" if t["scores"] else None)
        )
    thread_scores = await async_reader.conversation_scores(project_id, thread_id)
    return {"thread_id": thread_id, "turns": turns, "scores": thread_scores}


@router.get("/sessions/{thread_id}/agents")
async def get_session_agents(
    thread_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """The agents (and the tools each used) that participated in this conversation, derived from
    its spans. Optional metadata — sparse when the traces carry only a single default agent. Agent
    ids are resolved to their registered slug/display name where known."""
    agents = await async_reader.thread_agents(project_id, thread_id)
    ids = [a["agent_id"] for a in agents if a["agent_id"]]

    def resolve_names() -> dict[str, dict]:
        names: dict[str, dict] = {}
        with SyncSessionLocal() as s:
            for aid in ids:
                a = repo.agent_in_project(s, project_id, aid)
                if a:
                    names[aid] = {"slug": a.slug, "display_name": a.display_name or a.slug}
        return names

    name_map = await run_in_threadpool(resolve_names) if ids else {}
    for a in agents:
        info = name_map.get(a["agent_id"])
        a["slug"] = info["slug"] if info else ""
        a["name"] = (info["display_name"] if info else "") or a["agent_id"] or "agent"
    return {"thread_id": thread_id, "agents": agents}


class GenerateSummaryBody(BaseModel):
    force: bool = False  # rebuild from scratch (drop cached step rows)


@router.get("/sessions/{thread_id}/rolling-summary")
async def get_rolling_summary(
    thread_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """The stored rolling summary for a conversation (accumulated items + the @HISTORY rendering),
    or an empty shell when none has been generated yet."""
    return await run_in_threadpool(
        RollingSummaryService.get_for_thread, project_id, thread_id
    )


@router.get("/sessions/{thread_id}/rolling-summary/by-level")
async def get_rolling_summary_by_level(
    thread_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """Per-row rolling summaries for the table's three levels — `conversation` (whole thread),
    `traces[trace_id]` (through that turn), and `spans[span_id]` (through that step). Each is the
    accumulated summary AS OF that row, rendered + clipped for display (the cell shows the top
    512 chars)."""
    return await run_in_threadpool(
        RollingSummaryService.by_level, project_id, thread_id
    )


@router.post("/sessions/{thread_id}/rolling-summary/generate")
async def generate_rolling_summary(
    thread_id: str,
    body: GenerateSummaryBody = GenerateSummaryBody(),
    project_id: str = Depends(get_project_id),
) -> dict:
    """Generate (or refresh with `force`) the per-span rolling summary for a conversation. Short
    steps are kept verbatim; only large steps hit the summarizer LLM."""

    def work() -> dict:
        return RollingSummaryService().build_for_thread(project_id, thread_id, force=body.force)

    return await run_in_threadpool(work)
