"""failure clustering: failure_clusters, cluster_members

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "failure_clusters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("taxonomy", sa.String(64), nullable=False, server_default=""),
        sa.Column("signature", sa.String(2000), nullable=False, server_default=""),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("candidate_case_id", sa.String(36), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "agent_id", "cluster_key", name="uq_cluster_project_agent_key"),
    )
    op.create_index("ix_clusters_project_id", "failure_clusters", ["project_id"])
    op.create_index("ix_clusters_agent_id", "failure_clusters", ["agent_id"])

    op.create_table(
        "cluster_members",
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("failure_clusters.id"), primary_key=True),
        sa.Column("trace_id", sa.String(64), primary_key=True),
        sa.Column("is_medoid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("cluster_members")
    op.drop_table("failure_clusters")
