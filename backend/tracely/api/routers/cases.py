"""Regression: promote a trace, list/get cases, replay a case."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import desc, func, select
from starlette.concurrency import run_in_threadpool

from tracely import clickhouse, regression
from tracely.api.auth import get_project_id
from tracely.db import SyncSessionLocal
from tracely.models import Agent, CaseReplay, EvaluationCase, FailureCluster

router = APIRouter(prefix="/api")


@router.get("/stats")
async def stats(project_id: str = Depends(get_project_id)) -> dict:
    def work():
        c = clickhouse.get_client()
        r = c.query(
            "SELECT uniqExact(trace_id), count() FROM events FINAL WHERE project_id = {p:String}",
            parameters={"p": project_id},
        ).result_rows
        traces, spans = (int(r[0][0]), int(r[0][1])) if r else (0, 0)
        f = c.query(
            "SELECT uniqExact(trace_id) FROM events FINAL WHERE project_id = {p:String} AND level = 'ERROR'",
            parameters={"p": project_id},
        ).result_rows
        failing = int(f[0][0]) if f else 0
        af = c.query(
            "SELECT uniqExact(trace_id) FROM scores FINAL WHERE project_id = {p:String} "
            "AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = ''",
            parameters={"p": project_id},
        ).result_rows
        auto_failures = int(af[0][0]) if af else 0
        with SyncSessionLocal() as s:
            agents = s.execute(
                select(func.count()).select_from(Agent).where(Agent.project_id == project_id)
            ).scalar() or 0
            cases = s.execute(
                select(func.count()).select_from(EvaluationCase).where(EvaluationCase.project_id == project_id)
            ).scalar() or 0
            open_clusters = s.execute(
                select(func.count()).select_from(FailureCluster).where(
                    FailureCluster.project_id == project_id, FailureCluster.status == "OPEN"
                )
            ).scalar() or 0
        return {"traces": traces, "spans": spans, "failing_traces": failing,
                "auto_failures": auto_failures, "open_clusters": int(open_clusters),
                "agents": int(agents), "cases": int(cases)}

    return await run_in_threadpool(work)


def _case_dict(c: EvaluationCase, replays: list[CaseReplay] | None = None) -> dict[str, Any]:
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
                case = regression.promote_trace(s, project_id, trace_id)
            except regression.NotFound as e:
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
            rows = (
                s.execute(
                    select(EvaluationCase)
                    .where(EvaluationCase.project_id == project_id)
                    .order_by(desc(EvaluationCase.created_at))
                )
                .scalars()
                .all()
            )
            # attach the latest replay verdict for the list view
            out = []
            for c in rows:
                last = (
                    s.execute(
                        select(CaseReplay)
                        .where(CaseReplay.case_id == c.id)
                        .order_by(desc(CaseReplay.created_at))
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                d = _case_dict(c)
                d["last_verdict"] = last.verdict if last else None
                out.append(d)
            return out

    return await run_in_threadpool(work)


@router.get("/cases/{case_id}")
async def get_case(case_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            c = s.get(EvaluationCase, case_id)
            if not c or c.project_id != project_id:
                return None
            replays = (
                s.execute(
                    select(CaseReplay)
                    .where(CaseReplay.case_id == case_id)
                    .order_by(desc(CaseReplay.created_at))
                )
                .scalars()
                .all()
            )
            return _case_dict(c, replays)

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
            c = s.get(EvaluationCase, case_id)
            if not c or c.project_id != project_id:
                return ("err", "case not found")
            tid = candidate or c.source_trace_id
            try:
                r = regression.replay_case(s, project_id, case_id, tid)
            except regression.NotFound as e:
                return ("err", str(e))
            return ("ok", {"verdict": r.verdict, "candidate_trace_id": r.candidate_trace_id, "detail": r.detail})

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)
    return payload
