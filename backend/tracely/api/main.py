"""Tracely API entrypoint — `uvicorn tracely.api.main:app`."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tracely.api.routers import (
    analytics,
    cases,
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

app = FastAPI(title="Tracely API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # The web app fetches the API via same-origin Next proxy routes. Allow direct browser calls from a
    # local dev frontend on any port, plus the hosted frontend origin when configured (CORS for SaaS).
    allow_origins=[settings.frontend_origin] if settings.frontend_origin else [],
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AuthError)
async def _auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


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

# Auth: /auth/me + /auth/logout always; mode-specific endpoints gated by AUTH_MODE.
app.include_router(auth_router.common_router)
if settings.auth_mode == "local":
    app.include_router(auth_router.local_router)
elif settings.auth_mode == "clerk":
    app.include_router(auth_router.clerk_router)
