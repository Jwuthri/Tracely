"""Tracely API entrypoint — `uvicorn tracely.api.main:app`."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tracely.api.routers import (
    analytics,
    cases,
    calibration,
    clusters,
    evaluations,
    evaluators,
    gate,
    health,
    meta_analysis,
    otlp,
    search,
    sessions,
    traces,
)
from tracely.api.routers import auth as auth_router
from tracely.auth import AuthError
from tracely.config import settings
from tracely.infrastructure.clickhouse.client import close_async_client
from tracely.infrastructure.db.engine import async_engine, sync_engine
from tracely.log_config import configure_logging

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("api_startup", env=settings.tracely_env, auth_mode=settings.auth_mode)
    yield
    # Release pooled connections so reloads/restarts/shutdowns don't leak sockets + file descriptors.
    await close_async_client()
    await async_engine.dispose()
    sync_engine.dispose()


app = FastAPI(title="Tracely API", version="0.1.0", lifespan=lifespan)

# The web app fetches the API via same-origin Next proxy routes. Allow direct browser calls from a
# local dev frontend on any port (dev/staging only — never punch a localhost hole in prod), plus the
# hosted frontend origin when configured (CORS for SaaS).
_is_prod = settings.tracely_env.lower() in ("prod", "production")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin] if settings.frontend_origin else [],
    allow_origin_regex=None if _is_prod else r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AuthError)
async def _auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log the unhandled error with request context (instead of a bare 500 with
    no trace) and return a generic body that never leaks internals to the client."""
    log.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(health.router)
app.include_router(otlp.router)
app.include_router(traces.router)
app.include_router(sessions.router)
app.include_router(search.router)
app.include_router(cases.router)
app.include_router(gate.router)
app.include_router(clusters.router)
app.include_router(analytics.router)
app.include_router(evaluators.router)
app.include_router(evaluations.router)
app.include_router(meta_analysis.router)
app.include_router(calibration.router)

# Auth: /auth/me + /auth/logout always; mode-specific endpoints gated by AUTH_MODE.
app.include_router(auth_router.common_router)
if settings.auth_mode == "local":
    app.include_router(auth_router.local_router)
elif settings.auth_mode == "clerk":
    app.include_router(auth_router.clerk_router)
