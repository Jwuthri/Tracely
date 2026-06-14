"""rolling summary: per-span accumulating conversation summary (caches @HISTORY / conversation context)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rolling_summaries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("span_id", sa.String(64), nullable=False),
        # position of this span in the thread's start_time order — drives before/latest lookups
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
        # the FULL accumulated summary as of this step (list[ConversationSummaryItem]); not a delta
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # one summary per span → generation is idempotent / race-safe
        sa.UniqueConstraint("project_id", "span_id", name="uq_rolling_summary_project_span"),
    )
    op.create_index("ix_rolling_summaries_project_id", "rolling_summaries", ["project_id"])
    op.create_index(
        "ix_rolling_summaries_thread", "rolling_summaries", ["project_id", "thread_id", "step_order"]
    )


def downgrade() -> None:
    op.drop_index("ix_rolling_summaries_thread", table_name="rolling_summaries")
    op.drop_index("ix_rolling_summaries_project_id", table_name="rolling_summaries")
    op.drop_table("rolling_summaries")
