"""Session/thread endpoints: traces grouped into conversations + per-turn rollups.

Pure HTTP shaping — all ClickHouse access lives in `infrastructure.clickhouse.async_reader`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tracely.api.advisory import advisory_score_names
from tracely.api.auth import get_project_id
from tracely.domain.evaluation.verdict import rollup_verdict
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
    advisory = await advisory_score_names(project_id)
    rows = await async_reader.sessions_overview(
        project_id, limit, offset, from_ts, to_ts, advisory
    )
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
    advisory = await advisory_score_names(project_id)
    turns = await async_reader.session_turns(project_id, thread_id, advisory)
    by_trace = await async_reader.scores_by_trace(project_id, [t["trace_id"] for t in turns])
    for t in turns:
        t["scores"] = by_trace.get(t["trace_id"], [])
        t["verdict"] = rollup_verdict(t["scores"], advisory)
    thread_scores = await async_reader.conversation_scores(project_id, thread_id)
    return {"thread_id": thread_id, "turns": turns, "scores": thread_scores}


def _shape_declared_agent(ag: dict, obs_counts: dict[str, int]) -> dict:
    """Normalize a user-declared agent ({name, description, tools}) into the panel shape, annotating
    each tool with how many times it was actually executed in the conversation (from observed spans).
    `tools` may be a dict-of-tools (the documented shape) or a list."""
    raw = ag.get("tools")
    entries = raw.items() if isinstance(raw, dict) else (
        [(t.get("name", ""), t) for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []
    )
    tools = []
    for key, tdef in entries:
        tdef = tdef if isinstance(tdef, dict) else {}
        name = tdef.get("name") or key
        tools.append(
            {
                "name": name,
                "description": tdef.get("description") or "",
                "parameters": tdef.get("parameters") or {},
                "count": obs_counts.get(name, 0),
            }
        )
    return {
        "name": ag.get("name") or "agent",
        "description": ag.get("description") or "",
        "tools": tools,
    }


@router.get("/sessions/{thread_id}/agents")
async def get_session_agents(
    thread_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """A conversation's agents — both the user-DECLARED catalog (sent via the SDK, rich: name,
    description, tools with parameters) and the OBSERVED agents derived from the trace spans (with
    tool-execution counts). The panel shows declared first; observed fills in when nothing was
    declared. Declared tools are annotated with their observed execution counts."""
    observed = await async_reader.thread_agents(project_id, thread_id)
    ids = [a["agent_id"] for a in observed if a["agent_id"]]

    def work() -> tuple[dict[str, dict], list]:
        names: dict[str, dict] = {}
        with SyncSessionLocal() as s:
            for aid in ids:
                a = repo.agent_in_project(s, project_id, aid)
                if a:
                    names[aid] = {"slug": a.slug, "display_name": a.display_name or a.slug}
            row = repo.conversation_agents_get(s, project_id, thread_id)
            declared = list(row.agents) if row and row.agents else []
        return names, declared

    name_map, declared_raw = await run_in_threadpool(work)
    for a in observed:
        info = name_map.get(a["agent_id"])
        a["slug"] = info["slug"] if info else ""
        a["name"] = (info["display_name"] if info else "") or a["agent_id"] or "agent"

    obs_counts: dict[str, int] = {}
    for a in observed:
        for t in a["tools"]:
            obs_counts[t["name"]] = obs_counts.get(t["name"], 0) + t["count"]
    declared = [_shape_declared_agent(ag, obs_counts) for ag in declared_raw if isinstance(ag, dict)]

    return {"thread_id": thread_id, "declared": declared, "observed": observed}


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
