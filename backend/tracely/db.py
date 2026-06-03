"""SQLAlchemy 2.0 — async engine for the API, sync engine for Celery workers / migrations / seed."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from tracely.config import settings


class Base(DeclarativeBase):
    pass


# Async (FastAPI read/registry path)
async_engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Sync (Celery tasks, seed scripts) — Celery tasks are sync processes; avoid asyncio in them.
sync_engine = create_engine(settings.alembic_database_url, pool_pre_ping=True, future=True)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


def sync_session() -> Iterator[Session]:
    with SyncSessionLocal() as session:
        yield session
