"""emulated conversations: agent endpoints + scenarios, and gate cases that point at either.

Adds the two tables behind endpoint-driven multi-turn testing (`agent_endpoints`, `scenarios`)
and widens `gate_cases` so one gate run can mix replayed regression cases with emulated
conversations: `evaluation_case_id` becomes nullable and a nullable `scenario_id` sits beside it.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_endpoints",
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), index=True),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("auth_header", sa.String(64), server_default="Authorization"),
        sa.Column("auth_scheme", sa.String(32), server_default="Bearer"),
        sa.Column("token_encrypted", sa.String(2000), server_default=""),
        sa.Column("extra_headers", sa.JSON(), server_default="{}"),
        sa.Column("reply_path", sa.String(200), server_default=""),
        sa.Column("session_key", sa.String(120), server_default="conversation_id"),
        sa.Column("timeout_s", sa.Integer(), server_default="60"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), index=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), index=True),
        sa.Column("title", sa.String(512), server_default=""),
        sa.Column("kind", sa.String(16), server_default="SCRIPTED"),
        sa.Column("turns", sa.JSON(), server_default="[]"),
        sa.Column("goal", sa.Text(), server_default=""),
        sa.Column("max_turns", sa.Integer(), server_default="6"),
        sa.Column("source_thread_id", sa.String(64), server_default=""),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true()),
        sa.Column("created_by", sa.String(128), server_default="ui"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scenario_project_agent", "scenarios", ["project_id", "agent_id"])

    # A gate case is now EITHER a replayed regression case OR an emulated conversation.
    op.alter_column("gate_cases", "evaluation_case_id", existing_type=sa.String(36), nullable=True)
    op.add_column(
        "gate_cases",
        sa.Column("scenario_id", sa.String(36), sa.ForeignKey("scenarios.id"), nullable=True),
    )
    # "NO_COVERAGE"/"UNGRADED" don't fit the old 8-char verdict column.
    op.alter_column(
        "gate_cases", "verdict", existing_type=sa.String(8), type_=sa.String(12), nullable=False
    )


def downgrade() -> None:
    op.alter_column(
        "gate_cases", "verdict", existing_type=sa.String(12), type_=sa.String(8), nullable=False
    )
    op.drop_column("gate_cases", "scenario_id")
    op.alter_column("gate_cases", "evaluation_case_id", existing_type=sa.String(36), nullable=False)
    op.drop_index("ix_scenario_project_agent", table_name="scenarios")
    op.drop_table("scenarios")
    op.drop_table("agent_endpoints")
