"""Async Postgres reads for the auth endpoints.

The auth router composes these (plus `provisioning`/`invitations`) — it never builds queries
itself. All functions take the request-scoped `AsyncSession`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.infrastructure.db.models import IngestKey, Invitation, Membership, Project, User


async def get_project(session: AsyncSession, project_id: str) -> Project | None:
    return (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()


async def project_ingest_keys(session: AsyncSession, project_id: str) -> list[str]:
    return list(
        (
            await session.execute(
                select(IngestKey.key).where(IngestKey.project_id == project_id)
            )
        ).scalars()
    )


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    return (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()


async def local_user_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(
            select(User).where(User.source == "local", User.email == email)
        )
    ).scalar_one_or_none()


async def user_memberships(
    session: AsyncSession, user_id: str
) -> list[tuple[Membership, Project]]:
    rows = (
        await session.execute(
            select(Membership, Project)
            .join(Project, Project.id == Membership.project_id)
            .where(Membership.user_id == user_id)
        )
    ).all()
    return [(m, p) for m, p in rows]


async def invitations_for_project(
    session: AsyncSession, project_id: str
) -> list[Invitation]:
    return list(
        (
            await session.execute(
                select(Invitation)
                .where(Invitation.project_id == project_id)
                .order_by(Invitation.created_at.desc())
            )
        ).scalars()
    )


async def invitation_get(
    session: AsyncSession, project_id: str, invite_id: str
) -> Invitation | None:
    return (
        await session.execute(
            select(Invitation).where(
                Invitation.id == invite_id, Invitation.project_id == project_id
            )
        )
    ).scalar_one_or_none()
