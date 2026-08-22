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
from tracely.infrastructure.db.models import IngestKey, OrgMembership, Project, User


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
    role: str | None  # the caller's role in the ORG owning project_id; None for ingest keys
    kind: Literal["ingest", "local", "clerk"]
    # The account the active workspace belongs to. None for ingest keys (machine credentials
    # carry no human identity — billing/team endpoints reject them on `role` anyway) and for
    # org-less projects (CLI-seeded / dev mode).
    organization_id: str | None = None


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
    # A machine credential has no role, so `require_user` endpoints (wipe, secrets, deletes)
    # refuse it — a key leaked from CI can't take the workspace with it. Dev mode is the one
    # exception: it has no human auth at all, the UI itself runs on this key, and prod refuses
    # to boot in it (`config._validate_auth`).
    role = "OWNER" if settings.auth_mode == "dev" else None
    return Principal(project_id=row.project_id, user_id=None, role=role, kind="ingest")


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
    # Revocation: a password change or reset bumps `token_version`, which strands every token
    # issued before it — including one an intruder is holding, which is the entire point of
    # taking the account back. Tokens minted before this claim existed read as 0 and still match
    # the column default.
    if int(claims.get("tv", 0)) != int(user.token_version or 0):
        raise AuthError(401, "session ended — sign in again")
    return await select_membership(user.id, x_project, session, kind="local")


async def select_membership(
    user_id: str,
    x_project: str | None,
    session: AsyncSession,
    *,
    kind: Literal["local", "clerk"],
) -> Principal:
    """Pick the active workspace for a user: the one named by `X-Tracely-Project`, else their
    oldest. Raises 403 if they can reach none / can't reach the requested one.

    Reachability is derived, never stored: a workspace is reachable exactly when the user is a
    member of the organization owning it. That is the whole cross-tenant boundary — there is no
    per-workspace grant that could drift from it."""
    rows = (
        await session.execute(
            select(Project.id, Project.organization_id, OrgMembership.role)
            .join(OrgMembership, OrgMembership.organization_id == Project.organization_id)
            .where(OrgMembership.user_id == user_id)
            .order_by(Project.created_at, Project.id)
        )
    ).all()
    if not rows:
        raise AuthError(403, "no workspace membership")
    if x_project:
        row = next((r for r in rows if r[0] == x_project), None)
        if row is None:
            raise AuthError(403, "not a member of the requested project")
    else:
        row = rows[0]
    return Principal(
        project_id=row[0], user_id=user_id, role=row[2], kind=kind, organization_id=row[1]
    )
