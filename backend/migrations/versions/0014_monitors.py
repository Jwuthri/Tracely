"""monitors: threshold rules over the regression-loop metrics + Slack/webhook notifications.

One row per monitor. A monitor watches a project's online scores (and/or the trace failure rate)
over a sliding window — when its `condition` fires, it POSTs to each configured `channel` and
records `last_fired_at` / `last_fired_summary`. The condition body is a JSON dict so the engine
can evolve (`fail_rate_over`, `score_below`, …) without a schema change per condition type.

Per-monitor `min_interval_seconds` dedupes alerts (a noisy condition won't page you every minute).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        # Optional scope: when set, the monitor only considers traces for this agent (matched on
        # `agents.slug` or `agents.id`). Empty = the whole project. Plain string (not FK) so
        # deleting an agent doesn't cascade through the monitor.
        sa.Column("target_agent", sa.String(80), nullable=False, server_default=""),
        # The condition the monitor watches:
        #   {"type": "fail_rate_over", "score_name": "tracely.run.quality",
        #    "window_minutes": 60, "min_samples": 20, "threshold": 0.20}
        #   {"type": "score_below", "score_name": "tracely.conv.goal_success",
        #    "window_minutes": 60, "min_samples": 10, "threshold": 0.6}
        #   {"type": "trace_failure_rate", "window_minutes": 60, "min_samples": 50,
        #    "threshold": 0.25}
        sa.Column("condition", sa.JSON(), nullable=False),
        # Where to send alerts. List of dicts: [{"type": "slack", "url": "..."},
        # {"type": "webhook", "url": "...", "headers": {...}}]. Empty = the monitor still
        # evaluates (last_fired_* records the fire), just no notification leaves the box.
        sa.Column("channels", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Anti-spam: don't re-notify for the same monitor unless this many seconds have passed
        # since `last_fired_at`. Default 15 min.
        sa.Column("min_interval_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_summary", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "name", name="uq_monitors_project_name"),
    )
    op.create_index(
        "ix_monitors_project_enabled", "monitors", ["project_id", "enabled"]
    )


def downgrade() -> None:
    op.drop_index("ix_monitors_project_enabled", table_name="monitors")
    op.drop_table("monitors")
