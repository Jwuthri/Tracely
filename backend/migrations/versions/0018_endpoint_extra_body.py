"""agent_endpoints.extra_body: fields merged into every emulated-conversation request body.

Real agent APIs need more than a message — tenant_id, user_id, locale, channel. Query params
already ride along in `url` (posted verbatim), so this covers the remaining gap.

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_endpoints ADD COLUMN IF NOT EXISTS extra_body JSON DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE agent_endpoints DROP COLUMN IF EXISTS extra_body")
