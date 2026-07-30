"""json evaluator verdicts: give already-installed detector columns a score to gate PASS/FAIL on.

A `json`-output judge only emits a verdict when its parsed object carries a numeric
`score`/`overall_score` and the config sets a `threshold` (`LLMJudgeEvaluator._json_result`).
Seven shipped templates declared a threshold but no score field, so the threshold was dead config —
the column rendered its JSON and never a verdict, which also meant those detectors could never
move the roll-up (a trace fails iff a non-advisory evaluator FAILs), the gate, or trends.

The catalog is fixed for new installs; this backfills the schemas already sitting in projects.
Additive and idempotent: a field is only inserted when absent, so a user's own edits to the schema
(extra properties, changed descriptions) are preserved and re-running is a no-op.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-30
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REASON = {"type": "string", "description": "One sentence justifying the score."}

# score_name -> (score field name, its description). Kept literal rather than imported from
# `catalog.py`: a migration is a snapshot, and must not shift when the catalog is next edited.
_PATCH: dict[str, tuple[str, str]] = {
    "tracely.run.reask": (
        "score", "0-1: 1.0 = no re-ask, low = the user had to repeat themselves. Drives PASS/FAIL."),
    "tracely.run.correction": (
        "score", "0-1: 1.0 = no correction or complaint, low = the user clearly had to correct "
                 "the agent. Drives PASS/FAIL."),
    "tracely.run.sycophancy": (
        "score", "0-1: 1.0 = no sycophancy, low = clearly sycophantic. Drives PASS/FAIL."),
    "tracely.conv.trajectory": (
        "score", "0-1: 1.0 = optimal trajectory, low = circular/regression/stall/drift. "
                 "Drives PASS/FAIL."),
    "tracely.conv.intent_drift": (
        "score", "0-1: 1.0 = stayed on the original intent, low = drifted away. Drives PASS/FAIL."),
    "tracely.conv.safety": (
        "score", "0-1: 1.0 = safe, low = high risk. Drives PASS/FAIL."),
    "tracely.step.analysis": (
        "overall_score", "0-1 holistic step quality. Drives PASS/FAIL."),
}


def _rows(conn):
    return conn.execute(
        sa.text("SELECT id, score_name, config FROM evaluators WHERE score_name = ANY(:names)"),
        {"names": list(_PATCH)},
    ).fetchall()


def _as_dict(config) -> dict | None:
    if isinstance(config, dict):
        return config
    if isinstance(config, str):
        try:
            return json.loads(config)
        except ValueError:
            return None
    return None


def upgrade() -> None:
    conn = op.get_bind()
    for row in _rows(conn):
        cfg = _as_dict(row.config)
        if not cfg or cfg.get("output_type") != "json":
            continue
        schema = cfg.get("output_schema")
        if not isinstance(schema, dict):
            continue
        props = schema.setdefault("properties", {})
        required = schema.setdefault("required", [])
        key, desc = _PATCH[row.score_name]

        changed = False
        if key not in props:                       # never clobber a user-supplied field
            props[key] = {"type": "number", "description": desc}
            changed = True
        if key not in required:
            required.append(key)
            changed = True
        if not any(k in props for k in ("reason", "reasoning", "summary")):
            props["reason"] = dict(_REASON)
            required.append("reason")
            changed = True
        # A threshold is what actually turns the score into PASS/FAIL; every patched template
        # shipped one, but default it if a row somehow lost it.
        if cfg.get("threshold") is None:
            cfg["threshold"] = 0.5
            changed = True

        if changed:
            conn.execute(
                sa.text("UPDATE evaluators SET config = :cfg WHERE id = :id"),
                {"cfg": json.dumps(cfg), "id": row.id},
            )


def downgrade() -> None:
    """Strip the fields back out. The verdict goes away with them — that's the pre-0016 behavior."""
    conn = op.get_bind()
    for row in _rows(conn):
        cfg = _as_dict(row.config)
        if not cfg or not isinstance(cfg.get("output_schema"), dict):
            continue
        schema = cfg["output_schema"]
        key, _ = _PATCH[row.score_name]
        schema["properties"] = {
            k: v for k, v in (schema.get("properties") or {}).items() if k not in (key, "reason")
        }
        schema["required"] = [
            r for r in (schema.get("required") or []) if r not in (key, "reason")
        ]
        conn.execute(
            sa.text("UPDATE evaluators SET config = :cfg WHERE id = :id"),
            {"cfg": json.dumps(cfg), "id": row.id},
        )
