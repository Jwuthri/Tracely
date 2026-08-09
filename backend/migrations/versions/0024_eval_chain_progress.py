"""Sequential evaluation: chain progress + retire the `category` output type.

`eval_chain_progress` records how far a sequential evaluator's durable conversation has advanced
through a thread — the ordered turn ids already graded, plus the last result payload (the next
turn's `CFG_PREVIOUS` seed). It lets the settled-thread pass grade only the NEW turns instead of
re-grading the whole thread on every settle; a stored prefix that no longer matches the thread's
turn order (late-arriving trace, backfill) makes the pass rebuild from turn 1.

The `category` output type is retired: the Add Column builder already edits legacy category
columns as `json` + an enum schema, so this backfills the same conversion the frontend applied
on edit (`categories` → an enum-constrained `category` field; `fail_categories` had no `json`
equivalent and is dropped — it predates thresholds on json scores and nothing shipped uses it).

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-09
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_chain_progress",
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("score_name", sa.String(80), nullable=False),
        sa.Column("thread_id", sa.String(256), nullable=False),
        sa.Column("turn_ids", sa.JSON(), nullable=False),
        sa.Column("last_payload", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("project_id", "score_name", "thread_id"),
    )

    conn = op.get_bind()
    rows = conn.execute(
        text("SELECT id, config FROM evaluators WHERE config IS NOT NULL")
    ).fetchall()
    for row_id, config in rows:
        cfg = config if isinstance(config, dict) else json.loads(config or "{}")
        if str(cfg.get("output_type") or "") != "category":
            continue
        categories = [str(c) for c in (cfg.get("categories") or [])]
        cfg = {k: v for k, v in cfg.items() if k not in ("categories", "fail_categories")}
        cfg["output_type"] = "json"
        cfg["output_schema"] = {
            "type": "object",
            "properties": {
                "category": (
                    {"type": "string", "enum": categories} if categories else {"type": "string"}
                ),
                "reason": {"type": "string", "description": "why this category fits"},
            },
            "required": ["category"],
        }
        conn.execute(
            text("UPDATE evaluators SET config = CAST(:config AS json) WHERE id = :id"),
            {"config": json.dumps(cfg), "id": row_id},
        )


def downgrade() -> None:
    op.drop_table("eval_chain_progress")
    # the category→json config rewrite is not reversed: json + enum is a superset shape
