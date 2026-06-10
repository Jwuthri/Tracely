"""Trends & analytics: time-series + roll-ups over traces, failures, gates, and clusters.

Pure HTTP shaping — ClickHouse series live in `infrastructure.clickhouse.async_reader`,
Postgres rollups in `infrastructure.db.repositories`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.clickhouse import async_reader
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal

router = APIRouter(prefix="/api")


@router.get("/trends")
async def trends(days: int = 14, project_id: str = Depends(get_project_id)) -> dict:
    days = max(1, min(days, 90))
    daily = await async_reader.daily_trace_failures(project_id, days)
    total_traces, total_failures = await async_reader.trace_failure_totals(project_id)

    def registry():
        with SyncSessionLocal() as s:
            return repo.gate_cluster_trends(s, project_id)

    rollups = await run_in_threadpool(registry)
    return {
        "days": days,
        "daily": daily,
        "gates_daily": rollups.pop("gates_daily"),
        "summary": {
            "total_traces": total_traces,
            "total_failures": total_failures,
            "failure_rate": round(total_failures / total_traces, 3) if total_traces else 0.0,
            **rollups,
        },
    }
