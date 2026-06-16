"""Monitor CRUD + `/test`: threshold rules over the regression-loop metrics already in CH.

Pure HTTP shaping — Postgres queries live in `infrastructure.db.repositories`, ClickHouse + alert
dispatch live in `services.monitoring_service`. The `/test` endpoint runs ONE evaluation against
the live samples (no scheduling) so the user can see "what does this look like right now?" before
arming the monitor.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Monitor
from tracely.services.monitoring_service import MonitoringService

router = APIRouter(prefix="/api")

VALID_CONDITION_TYPES = {"fail_rate_over", "score_below", "trace_failure_rate"}
VALID_CHANNEL_TYPES = {"slack", "webhook"}


def _monitor_dict(m: Monitor) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "description": m.description,
        "target_agent": m.target_agent,
        "condition": m.condition or {},
        "channels": m.channels or [],
        "enabled": m.enabled,
        "min_interval_seconds": m.min_interval_seconds,
        "last_evaluated_at": m.last_evaluated_at.isoformat() if m.last_evaluated_at else None,
        "last_fired_at": m.last_fired_at.isoformat() if m.last_fired_at else None,
        "last_fired_summary": m.last_fired_summary,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _validate_condition(cond: dict) -> None:
    cond_type = (cond or {}).get("type")
    if cond_type not in VALID_CONDITION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"condition.type must be one of {sorted(VALID_CONDITION_TYPES)}",
        )
    # Each type has a numeric threshold; `score_name` is required for score-based types.
    if cond_type in ("fail_rate_over", "score_below") and not (cond.get("score_name") or "").strip():
        raise HTTPException(
            status_code=400, detail=f"condition.score_name is required for {cond_type}"
        )
    if cond.get("threshold") is None:
        raise HTTPException(status_code=400, detail="condition.threshold is required")


def _validate_channels(channels: list[dict]) -> None:
    for ch in channels or []:
        ctype = (ch or {}).get("type")
        if ctype not in VALID_CHANNEL_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"channel.type must be one of {sorted(VALID_CHANNEL_TYPES)}",
            )
        if not (ch.get("url") or "").strip():
            raise HTTPException(status_code=400, detail="channel.url is required")


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    target_agent: str = Field(default="", max_length=80)
    condition: dict[str, Any]
    channels: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    min_interval_seconds: int = Field(default=900, ge=0, le=86400)


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=400)
    target_agent: str | None = Field(default=None, max_length=80)
    condition: dict[str, Any] | None = None
    channels: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    min_interval_seconds: int | None = Field(default=None, ge=0, le=86400)


@router.get("/monitors")
async def list_monitors(project_id: str = Depends(get_project_id)) -> list[dict]:
    def work():
        with SyncSessionLocal() as s:
            return [_monitor_dict(m) for m in repo.monitors_list(s, project_id)]

    return await run_in_threadpool(work)


@router.post("/monitors")
async def create_monitor(
    body: MonitorCreate, project_id: str = Depends(get_project_id)
) -> dict:
    _validate_condition(body.condition)
    _validate_channels(body.channels)

    def work():
        with SyncSessionLocal() as s:
            m = repo.monitor_create(
                s, project_id,
                name=body.name, description=body.description, target_agent=body.target_agent,
                condition=body.condition, channels=body.channels, enabled=body.enabled,
                min_interval_seconds=body.min_interval_seconds,
            )
            return _monitor_dict(m)

    return await run_in_threadpool(work)


@router.patch("/monitors/{monitor_id}")
async def update_monitor(
    monitor_id: str,
    body: MonitorUpdate,
    project_id: str = Depends(get_project_id),
) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if "condition" in patch:
        _validate_condition(patch["condition"])
    if "channels" in patch:
        _validate_channels(patch["channels"])

    def work():
        with SyncSessionLocal() as s:
            m = repo.monitor_update(s, project_id, monitor_id, patch)
            return None if m is None else _monitor_dict(m)

    res = await run_in_threadpool(work)
    if res is None:
        raise HTTPException(status_code=404, detail="monitor not found")
    return res


@router.delete("/monitors/{monitor_id}")
async def delete_monitor(
    monitor_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    def work():
        with SyncSessionLocal() as s:
            return repo.monitor_delete(s, project_id, monitor_id)

    ok = await run_in_threadpool(work)
    if not ok:
        raise HTTPException(status_code=404, detail="monitor not found")
    return {"deleted": monitor_id}


@router.post("/monitors/{monitor_id}/test")
async def test_monitor(
    monitor_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """Evaluate the monitor right now against the live window (and dispatch alerts if the
    condition fires + the dedup interval has elapsed). The same code path the periodic beat uses
    — so a passing test means the periodic run will work too."""
    res = await MonitoringService().evaluate_one(project_id, monitor_id)
    if res is None:
        raise HTTPException(status_code=404, detail="monitor not found")
    return res
