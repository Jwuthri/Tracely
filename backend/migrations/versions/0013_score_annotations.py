"""score_annotations: human labels on judge scores (judge-vs-human calibration)

A reviewer agrees/disagrees with an evaluator's verdict on a target (trace / span / thread). One row
per (project, score natural-key, labeler). We snapshot the judge verdict at label time so the
agreement % is a pure Postgres query (no ClickHouse join) and reflects what the human reviewed.

Score natural key = (name, evaluation_level, trace_id, session_id, observation_id) — empty-string
(not NULL) defaults so the unique constraint behaves.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "score_annotations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        # the score's natural key (matches infrastructure.clickhouse `scores`)
        sa.Column("score_name", sa.String(128), nullable=False),
        sa.Column("evaluation_level", sa.String(32), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("session_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("observation_id", sa.String(64), nullable=False, server_default=""),
        # the labels
        sa.Column("judge_verdict", sa.String(32), nullable=False, server_default=""),  # snapshot
        sa.Column("human_verdict", sa.String(32), nullable=False),  # PASS | FAIL | …
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("labeled_by", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "project_id", "score_name", "evaluation_level", "trace_id", "session_id",
            "observation_id", "labeled_by", name="uq_score_annotations_target_labeler",
        ),
    )
    op.create_index(
        "ix_score_annotations_project_name", "score_annotations", ["project_id", "score_name"]
    )
    op.create_index(
        "ix_score_annotations_project_trace", "score_annotations", ["project_id", "trace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_score_annotations_project_trace", table_name="score_annotations")
    op.drop_index("ix_score_annotations_project_name", table_name="score_annotations")
    op.drop_table("score_annotations")
