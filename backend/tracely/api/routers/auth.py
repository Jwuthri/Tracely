"""Auth endpoints. Mounted per-mode in api/main.py:
  - common_router : /auth/me, /auth/logout            (always)
  - local_router  : register/login/invitations        (AUTH_MODE=local)
  - clerk_router  : /auth/sync                         (AUTH_MODE=clerk)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.api.auth import get_principal, require_role
from tracely.api.dto.auth import (
    AcceptInviteIn,
    ChangePasswordIn,
    CreateProjectIn,
    InviteIn,
    InviteOut,
    InviteSummary,
    LoginIn,
    MeOut,
    ProjectRef,
    RegisterIn,
    SessionOut,
)
from tracely.auth import invitations, passwords, provisioning, queries, tokens
from tracely.auth.principal import Principal, select_membership
from tracely.infrastructure import mailer
from tracely.infrastructure.db.session import get_session

common_router = APIRouter()
local_router = APIRouter()
clerk_router = APIRouter()


async def _build_me(principal: Principal, session: AsyncSession) -> MeOut:
    project = await queries.get_project(session, principal.project_id)
    keys = await queries.project_ingest_keys(session, principal.project_id)
    email = display_name = None
    projects: list[ProjectRef] = []
    if principal.user_id:
        user = await queries.get_user(session, principal.user_id)
        if user:
            email, display_name = user.email, user.display_name
        projects = [
            ProjectRef(id=p.id, name=p.name, slug=p.slug, role=m.role)
            for (m, p) in await queries.user_memberships(session, principal.user_id)
        ]
    return MeOut(
        user_id=principal.user_id,
        email=email,
        display_name=display_name,
        role=principal.role,
        project_id=principal.project_id,
        project_name=project.name if project else None,
        projects=projects,
        ingest_keys=list(keys),
    )


# ── common ────────────────────────────────────────────────────────────────────

@common_router.get("/auth/me", response_model=MeOut)
async def me(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    return await _build_me(principal, session)


@common_router.post("/auth/logout")
async def logout() -> dict:
    # Stateless: the frontend clears the session cookie. (A token denylist is future work.)
    return {"ok": True}


@common_router.post("/auth/projects", response_model=ProjectRef)
async def create_project(
    body: CreateProjectIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> ProjectRef:
    """Create a new workspace owned by the caller. Available in local/clerk modes (dev mode has no
    signed-in user, so the ingest key already pins the single workspace)."""
    if not principal.user_id:
        raise HTTPException(
            400, "creating a workspace requires a signed-in user (AUTH_MODE=local or clerk)"
        )
    project, _key = await provisioning.create_workspace(
        session, name=body.name, owner_user_id=principal.user_id
    )
    return ProjectRef(id=project.id, name=project.name, slug=project.slug, role="OWNER")


# ── local mode ────────────────────────────────────────────────────────────────

@local_router.post("/auth/register", response_model=SessionOut)
async def register(
    body: RegisterIn, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    if await provisioning.any_local_user(session):
        raise HTTPException(409, "registration is invite-only; ask an owner for an invite")
    project, user = await provisioning.bootstrap_owner(
        session,
        email=body.email.lower().strip(),
        password_hash=passwords.hash_password(body.password),
        display_name=body.display_name,
        workspace_name=body.workspace_name,
    )
    return SessionOut(token=tokens.issue_session(user.id), user_id=user.id, project_id=project.id)


@local_router.post("/auth/change-password")
async def change_password(
    body: ChangePasswordIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Change the signed-in local user's password (verifies the current one first)."""
    if not principal.user_id:
        raise HTTPException(400, "not signed in")
    user = await queries.get_user(session, principal.user_id)
    if not user or not user.password_hash:
        raise HTTPException(404, "no local password for this account")
    if not passwords.verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "current password is incorrect")
    user.password_hash = passwords.hash_password(body.new_password)
    await session.commit()
    return {"ok": True}


@local_router.post("/auth/login", response_model=SessionOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> SessionOut:
    user = await queries.local_user_by_email(session, body.email.lower().strip())
    ok = passwords.verify_password(body.password, user.password_hash if user else None)
    if not ok or not user or not user.is_active:
        raise HTTPException(401, "invalid email or password")
    principal = await select_membership(user.id, None, session, kind="local")
    return SessionOut(
        token=tokens.issue_session(user.id), user_id=user.id, project_id=principal.project_id
    )


@local_router.post("/auth/invitations", response_model=InviteOut)
async def create_invitation(
    body: InviteIn,
    principal: Principal = Depends(require_role("OWNER", "ADMIN")),
    session: AsyncSession = Depends(get_session),
) -> InviteOut:
    role = body.role.upper()
    if role not in ("ADMIN", "MEMBER"):
        raise HTTPException(400, "role must be ADMIN or MEMBER")
    raw, token_hash = invitations.new_invite_token()
    inv = await provisioning.create_invitation(
        session,
        project_id=principal.project_id,
        email=body.email,
        role=role,
        invited_by=principal.user_id,
        token_hash=token_hash,
    )
    # Best-effort: email the invite link when Resend is configured. The raw token is always returned
    # so the UI can still surface the link manually (and as a fallback if delivery fails).
    emailed = False
    if mailer.email_enabled():
        project = await queries.get_project(session, principal.project_id)
        inviter = None
        if principal.user_id:
            u = await queries.get_user(session, principal.user_id)
            inviter = (u.display_name or u.email) if u else None
        emailed = await mailer.send_invite_email(
            to=inv.email,
            raw_token=raw,
            project_name=project.name if project else "Tracely",
            inviter=inviter,
        )
    return InviteOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        token=raw,
        expires_at=inv.expires_at.isoformat(),
        emailed=emailed,
    )


@local_router.get("/auth/invitations", response_model=list[InviteSummary])
async def list_invitations(
    principal: Principal = Depends(require_role("OWNER", "ADMIN")),
    session: AsyncSession = Depends(get_session),
) -> list[InviteSummary]:
    rows = await queries.invitations_for_project(session, principal.project_id)
    return [
        InviteSummary(
            id=i.id,
            email=i.email,
            role=i.role,
            status=i.status,
            created_at=i.created_at.isoformat() if i.created_at else None,
        )
        for i in rows
    ]


@local_router.delete("/auth/invitations/{invite_id}")
async def revoke_invitation(
    invite_id: str,
    principal: Principal = Depends(require_role("OWNER", "ADMIN")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    inv = await queries.invitation_get(session, principal.project_id, invite_id)
    if not inv:
        raise HTTPException(404, "invitation not found")
    if inv.status == "PENDING":
        inv.status = "REVOKED"
        await session.commit()
    return {"ok": True}


@local_router.post("/auth/invitations/accept", response_model=SessionOut)
async def accept_invitation(
    body: AcceptInviteIn, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    user, project = await provisioning.accept_invitation(
        session,
        raw_token=body.token,
        password_hash=passwords.hash_password(body.password),
        display_name=body.display_name,
    )
    return SessionOut(token=tokens.issue_session(user.id), user_id=user.id, project_id=project.id)


# ── clerk mode ────────────────────────────────────────────────────────────────

@clerk_router.post("/auth/sync", response_model=MeOut)
async def sync(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    # get_principal already upserted the user/project/membership from the verified Clerk JWT
    return await _build_me(principal, session)
