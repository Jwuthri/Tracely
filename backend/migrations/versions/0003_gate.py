"""ci/cd gate: gate_runs, gate_cases

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gate_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("env", sa.String(16), nullable=False, server_default="ci"),
        sa.Column("git_ref", sa.String(80), nullable=False, server_default=""),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="RUNNING"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_gate_runs_project_id", "gate_runs", ["project_id"])
    op.create_index("ix_gate_runs_agent_id", "gate_runs", ["agent_id"])

    op.create_table(
        "gate_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gate_run_id", sa.String(36), sa.ForeignKey("gate_runs.id"), nullable=False),
        sa.Column("evaluation_case_id", sa.String(36), sa.ForeignKey("evaluation_cases.id"), nullable=False),
        sa.Column("candidate_trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("verdict", sa.String(8), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
    )
    op.create_index("ix_gate_cases_gate_run_id", "gate_cases", ["gate_run_id"])


def downgrade() -> None:
    op.drop_table("gate_cases")
    op.drop_table("gate_runs")
