"""Resolve the project from an ingest key (Authorization: Bearer <key> or X-Tracely-Key)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.db import get_session
from tracely.models import IngestKey


async def get_project_id(
    authorization: str | None = Header(default=None),
    x_tracely_key: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> str:
    key = None
    if authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    key = key or x_tracely_key
    if not key:
        raise HTTPException(status_code=401, detail="missing ingest key")
    row = (
        await session.execute(select(IngestKey).where(IngestKey.key == key))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=401, detail="invalid ingest key")
    return row.project_id
