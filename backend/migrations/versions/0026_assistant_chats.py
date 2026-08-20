"""In-app assistant conversations.

The chat widget used to keep its transcript in the browser, which meant a new laptop — or a
cleared site data — was a new blank assistant. `assistant_chats` moves it server-side: one row
per conversation, the whole transcript in a JSON column (a chat is always read and written whole),
scoped to the project and to the person who had it.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_chats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(120), nullable=False, server_default=""),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assistant_chats_project_id", "assistant_chats", ["project_id"])
    op.create_index(
        "ix_assistant_chats_owner", "assistant_chats", ["project_id", "user_id", "updated_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_chats_owner", table_name="assistant_chats")
    op.drop_index("ix_assistant_chats_project_id", table_name="assistant_chats")
    op.drop_table("assistant_chats")
