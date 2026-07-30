"""Failure cluster endpoints: list, detail, rebuild, promote, ignore.

Slim wrapper: HTTP shaping only. Business logic lives in:
- `domain/evaluation/evaluator_suggestion.py` (suggested evaluator generation)
- `domain/failure/histogram.py` (occurrence bucketing)
- `infrastructure/db/repositories.py` (Postgres queries)
- `infrastructure/clickhouse/trace_reader.py:TraceReader.member_meta` (CH read)
- `services/regression_service.py:RegressionService.promote_trace` (promote action)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.domain.evaluation.evaluator_suggestion import suggest_evaluator
from tracely.domain.failure.histogram import histogram
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Agent, FailureCluster
from tracely.infrastructure.llm import provider
from tracely.infrastructure.llm.embeddings import embeddings_enabled
from tracely.infrastructure.llm.provider import llm_enabled
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


@router.post("/clusters/rebuild")
async def rebuild(project_id: str = Depends(get_project_id)) -> dict:
    # Embeddings and the analysis agents both go through OpenRouter (OPENAI_API_KEY is only a
    # fallback for embeddings on older deployments).
    with provider.use_project_key(project_id):
        ready = embeddings_enabled() and llm_enabled()
    if not ready:
        raise HTTPException(
            status_code=400,
            detail="Set OPENROUTER_API_KEY (embeddings + agent analysis) to enable cluster rebuild",
        )
    rebuild_clusters_task.delay(project_id)
    return {"status": "started"}


@router.get("/clusters")
async def list_clusters(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            return [
                _cluster_dict(cl, slug) for cl, slug in repo.clusters_list_with_agent(s, project_id)
            ]

    return await run_in_threadpool(work)


@router.get("/clusters/{cluster_id}")
async def get_cluster(cluster_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        reader = TraceReader()
        with SyncSessionLocal() as s:
            cl = repo.cluster_get(s, project_id, cluster_id)
            if not cl:
                return None
            mem = repo.cluster_members(s, cl.id)
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
            d["histogram"] = histogram([meta[m.trace_id]["ts"] for m in mem if m.trace_id in meta])
            d["suggested_evaluator"] = suggest_evaluator(cl.label, cl.taxonomy)
            return d

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    return res


@router.post("/clusters/{cluster_id}/promote")
async def promote_cluster(cluster_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            cl = repo.cluster_get(s, project_id, cluster_id)
            if not cl:
                return ("err", "cluster not found")
            med = repo.cluster_medoid(s, cl.id)
            if not med:
                return ("err", "cluster has no members")
            try:
                case = RegressionService(s).promote_trace(project_id, med.trace_id, title=cl.label)
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


class DeleteClustersBody(BaseModel):
    cluster_ids: list[str]


@router.delete("/clusters")
async def delete_clusters(
    body: DeleteClustersBody, project_id: str = Depends(get_project_id)
) -> dict:
    """Delete clusters (multi-select in the UI). Clusters are derived from the traces, so a later
    Analyze re-forms any issue whose failing traces still exist — this prunes noise and orphans."""
    ids = [c for c in dict.fromkeys(body.cluster_ids) if c]
    if not ids:
        raise HTTPException(status_code=400, detail="no clusters given")

    def work():
        with SyncSessionLocal() as s:
            return repo.clusters_delete(s, project_id, ids)

    return {"deleted": await run_in_threadpool(work)}


@router.post("/clusters/{cluster_id}/ignore")
async def ignore_cluster(cluster_id: str, project_id: str = Depends(get_project_id)) -> dict:
    def work():
        with SyncSessionLocal() as s:
            cl = repo.cluster_get(s, project_id, cluster_id)
            if not cl:
                return None
            cl.status = "IGNORED"
            s.commit()
            return {"status": cl.status}

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="cluster not found")
    return res
