"""meta-analysis: cross-metric correlation/outlier analysis over an agent's evaluator scores

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meta_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        # the events agent_id (Agent uuid) this analysis was scoped to; "" = whole project
        sa.Column("agent_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("analysis_type", sa.String(32), nullable=False, server_default="agent"),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_meta_analyses_project_id", "meta_analyses", ["project_id"])
    # "latest analysis for this (project, agent)" is the hot lookup
    op.create_index(
        "ix_meta_analyses_project_agent", "meta_analyses", ["project_id", "agent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_meta_analyses_project_agent", table_name="meta_analyses")
    op.drop_index("ix_meta_analyses_project_id", table_name="meta_analyses")
    op.drop_table("meta_analyses")
