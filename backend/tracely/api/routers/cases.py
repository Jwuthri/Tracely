"""Regression: promote a trace, list/get cases, replay a case + the dashboard stats.

Pure HTTP shaping — ClickHouse counters live in `infrastructure.clickhouse.async_reader`,
Postgres queries in `infrastructure.db.repositories`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.clickhouse import async_reader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import EvaluationCase
from tracely.services.regression_service import NotFound, RegressionService

router = APIRouter(prefix="/api")


@router.get("/stats")
async def stats(project_id: str = Depends(get_project_id)) -> dict:
    counters = await async_reader.stats_counts(project_id)

    def registry():
        with SyncSessionLocal() as s:
            return repo.registry_counts(s, project_id)

    return {**counters, **await run_in_threadpool(registry)}


def _case_dict(c: EvaluationCase, replays: list | None = None) -> dict[str, Any]:
    d = {
        "id": c.id,
        "agent_id": c.agent_id,
        "level": c.level,
        "title": c.title,
        "status": c.status,
        "origin": c.origin,
        "source_trace_id": c.source_trace_id,
        "input_digest": c.input_digest,
        "match_mode": c.match_mode,
        "fail_to_pass_validated": c.fail_to_pass_validated,
        "assertions": c.assertions,
        "reference_trajectory": c.reference_trajectory,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
    if replays is not None:
        d["replays"] = [
            {
                "verdict": r.verdict,
                "candidate_trace_id": r.candidate_trace_id,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in replays
        ]
    return d


@router.post("/traces/{trace_id}/promote")
async def promote(trace_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            try:
                case = RegressionService(s).promote_trace(project_id, trace_id)
            except NotFound as e:
                return ("err", str(e))
            return ("ok", _case_dict(case))

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)
    return payload


@router.get("/cases")
async def list_cases(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            out = []
            for c in repo.cases_list(s, project_id):
                last = repo.case_last_replay(s, c.id)
                d = _case_dict(c)
                d["last_verdict"] = last.verdict if last else None
                out.append(d)
            return out

    return await run_in_threadpool(work)


@router.get("/cases/{case_id}")
async def get_case(case_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            c = repo.case_get(s, project_id, case_id)
            if not c:
                return None
            return _case_dict(c, repo.case_replays(s, case_id))

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="case not found")
    return res


@router.post("/cases/{case_id}/replay")
async def replay(
    case_id: str,
    project_id: str = Depends(get_project_id),
    body: dict = Body(default={}),
) -> dict:
    candidate = body.get("candidate_trace_id")

    def work():
        with SyncSessionLocal() as s:
            c = repo.case_get(s, project_id, case_id)
            if not c:
                return ("err", "case not found")
            tid = candidate or c.source_trace_id
            try:
                r = RegressionService(s).replay_case(project_id, case_id, tid)
            except NotFound as e:
                return ("err", str(e))
            return ("ok", {"verdict": r.verdict, "candidate_trace_id": r.candidate_trace_id, "detail": r.detail})

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)
    return payload
