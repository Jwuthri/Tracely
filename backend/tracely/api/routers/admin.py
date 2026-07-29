"""Project-level destructive maintenance: wipe the workspace's data.

Pure HTTP shaping — ClickHouse deletes live in `infrastructure.clickhouse.deletes`, Postgres in
`infrastructure.db.repositories`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.clickhouse import deletes
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal

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
