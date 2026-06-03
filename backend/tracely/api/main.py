"""Tracely API entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tracely.api.routers import cases, clusters, gate, health, otlp, reads

app = FastAPI(title="Tracely API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(otlp.router)
app.include_router(reads.router)
app.include_router(cases.router)
app.include_router(gate.router)
app.include_router(clusters.router)
