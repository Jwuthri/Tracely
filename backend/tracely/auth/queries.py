"""Async Postgres reads for the auth endpoints.

The auth router composes these (plus `provisioning`/`invitations`) — it never builds queries
itself. All functions take the request-scoped `AsyncSession`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.infrastructure.db.models import (
    IngestKey,
    Invitation,
    Organization,
    OrgMembership,
    Project,
    User,
)


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


async def user_workspaces(
    session: AsyncSession, user_id: str
) -> list[tuple[Project, str]]:
    """Every workspace the user can reach, with their role in it — derived from org membership,
    the same join `select_membership` authorizes with."""
    rows = (
        await session.execute(
            select(Project, OrgMembership.role)
            .join(OrgMembership, OrgMembership.organization_id == Project.organization_id)
            .where(OrgMembership.user_id == user_id)
            .order_by(Project.created_at, Project.id)
        )
    ).all()
    return [(p, role) for p, role in rows]


async def organization_members(
    session: AsyncSession, organization_id: str
) -> list[tuple[User, str]]:
    rows = (
        await session.execute(
            select(User, OrgMembership.role)
            .join(OrgMembership, OrgMembership.user_id == User.id)
            .where(OrgMembership.organization_id == organization_id)
            .order_by(OrgMembership.created_at)
        )
    ).all()
    return [(u, role) for u, role in rows]


async def get_organization(
    session: AsyncSession, organization_id: str
) -> Organization | None:
    return await session.get(Organization, organization_id)


async def invitations_for_org(
    session: AsyncSession, organization_id: str
) -> list[Invitation]:
    return list(
        (
            await session.execute(
                select(Invitation)
                .where(Invitation.organization_id == organization_id)
                .order_by(Invitation.created_at.desc())
            )
        ).scalars()
    )


async def invitation_get(
    session: AsyncSession, organization_id: str, invite_id: str
) -> Invitation | None:
    return (
        await session.execute(
            select(Invitation).where(
                Invitation.id == invite_id, Invitation.organization_id == organization_id
            )
        )
    ).scalar_one_or_none()
