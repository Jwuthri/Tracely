"""Failure cluster endpoints: list, detail, rebuild, promote, ignore.

Slim wrapper: serialization + DB read/write only. Business logic lives in:
- `domain/evaluation/evaluator_suggestion.py` (suggested evaluator generation)
- `domain/failure/histogram.py` (occurrence bucketing)
- `infrastructure/clickhouse/trace_reader.py:TraceReader.member_meta` (CH read)
- `services/regression_service.py:RegressionService.promote_trace` (promote action)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.config import settings
from tracely.domain.evaluation.evaluator_suggestion import suggest_evaluator
from tracely.domain.failure.histogram import histogram
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Agent, ClusterMember, FailureCluster
from tracely.infrastructure.text import message_text
from tracely.services.regression_service import NotFound, RegressionService
from tracely.workers.tasks import rebuild_clusters_task

router = APIRouter(prefix="/api")


def _cluster_dict(
    cl: FailureCluster, agent_slug: str | None = None, members: list | None = None
) -> dict[str, Any]:
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


@router.post("/clusters/rebuild")
async def rebuild(project_id: str = Depends(get_project_id)) -> dict:
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="Set OPENAI_API_KEY to enable embedding + agent analysis",
        )
    rebuild_clusters_task.delay(project_id)
    return {"status": "started"}


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
        reader = TraceReader()
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
            meta = reader.member_meta(project_id, [m.trace_id for m in mem])
            # Drop members whose trace no longer exists in events (wiped, or aged out by
            # ClickHouse TTL retention) so the detail shows real linked traces.
            members = [
                {
                    "trace_id": m.trace_id,
                    "is_medoid": m.is_medoid,
                    "summary": m.summary,
                    "input": message_text(meta[m.trace_id].get("input", "")),
                    "latency_ms": meta[m.trace_id].get("latency_ms", 0.0),
                }
                for m in mem
                if m.trace_id in meta
            ]
            agent = s.get(Agent, cl.agent_id)
            d = _cluster_dict(cl, agent.slug if agent else None, members)
            d["histogram"] = histogram(
                [meta[m.trace_id]["ts"] for m in mem if m.trace_id in meta]
            )
            d["suggested_evaluator"] = suggest_evaluator(cl.label, cl.taxonomy)
            return d

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    return res


@router.post("/clusters/{cluster_id}/promote")
async def promote_cluster(
    cluster_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    def work():
        with SyncSessionLocal() as s:
            cl = s.get(FailureCluster, cluster_id)
            if not cl or cl.project_id != project_id:
                return ("err", "cluster not found")
            med = _medoid(s, cl.id)
            if not med:
                return ("err", "cluster has no members")
            try:
                case = RegressionService(s).promote_trace(
                    project_id, med.trace_id, title=cl.label
                )
            except NotFound as e:
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
async def ignore_cluster(
    cluster_id: str, project_id: str = Depends(get_project_id)
) -> dict:
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
