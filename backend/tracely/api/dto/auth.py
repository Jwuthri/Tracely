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


class CreateProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    user_id: str | None
    email: str | None
    display_name: str | None
    role: str | None
    project_id: str
    project_name: str | None
    projects: list[ProjectRef] = []
    ingest_keys: list[str] = []


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
