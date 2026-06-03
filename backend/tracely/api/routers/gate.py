"""CI/CD gate endpoints: run a gate, list gates, gate detail."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from tracely import gate as gatesvc
from tracely.api.auth import get_project_id
from tracely.db import SyncSessionLocal
from tracely.models import Agent, EvaluationCase, GateCase, GateRun

router = APIRouter(prefix="/api")


def _gate_dict(g: GateRun, agent_slug: str | None = None, cases: list | None = None) -> dict[str, Any]:
    d = {
        "id": g.id,
        "agent_id": g.agent_id,
        "agent": agent_slug,
        "env": g.env,
        "git_ref": g.git_ref,
        "pr_number": g.pr_number,
        "status": g.status,
        "total": g.total,
        "passed": g.passed,
        "failed": g.failed,
        "skipped": g.skipped,
        "created_at": g.created_at.isoformat() if g.created_at else None,
    }
    if cases is not None:
        d["cases"] = cases
    return d


def _cases(session, gate_id: str) -> list[dict]:
    rows = session.execute(
        select(GateCase, EvaluationCase.title)
        .join(EvaluationCase, GateCase.evaluation_case_id == EvaluationCase.id)
        .where(GateCase.gate_run_id == gate_id)
    ).all()
    return [
        {
            "title": title,
            "verdict": gc.verdict,
            "candidate_trace_id": gc.candidate_trace_id,
            "detail": gc.detail,
            "evaluation_case_id": gc.evaluation_case_id,
        }
        for gc, title in rows
    ]


@router.post("/gate")
async def run_gate(project_id: str = Depends(get_project_id), body: dict = Body(default={})) -> dict:
    agent_ref = body.get("agent")
    env = body.get("env") or "ci"
    git_ref = body.get("git_ref") or ""
    pr_number = body.get("pr_number")
    if not agent_ref:
        raise HTTPException(status_code=400, detail="agent required")

    def work():
        with SyncSessionLocal() as s:
            aid = gatesvc.resolve_agent_id(s, project_id, agent_ref)
            if not aid:
                return ("err", f"agent '{agent_ref}' not found")
            g = gatesvc.run_gate(s, project_id, aid, env=env, git_ref=git_ref, pr_number=pr_number)
            agent = s.get(Agent, aid)
            return ("ok", _gate_dict(g, agent.slug if agent else None, _cases(s, g.id)))

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)
    return payload


@router.get("/gates")
async def list_gates(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            rows = s.execute(
                select(GateRun, Agent.slug)
                .join(Agent, GateRun.agent_id == Agent.id)
                .where(GateRun.project_id == project_id)
                .order_by(desc(GateRun.created_at))
            ).all()
            return [_gate_dict(g, slug) for g, slug in rows]

    return await run_in_threadpool(work)


@router.get("/gates/{gate_id}")
async def get_gate(gate_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            g = s.get(GateRun, gate_id)
            if not g or g.project_id != project_id:
                return None
            agent = s.get(Agent, g.agent_id)
            return _gate_dict(g, agent.slug if agent else None, _cases(s, g.id))

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="gate not found")
    return res
