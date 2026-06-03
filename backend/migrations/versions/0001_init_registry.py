"""init registry: projects, ingest_keys, agents, agent_versions

Revision ID: 0001
Revises:
Create Date: 2026-06-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )

    op.create_table(
        "ingest_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("key", name="uq_ingest_keys_key"),
    )
    op.create_index("ix_ingest_keys_project_id", "ingest_keys", ["project_id"])

    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False, server_default="SINGLE"),
        sa.Column("role", sa.String(32), nullable=False, server_default="GENERIC"),
        sa.Column("framework", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "slug", name="uq_agent_project_slug"),
    )
    op.create_index("ix_agents_project_id", "agents", ["project_id"])

    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("git_sha", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_id", "config_hash", name="uq_agentversion_agent_confighash"),
    )
    op.create_index("ix_agent_versions_agent_id", "agent_versions", ["agent_id"])


def downgrade() -> None:
    op.drop_table("agent_versions")
    op.drop_table("agents")
    op.drop_table("ingest_keys")
    op.drop_table("projects")
