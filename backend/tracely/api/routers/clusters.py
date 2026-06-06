"""Failure cluster endpoints: list, detail, promote (-> regression case), ignore."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from tracely import clickhouse, regression
from tracely.api.auth import get_project_id
from tracely.config import settings
from tracely.db import SyncSessionLocal
from tracely.models import Agent, ClusterMember, FailureCluster
from tracely.tasks import rebuild_clusters_task
from tracely.textfmt import message_text

router = APIRouter(prefix="/api")


def _member_meta(project_id: str, trace_ids: list[str]) -> dict:
    """Per-member trace facts for the cluster detail: timestamp, latency, and an input snippet."""
    if not trace_ids:
        return {}
    rows = clickhouse.get_client().query(
        "SELECT trace_id, min(start_time) AS ts, "
        "dateDiff('millisecond', min(start_time), max(coalesce(end_time, start_time))) AS lat, "
        "argMinIf(input, start_time, input != '') AS inp "
        "FROM events FINAL WHERE project_id = {p:String} AND trace_id IN {t:Array(String)} "
        "GROUP BY trace_id",
        parameters={"p": project_id, "t": trace_ids},
    ).result_rows
    # only trace_ids still present in events appear here; input is structured message JSON, so
    # surface the readable text (not the raw {"role":...,"content":[...]} blob).
    return {r[0]: {"ts": r[1], "latency_ms": float(r[2]), "input": message_text(r[3])} for r in rows}


def _histogram(timestamps: list, buckets: int = 12) -> list[dict]:
    """Occurrences over time (for the issue histogram), bucketed across [first, last seen]."""
    ts = sorted(t for t in timestamps if t)
    if not ts:
        return []
    lo, hi = ts[0], ts[-1]
    span = (hi - lo).total_seconds()
    if span <= 0:
        return [{"t": lo.isoformat(), "count": len(ts)}]
    width = span / buckets
    counts = [0] * buckets
    for t in ts:
        counts[min(buckets - 1, int((t - lo).total_seconds() / width))] += 1
    return [{"t": (lo + timedelta(seconds=width * i)).isoformat(), "count": counts[i]} for i in range(buckets)]


def _suggest_evaluator(cl: FailureCluster) -> dict:
    """A starting-point evaluator that would catch this failure mode — derived from its mechanism.
    Matches the real evaluator interface so it's a usable draft, not just illustrative."""
    name = (re.sub(r"[^a-z0-9]+", "_", (cl.label or "detected_failure").lower()).strip("_") or "detected_failure")[:48]
    tax = (cl.taxonomy or "").lower()
    if "not executed" in tax or "consistency" in tax:
        code = (
            "def evaluate(ctx):\n"
            '    """Catch runs where a tool was requested by the model but never executed."""\n'
            "    requested = {t for s in ctx.spans for t in (s.get('tool_call_names') or [])}\n"
            "    executed = {s.get('name') for s in ctx.spans if s.get('type') == 'TOOL'}\n"
            "    missing = sorted(requested - executed)\n"
            f"    return {{'name': '{name}', 'verdict': 'FAIL' if missing else 'PASS',\n"
            "            'comment': f'requested but not executed: {missing}' if missing else ''}"
        )
        return {"name": name, "language": "python", "code": code}
    if "error" in tax:
        code = (
            "def evaluate(ctx):\n"
            '    """Catch runs where a tool call errored."""\n'
            "    errs = [s.get('name') for s in ctx.spans if s.get('type') == 'TOOL' and s.get('level') == 'ERROR']\n"
            f"    return {{'name': '{name}', 'verdict': 'FAIL' if errs else 'PASS',\n"
            "            'comment': f'tool error: {errs}' if errs else ''}"
        )
        return {"name": name, "language": "python", "code": code}
    # wrong output / hallucination -> an LLM-judge rubric
    prompt = (
        "You are checking whether the agent's final answer is faithful to its tool results and not "
        "fabricated.\nReturn strict JSON {\"score\": 0..1, \"reason\": \"...\"}.\n\n"
        "User request:\n{{input}}\n\nTool results:\n{{tool_outputs}}\n\nAgent answer:\n{{output}}\n\n"
        "Score LOW if the answer contradicts, ignores, or invents detail beyond the tool results."
    )
    return {"name": name, "language": "prompt", "code": prompt}


@router.post("/clusters/rebuild")
async def rebuild(project_id: str = Depends(get_project_id)) -> dict:
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="Set OPENAI_API_KEY to enable embedding + agent analysis")
    rebuild_clusters_task.delay(project_id)
    return {"status": "started"}


def _cluster_dict(cl: FailureCluster, agent_slug: str | None = None, members: list | None = None) -> dict[str, Any]:
    d = {
        "id": cl.id,
        "agent_id": cl.agent_id,
        "agent": agent_slug,
        "label": cl.label,
        "taxonomy": cl.taxonomy,
        "description": cl.description,
        "proposed_fix": cl.proposed_fix,
        "severity": cl.severity,
        "method": cl.method,
        "count": cl.count,
        "status": cl.status,
        "candidate_case_id": cl.candidate_case_id,
        "signature": cl.signature,
        "first_seen_at": cl.first_seen_at.isoformat() if cl.first_seen_at else None,
        "last_seen_at": cl.last_seen_at.isoformat() if cl.last_seen_at else None,
    }
    if members is not None:
        d["members"] = members
    return d


def _medoid(session, cluster_id: str) -> ClusterMember | None:
    return (
        session.execute(
            select(ClusterMember)
            .where(ClusterMember.cluster_id == cluster_id)
            .order_by(desc(ClusterMember.is_medoid), ClusterMember.added_at)
        )
        .scalars()
        .first()
    )


@router.get("/clusters")
async def list_clusters(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            rows = s.execute(
                select(FailureCluster, Agent.slug)
                .join(Agent, FailureCluster.agent_id == Agent.id)
                .where(FailureCluster.project_id == project_id)
                .order_by(desc(FailureCluster.count), desc(FailureCluster.last_seen_at))
            ).all()
            return [_cluster_dict(cl, slug) for cl, slug in rows]

    return await run_in_threadpool(work)


@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            cl = s.get(FailureCluster, cluster_id)
            if not cl or cl.project_id != project_id:
                return None
            mem = (
                s.execute(
                    select(ClusterMember)
                    .where(ClusterMember.cluster_id == cl.id)
                    .order_by(desc(ClusterMember.is_medoid), ClusterMember.added_at)
                )
                .scalars()
                .all()
            )
            meta = _member_meta(project_id, [m.trace_id for m in mem])
            # drop members whose trace no longer exists in events (wiped, or aged out by ClickHouse
            # TTL retention) so the detail shows real linked traces instead of blank rows.
            members = [
                {
                    "trace_id": m.trace_id,
                    "is_medoid": m.is_medoid,
                    "summary": m.summary,
                    "input": meta[m.trace_id].get("input", ""),
                    "latency_ms": meta[m.trace_id].get("latency_ms", 0.0),
                }
                for m in mem
                if m.trace_id in meta
            ]
            agent = s.get(Agent, cl.agent_id)
            d = _cluster_dict(cl, agent.slug if agent else None, members)
            d["histogram"] = _histogram([meta[m.trace_id]["ts"] for m in mem if m.trace_id in meta])
            d["suggested_evaluator"] = _suggest_evaluator(cl)
            return d

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    return res


@router.post("/clusters/{cluster_id}/promote")
async def promote_cluster(cluster_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            cl = s.get(FailureCluster, cluster_id)
            if not cl or cl.project_id != project_id:
                return ("err", "cluster not found")
            med = _medoid(s, cl.id)
            if not med:
                return ("err", "cluster has no members")
            try:
                case = regression.promote_trace(s, project_id, med.trace_id, title=cl.label)
            except regression.NotFound as e:
                return ("err", str(e))
            cl.status = "PROMOTED"
            cl.candidate_case_id = case.id
            s.commit()
            return ("ok", {"case_id": case.id, "cluster_status": cl.status})

    status, payload = await run_in_threadpool(work)
    if status == "err":
        raise HTTPException(status_code=404, detail=payload)
    return payload


@router.post("/clusters/{cluster_id}/ignore")
async def ignore_cluster(cluster_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            cl = s.get(FailureCluster, cluster_id)
            if not cl or cl.project_id != project_id:
                return None
            cl.status = "IGNORED"
            s.commit()
            return {"status": cl.status}

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    return res
