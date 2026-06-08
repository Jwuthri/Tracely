"""Run a project's enabled evaluators on a trace and persist the resulting `Scores`.

Score ids are deterministic per `(trace, evaluator, target span)` (see `ScoreWriter`) so
re-evaluating a trace as spans arrive across batches replaces rather than duplicates via
ReplacingMergeTree.

Cluster-on-failure runs immediately after the eval batch — the cheap structural signature
clustering, NOT the embedding rebuild (that's on-demand via `FailureIntelService`).
"""

from __future__ import annotations

import structlog

from tracely.domain.evaluation.evaluators import EvalResult, RunContext, default_registry
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.clickhouse.score_writer import ScoreWriter
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import Evaluator
from tracely.services.structural_clustering_service import StructuralClusteringService

log = structlog.get_logger()


class EvaluationService:
    """Online evaluation orchestrator. Stateless across calls; lazy-constructs the trace
    reader / score writer / structural clusterer."""

    def __init__(
        self,
        trace_reader: TraceReader | None = None,
        score_writer: ScoreWriter | None = None,
        registry=default_registry,
    ) -> None:
        self.trace_reader = trace_reader or TraceReader()
        self.score_writer = score_writer or ScoreWriter(self.trace_reader.client)
        self.registry = registry

    def evaluate_trace(self, project_id: str, trace_id: str) -> dict:
        spans = self.trace_reader.read_spans(project_id, trace_id)
        if not spans:
            return {"scores": 0}
        root = root_span(spans)
        agent_run_id = root.get("agent_run_id") or trace_id
        ctx = RunContext(project_id, trace_id, agent_run_id, spans, root)

        results = self._run_enabled_evaluators(project_id, ctx)
        if not results:
            return {"scores": 0}

        self.score_writer.write_eval_scores(project_id, trace_id, agent_run_id, results)

        fail_results = [r for r in results if r.verdict == "FAIL"]
        if fail_results and root.get("agent_id"):
            self._cluster_failure(project_id, root["agent_id"], trace_id, fail_results, spans)

        log.info(
            "evaluated", trace_id=trace_id, scores=len(results), failures=len(fail_results)
        )
        return {"scores": len(results), "failures": len(fail_results)}

    # ── internals ─────────────────────────────────────────────────────────────

    def _run_enabled_evaluators(
        self, project_id: str, ctx: RunContext
    ) -> list[EvalResult]:
        results: list[EvalResult] = []
        for spec in self._load_enabled_evaluators(project_id):
            try:
                results.extend(self.registry.dispatch(
                    spec["kind"], spec["config"], spec["score_name"], spec["level"], ctx
                ))
            except Exception as exc:  # one bad evaluator must not sink the rest
                log.warning(
                    "evaluator_failed", evaluator=spec.get("score_name", "?"), error=str(exc)
                )
        return results

    @staticmethod
    def _load_enabled_evaluators(project_id: str) -> list[dict]:
        """The evaluators to run: the project's enabled `Evaluator` records. With none
        configured, online evaluation is a no-op — evaluators are opt-in, not auto-run."""
        try:
            from sqlalchemy import select

            with SyncSessionLocal() as s:
                rows = s.execute(
                    select(Evaluator).where(
                        Evaluator.project_id == project_id, Evaluator.enabled.is_(True)
                    )
                ).scalars().all()
            return [
                {"kind": r.kind, "config": r.config or {}, "score_name": r.score_name, "level": r.level}
                for r in rows
            ]
        except Exception as exc:  # table missing / DB hiccup -> no evals
            log.warning("evaluator_load_failed", error=str(exc))
            return []

    @staticmethod
    def _cluster_failure(
        project_id: str,
        agent_id: str,
        trace_id: str,
        fail_results: list[EvalResult],
        spans: list[dict],
    ) -> None:
        """Cheap structural clustering — runs in its own session so a clustering hiccup never
        breaks the eval insert. Exceptions are swallowed (logged) for the same reason."""
        try:
            with SyncSessionLocal() as s:
                StructuralClusteringService(s).cluster_failure(
                    project_id, agent_id, trace_id, fail_results, spans
                )
        except Exception as exc:
            log.warning("cluster_failed", trace_id=trace_id, error=str(exc))
