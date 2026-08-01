"""password resets: single-use, hashed, expiring reset grants for local-mode accounts.

Only the sha256 of the raw token is stored (same shape as `invitations`), so the table is useless
to anyone who reads it. Rows are consumed via `used_at` rather than deleted so a replayed link is
rejected explicitly.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), index=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_password_resets_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("password_resets")
