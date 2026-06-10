"""Hermetic auth test harness: an in-memory SQLite DB (StaticPool so every connection shares it) with
only the registry/auth tables created, plus an ASGI httpx client with `get_session` overridden.

AUTH_MODE/SESSION_SECRET are set *before* importing the app so main.py mounts the local-mode routers.
Clerk-mode tests monkeypatch `settings.auth_mode` and call the resolver directly (no app rebuild)."""

from __future__ import annotations

import os
from uuid import uuid4

os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-at-least-32-chars-long")

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from tracely.api.main import app  # noqa: E402
from tracely.auth import passwords  # noqa: E402
from tracely.infrastructure.db import models  # noqa: E402
from tracely.infrastructure.db.base import Base  # noqa: E402
from tracely.infrastructure.db.session import get_session  # noqa: E402

# Only the tables the auth flows touch — avoids the pgvector `Vector` column (failure_embeddings),
# which has no SQLite type compiler. Evaluators ride along because workspace provisioning seeds
# the recommended catalog (and the /api/evaluators CRUD tests need it).
_AUTH_TABLES = [
    models.Project.__table__,
    models.IngestKey.__table__,
    models.User.__table__,
    models.Membership.__table__,
    models.Invitation.__table__,
    models.Evaluator.__table__,
]


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_AUTH_TABLES)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(sessionmaker):
    async with sessionmaker() as s:
        yield s


@pytest_asyncio.fixture
async def client(sessionmaker):
    async def _override():
        async with sessionmaker() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
def make_workspace(session):
    """Create an isolated workspace (project + ingest key + OWNER user + membership), committed."""

    async def _make(slug: str, key: str, email: str, role: str = "OWNER", password: str = "pw-secret"):
        proj = models.Project(id=str(uuid4()), slug=slug, name=slug, source="local")
        user = models.User(
            id=str(uuid4()),
            email=email,
            source="local",
            password_hash=passwords.hash_password(password),
        )
        session.add_all([proj, user])
        await session.flush()
        k = models.IngestKey(id=str(uuid4()), project_id=proj.id, key=key)
        m = models.Membership(id=str(uuid4()), user_id=user.id, project_id=proj.id, role=role)
        session.add_all([k, m])
        await session.commit()
        return proj, user, k

    return _make
