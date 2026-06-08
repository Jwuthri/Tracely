"""Tracely API entrypoint — `uvicorn tracely.api.main:app`."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tracely.api.routers import (
    analytics,
    cases,
    clusters,
    gate,
    health,
    otlp,
    search,
    sessions,
    traces,
)

app = FastAPI(title="Tracely API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # The web app fetches the API only via same-origin Next proxy routes, but allow direct
    # browser calls from a local dev frontend on any port (TRACELY_WEB_PORT can remap 3000).
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(otlp.router)
app.include_router(traces.router)
app.include_router(sessions.router)
app.include_router(search.router)
app.include_router(cases.router)
app.include_router(gate.router)
app.include_router(clusters.router)
app.include_router(analytics.router)
