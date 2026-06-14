"""Meta-analysis ("Analyze"): cross-metric correlation/outlier synthesis over an agent's
evaluator scores.

Pure HTTP shaping — the async ClickHouse gather lives in `async_reader.agent_score_rows`, the
stats+LLM+persist in `MetaAnalysisService` (run in a threadpool, since it's sync), Postgres
lookups in `repositories`. The router never builds SQL.

The selector unit is the AGENT: pass `agent_id` (an events agent id) to scope, or "all"/blank for
the whole project. Analyses are persisted per (project, agent); the panel shows the latest on open
and re-runs on demand.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.clickhouse import async_reader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.services.meta_analysis_service import MetaAnalysisService, _to_response

router = APIRouter(prefix="/api")


class RunBody(BaseModel):
    agent_id: str = ""  # "" / "all" → whole project


def _norm_agent(agent_id: str | None) -> str:
    v = (agent_id or "").strip()
    return "" if v in ("", "all", "_all_") else v


@router.get("/meta-analyses/agents")
async def list_analysis_agents(project_id: str = Depends(get_project_id)) -> list[dict]:
    """The project's agents, for the meta-analysis selector ([{id, slug, display_name}])."""

    def work() -> list[dict]:
        with SyncSessionLocal() as s:
            return [
                {"id": a.id, "slug": a.slug, "display_name": a.display_name or a.slug}
                for a in repo.agents_list(s, project_id)
            ]

    return await run_in_threadpool(work)


@router.post("/meta-analyses/run")
async def run_meta_analysis(
    body: RunBody, project_id: str = Depends(get_project_id)
) -> dict:
    """Gather the agent's eval scores, compute correlations/outliers, synthesize, persist, return."""
    agent_id = _norm_agent(body.agent_id)
    rows = await async_reader.agent_score_rows(project_id, agent_id)
    if not rows:
        raise HTTPException(
            status_code=409,
            detail="No evaluation scores found for this selection — run evaluations first.",
        )
    return await run_in_threadpool(
        MetaAnalysisService.analyze_and_save, project_id, agent_id, rows
    )


@router.get("/meta-analyses/agent/{agent_id}")
async def latest_for_agent(
    agent_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """The latest analysis for an agent (or whole project for 'all'/blank). `{analysis: null}`
    when none has been run yet — so the panel can show the 'ready' state without 404 handling."""
    norm = _norm_agent(agent_id)

    def work() -> dict | None:
        with SyncSessionLocal() as s:
            row = repo.meta_analysis_latest_for_agent(s, project_id, norm)
            return _to_response(row) if row else None

    return {"analysis": await run_in_threadpool(work)}


@router.get("/meta-analyses/{analysis_id}")
async def get_meta_analysis(
    analysis_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    def work() -> dict | None:
        with SyncSessionLocal() as s:
            row = repo.meta_analysis_get(s, project_id, analysis_id)
            return _to_response(row) if row else None

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="analysis not found")
    return res


@router.delete("/meta-analyses/{analysis_id}")
async def delete_meta_analysis(
    analysis_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    def work() -> bool:
        with SyncSessionLocal() as s:
            return repo.meta_analysis_delete(s, project_id, analysis_id)

    if not await run_in_threadpool(work):
        raise HTTPException(status_code=404, detail="analysis not found")
    return {"ok": True}
