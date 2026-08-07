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
    CreateOrgIn,
    CreateProjectIn,
    ForgotPasswordIn,
    InviteIn,
    InviteOut,
    InviteSummary,
    LoginIn,
    MemberSummary,
    MeOut,
    OrgRef,
    ProjectRef,
    RegisterIn,
    ResetPasswordIn,
    SessionOut,
)
from tracely.auth import invitations, password_reset, passwords, provisioning, queries, tokens
from tracely.auth.principal import Principal, select_membership
from tracely.config import settings
from tracely.domain.billing import KIND_COMPANY
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
    orgs: list[OrgRef] = []
    if principal.user_id:
        user = await queries.get_user(session, principal.user_id)
        if user:
            email, display_name = user.email, user.display_name
        projects = [
            ProjectRef(
                id=p.id, name=p.name, slug=p.slug, role=role, organization_id=p.organization_id
            )
            for (p, role) in await queries.user_workspaces(session, principal.user_id)
        ]
        orgs = [
            OrgRef(id=o.id, name=o.name, slug=o.slug, kind=o.kind, plan=o.plan, role=role)
            for (o, role) in await provisioning.user_organizations(session, principal.user_id)
        ]
    active_org = next((o for o in orgs if o.id == principal.organization_id), None)
    return MeOut(
        user_id=principal.user_id,
        email=email,
        display_name=display_name,
        role=principal.role,
        project_id=principal.project_id,
        project_name=project.name if project else None,
        organization_id=principal.organization_id,
        organization_name=active_org.name if active_org else None,
        organization_kind=active_org.kind if active_org else None,
        organization_plan=active_org.plan if active_org else None,
        projects=projects,
        organizations=orgs,
        ingest_keys=list(keys),
    )


async def _require_org(principal: Principal, session: AsyncSession):
    """The org backing the caller's active workspace, or a 400. Machine principals and the
    org-less projects a CLI seed creates have no account to act on."""
    if not principal.organization_id:
        raise HTTPException(400, "this workspace has no organization (signed-in users only)")
    org = await queries.get_organization(session, principal.organization_id)
    if org is None:
        raise HTTPException(404, "organization not found")
    return org


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
    principal: Principal = Depends(require_role("OWNER", "ADMIN")),
    session: AsyncSession = Depends(get_session),
) -> ProjectRef:
    """Add a workspace to the caller's organization. Bounded by the org's plan: a personal
    account holds exactly one, so growing past it means creating an organization."""
    org = await _require_org(principal, session)
    await provisioning.assert_can_add_workspace(session, org)
    project, _key = await provisioning.create_workspace(
        session, name=body.name, organization_id=org.id
    )
    return ProjectRef(
        id=project.id,
        name=project.name,
        slug=project.slug,
        role=principal.role or "OWNER",
        organization_id=org.id,
    )


@common_router.post("/auth/organizations", response_model=OrgRef)
async def create_organization(
    body: CreateOrgIn,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> OrgRef:
    """Create a company organization owned by the caller, with its first workspace. This is how a
    solo account becomes a team: personal accounts can't be joined, companies can."""
    if not principal.user_id:
        raise HTTPException(
            400, "creating an organization requires a signed-in user (AUTH_MODE=local or clerk)"
        )
    org = await provisioning.create_organization(
        session, name=body.name, kind=KIND_COMPANY, owner_user_id=principal.user_id
    )
    await provisioning.create_workspace(session, name=body.name, organization_id=org.id)
    return OrgRef(
        id=org.id, name=org.name, slug=org.slug, kind=org.kind, plan=org.plan, role="OWNER"
    )


@common_router.get("/auth/members", response_model=list[MemberSummary])
async def list_members(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[MemberSummary]:
    """Who is in the caller's organization. Any member may see their teammates."""
    org = await _require_org(principal, session)
    return [
        MemberSummary(
            user_id=u.id, email=u.email, display_name=u.display_name or "", role=role
        )
        for (u, role) in await queries.organization_members(session, org.id)
    ]


# ── local mode ────────────────────────────────────────────────────────────────

@local_router.post("/auth/register", response_model=SessionOut)
async def register(
    body: RegisterIn, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    """Create an account. On hosted cloud (`ALLOW_PUBLIC_SIGNUP`) anyone may register and gets
    their own personal organization; self-hosted, the first registrant claims the deployment as a
    company org and everyone else arrives by invite."""
    email = body.email.lower().strip()
    first_user = not await provisioning.any_local_user(session)
    if not first_user and not settings.allow_public_signup:
        raise HTTPException(409, "registration is invite-only; ask an owner for an invite")
    if not first_user and await queries.local_user_by_email(session, email):
        raise HTTPException(409, "an account with that email already exists")
    make = provisioning.bootstrap_owner if first_user else provisioning.signup_personal
    project, user = await make(
        session,
        email=email,
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


@local_router.post("/auth/forgot-password")
async def forgot_password(
    body: ForgotPasswordIn, session: AsyncSession = Depends(get_session)
) -> dict:
    """Request a reset link. **Always** reports the same thing, whether or not the email has an
    account — an unauthenticated caller does not get to enumerate users. The raw token is only
    ever delivered by email; it is never in this response.

    With Resend unconfigured (the self-host default) nothing is sent. Recover such an account with
    `python -m tracely.auth.reset_link <email>` on the server, which prints the link directly.
    """
    grant = await password_reset.create_reset(session, body.email)
    if grant and mailer.email_enabled():
        raw, user = grant
        await mailer.send_password_reset_email(to=user.email, raw_token=raw)
    return {"ok": True, "message": "If that email has an account, a reset link is on its way."}


@local_router.post("/auth/reset-password", response_model=SessionOut)
async def reset_password(
    body: ResetPasswordIn, session: AsyncSession = Depends(get_session)
) -> SessionOut:
    """Consume a reset token and set the new password. Unknown, expired and already-used tokens
    all return the same 400 — telling them apart only helps someone guessing."""
    user = await password_reset.consume_reset(session, body.token, body.new_password)
    if user is None:
        raise HTTPException(400, "this reset link is invalid or has expired")
    principal = await select_membership(user.id, None, session, kind="local")
    return SessionOut(
        token=tokens.issue_session(user.id), user_id=user.id, project_id=principal.project_id
    )


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
    """Invite someone into the caller's ORGANIZATION — they get access to all of its workspaces.
    409 when the org has no seat left, or when it's a personal account (which can never be
    joined)."""
    role = body.role.upper()
    if role not in ("ADMIN", "MEMBER"):
        raise HTTPException(400, "role must be ADMIN or MEMBER")
    org = await _require_org(principal, session)
    await provisioning.assert_can_add_seat(session, org)
    raw, token_hash = invitations.new_invite_token()
    inv = await provisioning.create_invitation(
        session,
        organization_id=org.id,
        email=body.email,
        role=role,
        invited_by=principal.user_id,
        token_hash=token_hash,
    )
    # Best-effort: email the invite link when Resend is configured. The raw token is always returned
    # so the UI can still surface the link manually (and as a fallback if delivery fails).
    emailed = False
    if mailer.email_enabled():
        inviter = None
        if principal.user_id:
            u = await queries.get_user(session, principal.user_id)
            inviter = (u.display_name or u.email) if u else None
        emailed = await mailer.send_invite_email(
            to=inv.email,
            raw_token=raw,
            project_name=org.name,
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
    org = await _require_org(principal, session)
    rows = await queries.invitations_for_org(session, org.id)
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
    org = await _require_org(principal, session)
    inv = await queries.invitation_get(session, org.id, invite_id)
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
