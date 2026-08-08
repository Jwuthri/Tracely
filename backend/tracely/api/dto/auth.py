"""Request/response models for the /auth router (both modes)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8)
    display_name: str = ""
    workspace_name: str = "Tracely"


class LoginIn(BaseModel):
    email: str
    password: str


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Field(min_length=8)
    display_name: str = ""


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class InviteIn(BaseModel):
    email: str
    role: str = "MEMBER"


class SessionOut(BaseModel):
    token: str
    user_id: str
    project_id: str


class ProjectRef(BaseModel):
    id: str
    name: str
    slug: str
    role: str
    organization_id: str | None = None


class OrgRef(BaseModel):
    id: str
    name: str
    slug: str
    kind: str  # personal | company
    plan: str
    role: str


class CreateProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class CreateOrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class ConfirmIn(BaseModel):
    """Destructive actions confirm with the exact name of what's being destroyed, never a fixed
    word — muscle memory shouldn't be able to delete an organization."""

    confirm: str = ""


class MemberSummary(BaseModel):
    user_id: str
    email: str
    display_name: str = ""
    role: str


class MeOut(BaseModel):
    user_id: str | None
    email: str | None
    display_name: str | None
    role: str | None  # the caller's role in the ACTIVE organization
    project_id: str
    project_name: str | None
    organization_id: str | None = None
    organization_name: str | None = None
    organization_kind: str | None = None
    organization_plan: str | None = None
    projects: list[ProjectRef] = []
    organizations: list[OrgRef] = []
    ingest_keys: list[str] = []
    # Server-decided so the menu never offers an action the plan will reject.
    can_create_organization: bool = False


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    token: str  # shown once at creation
    expires_at: str | None = None
    emailed: bool = False  # True if the invite link was emailed (RESEND_API_KEY set); else share manually


class InviteSummary(BaseModel):
    id: str
    email: str
    role: str
    status: str
    created_at: str | None = None
