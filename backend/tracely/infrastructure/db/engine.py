"""SQLAlchemy 2.0 engines + sessionmakers.

Async engine for the FastAPI read path; sync engine for Celery workers, migrations, and seed
scripts (Celery tasks are sync processes — avoid asyncio there).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from tracely.config import settings

async_engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

sync_engine = create_engine(settings.alembic_database_url, pool_pre_ping=True, future=True)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)
