"""Run all evaluators on a trace and persist the resulting Scores.

Score ids are deterministic per (trace, evaluator, target span) so re-evaluating a trace
(spans arrive across batches) replaces rather than duplicates via ReplacingMergeTree.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from tracely import clickhouse
from tracely.evaluators import EvalResult, RunContext, run_evaluator
from tracely.regression import _root, read_trace_spans

log = structlog.get_logger()

_NS = uuid.UUID("c0ffee00-0000-0000-0000-000000000001")  # stable namespace for eval score ids

_SCORE_COLS = [
    "project_id", "id", "trace_id", "observation_id", "agent_run_id", "name", "source",
    "data_type", "value", "string_value", "verdict", "evaluation_level", "comment",
    "created_at", "event_ts",
]


def _evaluator_specs(project_id: str) -> list[dict]:
    """The evaluators to run: the project's enabled Evaluator records. With none configured, online
    evaluation is a no-op (the Evaluations tab stays empty) — evaluators are opt-in, not auto-run."""
    try:
        from sqlalchemy import select

        from tracely.db import SyncSessionLocal
        from tracely.models import Evaluator

        with SyncSessionLocal() as s:
            rows = s.execute(
                select(Evaluator).where(Evaluator.project_id == project_id, Evaluator.enabled.is_(True))
            ).scalars().all()
        return [
            {"kind": r.kind, "config": r.config or {}, "score_name": r.score_name, "level": r.level}
            for r in rows
        ]
    except Exception as exc:  # table missing / DB hiccup -> no evals (rather than built-in noise)
        log.warning("evaluator_load_failed", error=str(exc))
        return []


def evaluate_run(project_id: str, trace_id: str) -> dict:
    client = clickhouse.get_client()
    spans = read_trace_spans(client, project_id, trace_id)
    if not spans:
        return {"scores": 0}
    root = _root(spans)
    agent_run_id = root.get("agent_run_id") or trace_id
    ctx = RunContext(project_id, trace_id, agent_run_id, spans, root)

    results: list[EvalResult] = []
    for spec in _evaluator_specs(project_id):
        try:
            results.extend(run_evaluator(spec["kind"], spec["config"], spec["score_name"], spec["level"], ctx))
        except Exception as exc:  # one bad evaluator must not sink the rest
            log.warning("evaluator_failed", evaluator=spec.get("score_name", "?"), error=str(exc))
    if not results:
        return {"scores": 0}

    now = datetime.now(timezone.utc)
    rows = []
    for r in results:
        sid = str(uuid.uuid5(_NS, f"{trace_id}:{r.name}:{r.target_span_id}"))
        rows.append([
            project_id, sid, trace_id, r.target_span_id or None, agent_run_id, r.name, "EVAL",
            r.data_type, r.value, "", r.verdict, r.level, r.comment, now, now,
        ])
    clickhouse.insert_rows(client, "scores", _SCORE_COLS, rows)

    # Cluster this run with similar failures (cheap structural signature).
    fail_results = [r for r in results if r.verdict == "FAIL"]
    if fail_results and root.get("agent_id"):
        try:
            from tracely import cluster
            from tracely.db import SyncSessionLocal

            with SyncSessionLocal() as s:
                cluster.cluster_failure(s, project_id, root["agent_id"], trace_id, fail_results, spans)
        except Exception as exc:  # clustering must never break ingestion
            log.warning("cluster_failed", trace_id=trace_id, error=str(exc))

    log.info("evaluated", trace_id=trace_id, scores=len(results), failures=len(fail_results))
    return {"scores": len(results), "failures": len(fail_results)}
