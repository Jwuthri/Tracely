"""regression testing: evaluation_suites, evaluation_cases, evaluation_suite_cases, case_replays

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_suites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(256), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False, server_default="REGRESSION"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "agent_id", "slug", name="uq_suite_project_agent_slug"),
    )
    op.create_index("ix_suites_project_id", "evaluation_suites", ["project_id"])
    op.create_index("ix_suites_agent_id", "evaluation_suites", ["agent_id"])

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("level", sa.String(32), nullable=False, server_default="AGENT_RUN"),
        sa.Column("title", sa.String(512), nullable=False, server_default=""),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("origin", sa.String(32), nullable=False, server_default="MANUAL"),
        sa.Column("source_trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_span_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("agent_version_first_failed", sa.String(36), nullable=True),
        sa.Column("fixture_bundle_s3_key", sa.String(512), nullable=False, server_default=""),
        sa.Column("reference_trajectory", sa.JSON(), nullable=True),
        sa.Column("assertions", sa.JSON(), nullable=True),
        sa.Column("match_mode", sa.String(16), nullable=False, server_default="superset"),
        sa.Column("tool_args_mode", sa.String(16), nullable=False, server_default="exact"),
        sa.Column("fail_to_pass_validated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(128), nullable=False, server_default="ui"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "agent_id", "input_digest", name="uq_case_project_agent_inputdigest"),
    )
    op.create_index("ix_cases_project_id", "evaluation_cases", ["project_id"])
    op.create_index("ix_cases_agent_id", "evaluation_cases", ["agent_id"])
    op.create_index("ix_cases_input_digest", "evaluation_cases", ["input_digest"])

    op.create_table(
        "evaluation_suite_cases",
        sa.Column("suite_id", sa.String(36), sa.ForeignKey("evaluation_suites.id"), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("evaluation_cases.id"), primary_key=True),
        sa.Column("pinned_case_version", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "case_replays",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("evaluation_cases.id"), nullable=False),
        sa.Column("candidate_trace_id", sa.String(64), nullable=False),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_replays_case_id", "case_replays", ["case_id"])


def downgrade() -> None:
    op.drop_table("case_replays")
    op.drop_table("evaluation_suite_cases")
    op.drop_table("evaluation_cases")
    op.drop_table("evaluation_suites")
