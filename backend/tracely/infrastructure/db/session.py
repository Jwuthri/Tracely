"""FastAPI / context-manager friendly session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from tracely.infrastructure.db.engine import AsyncSessionLocal, SyncSessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


def sync_session() -> Iterator[Session]:
    with SyncSessionLocal() as session:
        yield session
