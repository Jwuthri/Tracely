"""failure intelligence: pgvector, failure_embeddings, LLM cluster fields

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("failure_clusters", sa.Column("description", sa.String(4000), nullable=False, server_default=""))
    op.add_column("failure_clusters", sa.Column("proposed_fix", sa.String(4000), nullable=False, server_default=""))
    op.add_column("failure_clusters", sa.Column("severity", sa.String(16), nullable=False, server_default=""))
    op.add_column("failure_clusters", sa.Column("method", sa.String(16), nullable=False, server_default="signature"))
    op.add_column("cluster_members", sa.Column("summary", sa.String(1000), nullable=False, server_default=""))

    op.create_table(
        "failure_embeddings",
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("summary", sa.String(4000), nullable=False, server_default=""),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_failure_embeddings_agent_id", "failure_embeddings", ["agent_id"])


def downgrade() -> None:
    op.drop_table("failure_embeddings")
    op.drop_column("cluster_members", "summary")
    op.drop_column("failure_clusters", "method")
    op.drop_column("failure_clusters", "severity")
    op.drop_column("failure_clusters", "proposed_fix")
    op.drop_column("failure_clusters", "description")
