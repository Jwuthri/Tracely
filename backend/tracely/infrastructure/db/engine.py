"""SQLAlchemy 2.0 engines + sessionmakers.

Async engine for the FastAPI read path; sync engine for Celery workers, migrations, and seed
scripts (Celery tasks are sync processes — avoid asyncio there).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from tracely.config import settings

# ponytail: bound the pools. SQLAlchemy's defaults are 5 + 10 overflow PER ENGINE PER PROCESS, and
# both engines live in both the API and the worker — enough to ask Postgres for more connections
# than it allows, which it answers with `FATAL: sorry, too many clients already` and a 500 on
# whatever was in flight. Note an API request can hold two at once: the async one its auth
# dependency keeps open for the whole request, plus a sync one while the handler runs in the
# threadpool. Ceiling: (5 + 5) * 2 engines * 2 services = 40. Raise it only alongside
# Postgres `max_connections`.
_POOL = {"pool_size": 5, "max_overflow": 5, "pool_pre_ping": True}

async_engine = create_async_engine(settings.database_url, future=True, **_POOL)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

sync_engine = create_engine(settings.alembic_database_url, future=True, **_POOL)
SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, class_=Session)
