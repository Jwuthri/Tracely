"""multi-tenant auth: users, memberships, invitations + project tenancy source

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── projects: tenancy source (existing rows backfill to "local" via server_default) ──
    op.add_column(
        "projects", sa.Column("source", sa.String(16), nullable=False, server_default="local")
    )
    op.add_column("projects", sa.Column("external_id", sa.String(128), nullable=True))
    op.create_unique_constraint(
        "uq_projects_source_external", "projects", ["source", "external_id"]
    )

    # ── users ──
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="local"),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("source", "external_id", name="uq_users_source_external"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    # email is unique only among local accounts (Clerk emails may be unknown/empty/duplicated)
    op.create_index(
        "uq_users_local_email",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("source = 'local'"),
    )

    # ── memberships ──
    op.create_table(
        "memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="MEMBER"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "project_id", name="uq_membership_user_project"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_project_id", "memberships", ["project_id"])

    # ── invitations ──
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="MEMBER"),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_project_id", "invitations", ["project_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_constraint("uq_projects_source_external", "projects", type_="unique")
    op.drop_column("projects", "external_id")
    op.drop_column("projects", "source")
