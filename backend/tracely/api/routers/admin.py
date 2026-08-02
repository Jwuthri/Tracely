"""Project-level settings: destructive maintenance (wipe the workspace's data) + the workspace's
own OpenRouter key for LLM eval spend.

Pure HTTP shaping — ClickHouse deletes live in `infrastructure.clickhouse.deletes`, Postgres in
`infrastructure.db.repositories`, encryption in `infrastructure.llm.provider`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.config import settings
from tracely.infrastructure.clickhouse import deletes
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.llm import provider

router = APIRouter(prefix="/api")

CONFIRM = "DELETE"


class WipeBody(BaseModel):
    confirm: str = ""


@router.delete("/project/data")
async def wipe_project_data(body: WipeBody, project_id: str = Depends(get_project_id)) -> dict:
    """Delete every trace, score and everything derived from them in this project.

    Keeps the project itself, ingest keys, users, evaluators and monitors — your configuration, so
    the workspace is immediately usable again. Send `{"confirm": "DELETE"}`; anything else is a
    400, which is the whole guard against a stray curl.

    Not transactional across the two stores: ClickHouse goes first, then Postgres. If the Postgres
    half fails you're left with derived rows pointing at deleted traces — run it again, it's
    idempotent.
    """
    if body.confirm != CONFIRM:
        raise HTTPException(status_code=400, detail=f"confirm must be exactly '{CONFIRM}'")

    events = await deletes.delete_project_events(project_id)

    def work():
        with SyncSessionLocal() as s:
            return repo.project_data_delete(s, project_id)

    registry = await run_in_threadpool(work)
    return {"deleted": {**events, **registry}}


@router.post("/project/seed")
async def seed_project_demo(project_id: str = Depends(get_project_id)) -> dict:
    """Populate this workspace with the demo dataset — traces, clusters, cases, gates, scenarios.

    A dev convenience so an empty install (or one you just wiped) has something to look at without
    dropping to a terminal. Queued, not inline: the seeder drives the product through its own HTTP
    API and takes minutes. Idempotent, so a double-click just costs time.
    """
    if settings.tracely_env == "prod":
        raise HTTPException(status_code=403, detail="seeding is disabled in prod")

    def key():
        with SyncSessionLocal() as s:
            return repo.project_ingest_key(s, project_id)

    ingest_key = await run_in_threadpool(key)
    if not ingest_key:
        raise HTTPException(status_code=400, detail="this workspace has no ingest key")

    script = Path(__file__).resolve().parents[4] / "scripts" / "seed_demo.py"
    if not script.exists():  # trimmed image — seeding is a dev convenience only
        raise HTTPException(status_code=501, detail="seed_demo.py is not present in this image")

    # Detached child of the API process, NOT a Celery task. The seeder pushes traces and then waits
    # for them to be ingested, clustered and evaluated — all of which are worker jobs. Under the
    # default `--pool=solo --concurrency=1` a seed task would hold the worker's only slot and wait
    # on work queued behind itself, so it deadlocked and gave up after phase 2 with cases, gates
    # and scenarios empty. Running it here leaves the worker free to do exactly that work.
    subprocess.Popen(  # noqa: S603
        [sys.executable, str(script)],
        env={**os.environ, "TRACELY_API": settings.internal_api_url, "TRACELY_KEY": ingest_key},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    return {"queued": True}


# ── workspace OpenRouter key ──────────────────────────────────────────────────


class OpenRouterKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)


class OpenRouterKeyOut(BaseModel):
    configured: bool


@router.get("/project/llm-key", response_model=OpenRouterKeyOut)
async def get_llm_key(project_id: str = Depends(get_project_id)) -> OpenRouterKeyOut:
    def work() -> bool:
        with SyncSessionLocal() as s:
            proj = repo.project_get(s, project_id)
            return bool(proj and proj.openrouter_api_key_encrypted)

    return OpenRouterKeyOut(configured=await run_in_threadpool(work))


@router.put("/project/llm-key", response_model=OpenRouterKeyOut)
async def set_llm_key(
    body: OpenRouterKeyIn, project_id: str = Depends(get_project_id)
) -> OpenRouterKeyOut:
    """Set this workspace's own OpenRouter key — every LLM eval call for this project (judge,
    failure intelligence, meta-analysis, rolling summary) then bills to it instead of the
    server-wide key. The key itself is never returned again; only whether one is configured."""
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="api_key is required")
    try:
        encrypted = provider.encrypt_project_key(key)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None

    def work() -> bool:
        with SyncSessionLocal() as s:
            return repo.project_set_openrouter_key(s, project_id, encrypted)

    if not await run_in_threadpool(work):
        raise HTTPException(status_code=404, detail="project not found")
    provider.invalidate_project_key(project_id)
    return OpenRouterKeyOut(configured=True)


@router.delete("/project/llm-key", response_model=OpenRouterKeyOut)
async def clear_llm_key(project_id: str = Depends(get_project_id)) -> OpenRouterKeyOut:
    """Clear the workspace key — LLM eval calls fall back to the server-wide key."""

    def work() -> bool:
        with SyncSessionLocal() as s:
            return repo.project_set_openrouter_key(s, project_id, None)

    await run_in_threadpool(work)
    provider.invalidate_project_key(project_id)
    return OpenRouterKeyOut(configured=False)
