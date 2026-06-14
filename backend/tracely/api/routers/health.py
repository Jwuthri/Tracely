"""Health endpoint — a real readiness probe, not a static `ok`.

The read API can't serve a request without ClickHouse (traces/scores) and Postgres (registry), so
`/health` probes both and returns 503 when either is unreachable. The old static `{"status":"ok"}`
meant a backend with a dead DB pool reported healthy and kept taking traffic — the orchestrator
(docker/Railway healthcheck) could never route around it.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from tracely.infrastructure.clickhouse.client import get_async_client
from tracely.infrastructure.db.engine import AsyncSessionLocal

router = APIRouter()
log = structlog.get_logger()


@router.get("/health")
async def health() -> JSONResponse:
    deps: dict[str, str] = {}

    try:
        client = await get_async_client()
        deps["clickhouse"] = "ok" if await client.ping() else "error"
    except Exception as exc:  # unreachable / auth / pool exhausted
        log.warning("health_clickhouse_failed", error=str(exc))
        deps["clickhouse"] = "error"

    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
        deps["postgres"] = "ok"
    except Exception as exc:
        log.warning("health_postgres_failed", error=str(exc))
        deps["postgres"] = "error"

    healthy = all(v == "ok" for v in deps.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "dependencies": deps},
    )
