"""billing: plan + Stripe columns on projects, monthly usage counters.

Hosted-cloud monetization. `plan` is `free | pro | unlimited` (`unlimited` = operator
workspaces, set via SQL, never touched by webhooks). `usage_counters` holds one row per
(project, UTC month) of externally-ingested traces — the number the quota gate compares
against the plan's limit. Self-hosters never write either (BILLING_ENABLED off), but the
columns exist so a later opt-in needs no migration.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS throughout — additive changes are safe to apply ahead of the code that uses
    # them (migrate-then-deploy), so a hand-applied head start must never fail the deploy (same
    # rationale as 0015).
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS plan VARCHAR(16) NOT NULL DEFAULT 'free'"
    )
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(64)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(64)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(32)")
    # Webhooks look a project up by its Stripe customer id on every subscription event.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_projects_stripe_customer_id "
        "ON projects (stripe_customer_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_counters (
            project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            period     VARCHAR(7)  NOT NULL,
            traces     BIGINT      NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (project_id, period)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_counters")
    op.execute("DROP INDEX IF EXISTS ix_projects_stripe_customer_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS subscription_status")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS stripe_subscription_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS stripe_customer_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS plan")
