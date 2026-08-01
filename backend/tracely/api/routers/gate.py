"""CI/CD gate endpoints: run a gate, list gates, gate detail, fetch the replay suite.

Pure HTTP shaping — Postgres queries live in `infrastructure.db.repositories`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Agent, GateRun
from tracely.services.gate_service import GateService
from tracely.workers.tasks import run_scenario_gate_task

router = APIRouter(prefix="/api")


def _gate_dict(
    g: GateRun, agent_slug: str | None = None, cases: list | None = None
) -> dict[str, Any]:
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
        "latency_ms": g.latency_ms,
        "total_tokens": g.total_tokens,
        "warnings": g.warnings or [],
        "created_at": g.created_at.isoformat() if g.created_at else None,
        # CI polls a simulated gate until this is set — RUNNING with no finish means keep waiting.
        "finished_at": g.finished_at.isoformat() if g.finished_at else None,
    }
    if cases is not None:
        d["cases"] = cases
    return d


def _cases(session, gate_id: str) -> list[dict]:
    return [
        {
            "title": title,
            "verdict": gc.verdict,
            "candidate_trace_id": gc.candidate_trace_id,
            "detail": gc.detail,
            "evaluation_case_id": gc.evaluation_case_id,
            "scenario_id": gc.scenario_id,
        }
        for gc, title in repo.gate_cases_with_titles(session, gate_id)
    ]


@router.post("/gate")
async def run_gate(
    project_id: str = Depends(get_project_id), body: dict = Body(default={})
) -> dict:
    agent_ref = body.get("agent")
    env = body.get("env") or "ci"
    git_ref = body.get("git_ref") or ""
    pr_number = body.get("pr_number")
    candidates = body.get("candidates") or None  # {case_id: trace_id} from `tracely replay`
    if not agent_ref:
        raise HTTPException(status_code=400, detail="agent required")

    def work():
        with SyncSessionLocal() as s:
            gate_svc = GateService(s)
            aid = gate_svc.resolve_agent_id(project_id, agent_ref)
            if not aid:
                return ("err", f"agent '{agent_ref}' not found")
            g = gate_svc.run_gate(
                project_id, aid, env=env, git_ref=git_ref, pr_number=pr_number,
                candidates=candidates,
            )
            agent = s.get(Agent, aid)
            return ("ok", _gate_dict(g, agent.slug if agent else None, _cases(s, g.id)))

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)
    return payload


@router.post("/gate/simulate")
async def run_simulated_gate(
    project_id: str = Depends(get_project_id), body: dict = Body(default={})
) -> dict:
    """Start a gate that drives the agent's enabled scenarios against its registered endpoint.

    Returns immediately with a RUNNING gate id: emulated conversations make real HTTP calls and
    then wait on the eval pipeline, so this is minutes of work. CI polls `GET /api/gates/{id}`
    until `finished_at` is set.
    """
    agent_ref = body.get("agent")
    if not agent_ref:
        raise HTTPException(status_code=400, detail="agent required")
    min_pass_rate = body.get("min_pass_rate")

    def work():
        with SyncSessionLocal() as s:
            aid = GateService(s).resolve_agent_id(project_id, agent_ref)
            if not aid:
                return ("err", f"agent '{agent_ref}' not found")
            gate = GateRun(
                id=str(uuid.uuid4()), project_id=project_id, agent_id=aid,
                env=body.get("env") or "ci", git_ref=body.get("git_ref") or "",
                pr_number=body.get("pr_number"), status="RUNNING",
            )
            s.add(gate)
            s.commit()
            return ("ok", (gate.id, aid, gate.env, gate.git_ref, gate.pr_number))

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)

    gate_id, aid, env, git_ref, pr_number = payload
    run_scenario_gate_task.delay(
        project_id, aid, gate_id, env, git_ref, pr_number,
        float(min_pass_rate) if min_pass_rate is not None else None,
    )
    return {"id": gate_id, "status": "RUNNING", "agent": agent_ref, "env": env}


@router.get("/gate/suite")
async def gate_suite(agent: str, project_id: str = Depends(get_project_id)) -> dict:
    """The promoted regression suite (+ recorded inputs) for an agent — what `tracely replay`
    runs."""
    def work():
        with SyncSessionLocal() as s:
            gate_svc = GateService(s)
            aid = gate_svc.resolve_agent_id(project_id, agent)
            if not aid:
                return None
            return {
                "agent": agent,
                "agent_id": aid,
                "cases": gate_svc.replay_suite(project_id, aid),
            }

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail=f"agent '{agent}' not found")
    return res


@router.get("/gates")
async def list_gates(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            return [_gate_dict(g, slug) for g, slug in repo.gates_list_with_agent(s, project_id)]

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
