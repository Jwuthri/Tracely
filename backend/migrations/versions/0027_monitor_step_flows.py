"""alert rule flows: a monitor's action becomes a DAG of steps instead of a channel list.

A monitor was "condition → POST to these channels". This turns the action half into a small
visual flow: `monitor_steps` holds one row per step (the step id IS the React Flow node id, so an
edge in `monitors.flow_layout` points straight at a step row — no mapping table), and
`monitor_executions` records every run with a per-step audit trail (`step_results`), including the
POST-Jinja value of every field that was actually sent.

The graph lives inside `monitors.flow_layout` as React Flow's own `{nodes, edges}` JSON and the
engine reads that same JSON — one source of truth, no join to reconstruct a graph. Edges are NOT
a table on purpose.

`monitors.channels` stays: a monitor with no steps keeps dispatching to its channels, which is
what every row created before this migration (and the assistant's `create_alert` tool) does.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # React Flow's own node/edge JSON. Stored opaquely (positions, styling, whatever the canvas
    # wants) with ONE guarantee the API enforces: every entry in `edges` has string
    # `source`/`target`. That is the only part the engine reads.
    op.add_column("monitors", sa.Column("flow_layout", sa.JSON(), nullable=True))

    op.create_table(
        "monitor_steps",
        # Not a uuid column by accident: this id doubles as the canvas node id, so the client
        # generates it and an edge can reference it before the row exists.
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "monitor_id",
            sa.String(36),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(120), nullable=False),
        # condition | webhook | send_email | slack | llm_prompt | python_expression
        sa.Column("step_type", sa.String(32), nullable=False),
        # Shape depends on `step_type` — JSON so a new step type is code, not a migration.
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_monitor_steps_monitor_order", "monitor_steps", ["monitor_id", "order_index"])

    op.create_table(
        "monitor_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "monitor_id",
            sa.String(36),
            sa.ForeignKey("monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        # What fired it: the event type (`gate_failed`, …) plus the id of the thing that happened,
        # so the run links back to the gate / trace / cluster it reported on.
        sa.Column("trigger_type", sa.String(40), nullable=False, server_default=""),
        sa.Column("subject_id", sa.String(120), nullable=False, server_default=""),
        # running | completed | failed | skipped ("skipped" = a condition step gated it off)
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # One audit row per step: result, error, rendered_config, ancestor_step_ids.
        sa.Column("step_results", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        # A test run is a real execution with real side effects, flagged so the history can say so.
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_monitor_executions_monitor_started",
        "monitor_executions",
        ["monitor_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_monitor_executions_monitor_started", table_name="monitor_executions")
    op.drop_table("monitor_executions")
    op.drop_index("ix_monitor_steps_monitor_order", table_name="monitor_steps")
    op.drop_table("monitor_steps")
    op.drop_column("monitors", "flow_layout")
