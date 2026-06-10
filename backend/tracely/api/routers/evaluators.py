"""Evaluator (= evaluation column) management: CRUD + the template library + AI generation.

An evaluator row IS a column in the trace table: `score_name` is the stable key results are
stored under, `level` picks the row granularity (CONVERSATION / AGENT_RUN / SPAN…), and
`config` carries the kind-specific knobs (judge prompt, threshold, output_type, model;
structural check + params). Deleting an evaluator keeps its historical scores (they're keyed
by name in ClickHouse) — the column simply disappears from the grid.

Pure HTTP shaping — all Postgres access lives in `infrastructure.db.repositories`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.domain.evaluation.evaluators import TEMPLATES
from tracely.domain.evaluation.generation import generate_evaluator_config
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Evaluator
from tracely.infrastructure.llm.provider import llm_enabled

router = APIRouter(prefix="/api")

VALID_LEVELS = {"CONVERSATION", "AGENT_RUN", "SPAN", "TOOL", "GENERATION", "CHAIN"}
VALID_KINDS = {"structural", "llm_judge"}


def _evaluator_dict(e: Evaluator) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "description": e.description,
        "kind": e.kind,
        "score_name": e.score_name,
        "level": e.level,
        "enabled": e.enabled,
        "target_agent": e.target_agent,
        "target_env": e.target_env,
        "sampling": e.sampling,
        "config": e.config or {},
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


class EvaluatorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    kind: str = "llm_judge"
    level: str = "AGENT_RUN"
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    score_name: str = Field(default="", max_length=80)


class EvaluatorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    level: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    target_agent: str | None = Field(default=None, max_length=80)
    target_env: str | None = Field(default=None, max_length=32)
    sampling: float | None = Field(default=None, ge=0.0, le=1.0)


class GenerateRequest(BaseModel):
    description: str = Field(min_length=3, max_length=2000)


@router.get("/evaluators")
async def list_evaluators(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            return [_evaluator_dict(e) for e in repo.evaluators_list(s, project_id)]

    return await run_in_threadpool(work)


@router.get("/evaluators/templates")
async def list_templates(project_id: str = Depends(get_project_id)) -> list[dict]:
    """The browse library: every catalog template, flagged with whether this project already
    has it installed (matched by score_name)."""

    def work():
        with SyncSessionLocal() as s:
            installed = repo.evaluator_score_names(s, project_id)
        return [{**t, "installed": t["score_name"] in installed} for t in TEMPLATES]

    return await run_in_threadpool(work)


@router.post("/evaluators/generate")
async def generate_evaluator(
    body: GenerateRequest, project_id: str = Depends(get_project_id)
) -> dict:
    """Natural-language description → a draft evaluator config (the UI pre-fills the manual
    form with it; nothing is persisted here)."""
    if not llm_enabled():
        raise HTTPException(
            status_code=503,
            detail="AI generation needs the judge LLM configured (set OPENROUTER_API_KEY).",
        )
    try:
        return await run_in_threadpool(generate_evaluator_config, body.description)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"generation failed: {exc}") from None


@router.post("/evaluators")
async def create_evaluator(
    body: EvaluatorCreate, project_id: str = Depends(get_project_id)
) -> dict:
    if body.kind not in VALID_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(VALID_KINDS)}")
    if body.level not in VALID_LEVELS:
        raise HTTPException(status_code=400, detail=f"level must be one of {sorted(VALID_LEVELS)}")

    def work():
        with SyncSessionLocal() as s:
            e = repo.evaluator_create(
                s, project_id,
                name=body.name, description=body.description, kind=body.kind,
                level=body.level, enabled=body.enabled, config=body.config or {},
                score_name=body.score_name,
            )
            return _evaluator_dict(e)

    return await run_in_threadpool(work)


@router.patch("/evaluators/{evaluator_id}")
async def update_evaluator(
    evaluator_id: str, body: EvaluatorUpdate, project_id: str = Depends(get_project_id)
) -> dict:
    if body.level is not None and body.level not in VALID_LEVELS:
        raise HTTPException(status_code=400, detail=f"level must be one of {sorted(VALID_LEVELS)}")

    def work():
        with SyncSessionLocal() as s:
            e = repo.evaluator_update(
                s, project_id, evaluator_id, body.model_dump(exclude_unset=True)
            )
            return None if e is None else _evaluator_dict(e)

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="evaluator not found")
    return res


@router.delete("/evaluators/{evaluator_id}")
async def delete_evaluator(
    evaluator_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    def work():
        with SyncSessionLocal() as s:
            return repo.evaluator_delete(s, project_id, evaluator_id)

    ok = await run_in_threadpool(work)
    if not ok:
        raise HTTPException(status_code=404, detail="evaluator not found")
    return {"deleted": evaluator_id}
