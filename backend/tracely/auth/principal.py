"""Resolve an incoming credential to a Principal (the project it grants, plus optional user/role).

This is the single chokepoint behind the FastAPI `get_project_id` dependency. It accepts three
credential kinds and HARD-BRANCHES between them: a JWT-shaped token is verified per AUTH_MODE and a
verify failure is a terminal 401 — it never falls back to an ingest-key lookup, and an opaque key is
never handed to the JWT verifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.auth import classify, tokens
from tracely.config import settings
from tracely.infrastructure.db.models import IngestKey, Membership, User


class AuthError(Exception):
    """Carries an HTTP status + detail; the dependency layer maps it to HTTPException."""

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class Principal:
    project_id: str
    user_id: str | None  # None for machine (ingest-key) principals
    role: str | None  # OWNER | ADMIN | MEMBER | None
    kind: Literal["ingest", "local", "clerk"]


async def resolve_principal(
    *, token: str, x_project: str | None, session: AsyncSession
) -> Principal:
    if classify.looks_like_jwt(token):
        if settings.auth_mode == "local":
            return await _resolve_local_jwt(token, x_project, session)
        if settings.auth_mode == "clerk":
            from tracely.auth import clerk  # lazy: JWKS/httpx only needed in clerk mode

            return await clerk.resolve_clerk_jwt(token, x_project, session)
        raise AuthError(401, "token auth is disabled (AUTH_MODE=dev)")
    return await _resolve_ingest_key(token, session)


async def _resolve_ingest_key(key: str, session: AsyncSession) -> Principal:
    row = (
        await session.execute(select(IngestKey).where(IngestKey.key == key))
    ).scalar_one_or_none()
    if not row:
        raise AuthError(401, "invalid ingest key")
    return Principal(project_id=row.project_id, user_id=None, role=None, kind="ingest")


async def _resolve_local_jwt(
    token: str, x_project: str | None, session: AsyncSession
) -> Principal:
    try:
        claims = tokens.verify_session(token)
    except tokens.TokenError:
        raise AuthError(401, "invalid session") from None
    user = (
        await session.execute(select(User).where(User.id == claims["sub"]))
    ).scalar_one_or_none()
    if not user or not user.is_active:
        raise AuthError(401, "invalid session")
    return await select_membership(user.id, x_project, session, kind="local")


async def select_membership(
    user_id: str,
    x_project: str | None,
    session: AsyncSession,
    *,
    kind: Literal["local", "clerk"],
) -> Principal:
    """Pick the active project for a user: the one named by `X-Tracely-Project` (membership enforced),
    else their first membership. Raises 403 if they have none / aren't a member of the requested one."""
    rows = (
        await session.execute(
            select(Membership)
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at)
        )
    ).scalars().all()
    if not rows:
        raise AuthError(403, "no workspace membership")
    if x_project:
        m = next((r for r in rows if r.project_id == x_project), None)
        if m is None:
            raise AuthError(403, "not a member of the requested project")
    else:
        m = rows[0]
    return Principal(project_id=m.project_id, user_id=user_id, role=m.role, kind=kind)
