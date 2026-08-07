"""billing: pool the free trace quota per owning account, not per workspace.

`projects.billing_owner_id` = the user whose account a workspace's free quota draws from
(the workspace creator). The quota gate sums usage across ALL free-plan workspaces sharing
an owner, so creating more workspaces never mints more free quota — the same account-level
model Langfuse/LangSmith bill on. Paid plans stay per-workspace (each Pro workspace buys its
own cap). NULL (dev mode, CLI-seeded projects) falls back to per-workspace accounting.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ON DELETE SET NULL: losing the owning user must never take the workspace down with it —
    # the project just degrades to per-workspace accounting.
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS billing_owner_id VARCHAR(36) "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_billing_owner_id ON projects (billing_owner_id)"
    )
    # Backfill existing workspaces: earliest OWNER membership, else earliest membership.
    op.execute(
        """
        UPDATE projects SET billing_owner_id = (
            SELECT m.user_id FROM memberships m
            WHERE m.project_id = projects.id
            ORDER BY CASE WHEN m.role = 'OWNER' THEN 0 ELSE 1 END, m.created_at, m.id
            LIMIT 1
        )
        WHERE billing_owner_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_projects_billing_owner_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS billing_owner_id")
