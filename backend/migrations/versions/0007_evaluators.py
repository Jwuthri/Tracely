"""user-defined evaluators: evaluators table

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluators",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("score_name", sa.String(80), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="AGENT_RUN"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("target_agent", sa.String(80), nullable=False, server_default=""),
        sa.Column("target_env", sa.String(32), nullable=False, server_default=""),
        sa.Column("sampling", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_evaluators_project_id", "evaluators", ["project_id"])


def downgrade() -> None:
    op.drop_table("evaluators")
