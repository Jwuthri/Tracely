"""Failure cluster endpoints: list, detail, promote (-> regression case), ignore."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from tracely import regression
from tracely.api.auth import get_project_id
from tracely.db import SyncSessionLocal
from tracely.models import Agent, ClusterMember, FailureCluster

router = APIRouter(prefix="/api")


def _cluster_dict(cl: FailureCluster, agent_slug: str | None = None, members: list | None = None) -> dict[str, Any]:
    d = {
        "id": cl.id,
        "agent_id": cl.agent_id,
        "agent": agent_slug,
        "label": cl.label,
        "taxonomy": cl.taxonomy,
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
            members = [{"trace_id": m.trace_id, "is_medoid": m.is_medoid} for m in mem]
            agent = s.get(Agent, cl.agent_id)
            return _cluster_dict(cl, agent.slug if agent else None, members)

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
                case = regression.promote_trace(s, project_id, med.trace_id)
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
