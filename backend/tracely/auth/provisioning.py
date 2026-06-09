"""Workspace + identity provisioning for the auth flows. Generalizes services/seeding_service.py.

Local mode keeps a single workspace per deployment: the first registrant becomes its OWNER (reusing the
seeded "default" project if present); everyone else joins by invite. The Clerk upsert path lives in
`auth/clerk.py` and calls `upsert_clerk_principal` here."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.auth.invitations import hash_token
from tracely.auth.principal import AuthError, Principal
from tracely.infrastructure.db.models import IngestKey, Invitation, Membership, Project, User


def new_ingest_key() -> str:
    """Opaque, dot-free ingest key — the classifier must never mistake it for a JWT."""
    return "tk_" + secrets.token_urlsafe(32)


def _as_utc(dt: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes from DateTime(timezone=True); treat them as UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _get_or_create(session: AsyncSession, model, *, where, defaults):
    """Portable, race-safe get-or-create (works on Postgres + SQLite). A concurrent insert that loses
    the unique-constraint race is caught at the savepoint and resolved by re-selecting the winner."""
    obj = (await session.execute(select(model).where(*where))).scalar_one_or_none()
    if obj is not None:
        return obj
    try:
        async with session.begin_nested():
            obj = model(**defaults)
            session.add(obj)
        return obj
    except IntegrityError:
        return (await session.execute(select(model).where(*where))).scalar_one()


# ── local mode ────────────────────────────────────────────────────────────────

async def any_local_user(session: AsyncSession) -> bool:
    n = (
        await session.execute(
            select(func.count()).select_from(User).where(User.source == "local")
        )
    ).scalar_one()
    return bool(n)


async def get_singleton_local_project(session: AsyncSession) -> Project | None:
    return (
        await session.execute(
            select(Project)
            .where(Project.source == "local")
            .order_by(Project.created_at)
            .limit(1)
        )
    ).scalars().first()


async def _ensure_ingest_key(session: AsyncSession, project_id: str) -> None:
    existing = (
        await session.execute(
            select(IngestKey).where(IngestKey.project_id == project_id).limit(1)
        )
    ).scalars().first()
    if not existing:
        session.add(IngestKey(id=str(uuid4()), project_id=project_id, key=new_ingest_key()))


async def bootstrap_owner(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str = "",
    workspace_name: str = "Tracely",
) -> tuple[Project, User]:
    """First-run: make `email` the OWNER of the singleton local workspace (reusing the seeded project
    if one exists, else creating it) and ensure it has an ingest key."""
    project = await get_singleton_local_project(session)
    if project is None:
        project = Project(id=str(uuid4()), slug="default", name=workspace_name, source="local")
        session.add(project)
        await session.flush()
    await _ensure_ingest_key(session, project.id)
    user = User(
        id=str(uuid4()),
        email=email,
        source="local",
        password_hash=password_hash,
        display_name=display_name,
    )
    session.add(user)
    await session.flush()
    session.add(
        Membership(id=str(uuid4()), user_id=user.id, project_id=project.id, role="OWNER")
    )
    await session.commit()
    return project, user


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (base or "workspace")[:96]


async def create_workspace(
    session: AsyncSession, *, name: str, owner_user_id: str
) -> tuple[Project, IngestKey]:
    """Create a new workspace (Project) owned by `owner_user_id`, with its own ingest key. Backs the
    UI's "New workspace" action: the user can then switch to it (X-Tracely-Project) and push traces
    with the returned key. The slug gets a short random suffix so same-named workspaces never collide
    on the unique constraint."""
    name = (name or "").strip() or "Workspace"
    project = Project(
        id=str(uuid4()),
        slug=f"{_slugify(name)}-{secrets.token_hex(3)}",
        name=name,
        source="local",
    )
    session.add(project)
    await session.flush()
    key = IngestKey(id=str(uuid4()), project_id=project.id, key=new_ingest_key())
    session.add(key)
    session.add(
        Membership(id=str(uuid4()), user_id=owner_user_id, project_id=project.id, role="OWNER")
    )
    await session.commit()
    return project, key


async def create_invitation(
    session: AsyncSession,
    *,
    project_id: str,
    email: str,
    role: str,
    invited_by: str | None,
    token_hash: str,
    ttl_seconds: int = 7 * 24 * 3600,
) -> Invitation:
    inv = Invitation(
        id=str(uuid4()),
        project_id=project_id,
        email=email.lower().strip(),
        role=role,
        token_hash=token_hash,
        invited_by=invited_by,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    )
    session.add(inv)
    await session.commit()
    return inv


async def accept_invitation(
    session: AsyncSession,
    *,
    raw_token: str,
    password_hash: str,
    display_name: str = "",
) -> tuple[User, Project]:
    """Atomically consume a valid invite and create (or re-attach) the member. Raises AuthError."""
    inv = (
        await session.execute(
            select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
        )
    ).scalar_one_or_none()
    if not inv or inv.status != "PENDING":
        raise AuthError(400, "invalid or used invitation")
    if _as_utc(inv.expires_at) <= datetime.now(timezone.utc):
        raise AuthError(400, "invitation expired")
    # single-use: flip PENDING -> ACCEPTED, asserting we won any race
    res = await session.execute(
        update(Invitation)
        .where(Invitation.id == inv.id, Invitation.status == "PENDING")
        .values(status="ACCEPTED", accepted_at=datetime.now(timezone.utc))
    )
    if res.rowcount != 1:
        raise AuthError(400, "invalid or used invitation")
    user = (
        await session.execute(
            select(User).where(User.source == "local", User.email == inv.email)
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(
            id=str(uuid4()),
            email=inv.email,
            source="local",
            password_hash=password_hash,
            display_name=display_name,
        )
        session.add(user)
        await session.flush()
    existing = (
        await session.execute(
            select(Membership).where(
                Membership.user_id == user.id, Membership.project_id == inv.project_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            Membership(
                id=str(uuid4()), user_id=user.id, project_id=inv.project_id, role=inv.role
            )
        )
    project = (
        await session.execute(select(Project).where(Project.id == inv.project_id))
    ).scalar_one()
    await session.commit()
    return user, project


# ── clerk mode ────────────────────────────────────────────────────────────────

async def upsert_clerk_principal(
    session: AsyncSession,
    *,
    clerk_user_id: str,
    email: str,
    display_name: str,
    org_id: str | None,
    role: str,
) -> Principal:
    """Idempotently upsert User + Project (+ IngestKey) + Membership from verified Clerk claims.
    Concurrent first-requests can't create duplicates (unique constraints + race-safe get-or-create)."""
    external_project = org_id or f"user:{clerk_user_id}"

    user = await _get_or_create(
        session,
        User,
        where=(User.source == "clerk", User.external_id == clerk_user_id),
        defaults=dict(
            id=str(uuid4()),
            email=email,
            source="clerk",
            external_id=clerk_user_id,
            display_name=display_name,
        ),
    )

    # the tenant — one project per org, or a personal workspace per user
    project = await _get_or_create(
        session,
        Project,
        where=(Project.source == "clerk", Project.external_id == external_project),
        defaults=dict(
            id=str(uuid4()),
            slug=f"clerk-{external_project}"[:128],
            name=(f"Org {org_id}" if org_id else email),
            source="clerk",
            external_id=external_project,
        ),
    )
    await _ensure_ingest_key(session, project.id)

    # membership — role synced from Clerk on every request (Clerk is source of truth)
    membership = await _get_or_create(
        session,
        Membership,
        where=(Membership.user_id == user.id, Membership.project_id == project.id),
        defaults=dict(
            id=str(uuid4()), user_id=user.id, project_id=project.id, role=role
        ),
    )
    if membership.role != role:
        membership.role = role

    await session.commit()
    return Principal(project_id=project.id, user_id=user.id, role=role, kind="clerk")
