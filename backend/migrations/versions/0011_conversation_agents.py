"""conversation agents: user-declared agent/tool catalog per conversation (sent via the SDK)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        # the declared catalog: [{name, description, tools: {tool_name: {name, description, parameters}}}]
        sa.Column("agents", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "thread_id", name="uq_conversation_agents_project_thread"),
    )
    op.create_index(
        "ix_conversation_agents_project_thread", "conversation_agents", ["project_id", "thread_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_agents_project_thread", table_name="conversation_agents")
    op.drop_table("conversation_agents")
