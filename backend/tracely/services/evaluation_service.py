"""Run a project's evaluators on traces/threads and persist the resulting `Scores`.

Score ids are deterministic per `(trace, evaluator, target span)` — and per `(thread, evaluator)`
for CONVERSATION-level evaluators — (see `ScoreWriter`) so re-evaluating as spans arrive across
batches, or re-running on demand from the UI, replaces rather than duplicates via
ReplacingMergeTree.

Entry points:
- `evaluate_trace`  — the ingest path (Celery) AND the on-demand path for one trace/turn.
  Runs every applicable evaluator: trace+span-level on the trace, conversation-level on the
  trace's thread (unless `skip_conversation`).
- `evaluate_thread` — the on-demand path for a whole conversation row: every turn, then the
  conversation-level evaluators once.

`on_result` (optional) fires once per persisted score with a JSON-ready dict — the SSE run
endpoint streams these straight into the grid.

Cluster-on-failure runs immediately after a trace's eval batch — the cheap structural signature
clustering, NOT the embedding rebuild (that's on-demand via `FailureIntelService`).
"""

from __future__ import annotations

import json
from typing import Callable

import structlog

from tracely.domain.evaluation.evaluators import EvalResult, RunContext, default_registry
from tracely.domain.evaluation.evaluators.base import CONVERSATION
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.clickhouse.score_writer import ScoreWriter
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db import repositories
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.services.structural_clustering_service import StructuralClusteringService

log = structlog.get_logger()

OnResult = Callable[[dict], None]


def _chain_payload(score: dict) -> dict:
    """A persisted score row → the compact context injected into the NEXT item's prompt in
    sequential mode (json results keep their schema shape; others collapse to value/verdict)."""
    sv = score.get("string_value")
    if sv:
        try:
            parsed = json.loads(sv)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    out = {"value": score.get("value"), "verdict": score.get("verdict") or None, "reason": score.get("comment") or None}
    return {k: v for k, v in out.items() if v is not None}


def _with_previous(spec: dict, chain: dict[str, dict]) -> dict:
    """A copy of `spec` carrying the previous turn's result of the same metric (no-op when the
    metric hasn't produced one yet — the first item simply grades without chain context)."""
    prev = chain.get(spec["score_name"])
    if prev is None:
        return spec
    return {**spec, "config": {**(spec.get("config") or {}), "__previous_result__": prev}}


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

    def evaluate_trace(
        self,
        project_id: str,
        trace_id: str,
        specs: list[dict] | None = None,
        on_result: OnResult | None = None,
        skip_conversation: bool = False,
    ) -> dict:
        spans = self.trace_reader.read_spans(project_id, trace_id)
        if not spans:
            return {"scores": 0}
        root = root_span(spans)
        agent_run_id = root.get("agent_run_id") or trace_id
        thread_id = next((s.get("conversation_id") for s in spans if s.get("conversation_id")), "") or trace_id
        if specs is None:
            specs = self.load_enabled_evaluators(project_id)
        trace_specs = [s for s in specs if s["level"] != CONVERSATION]
        conv_specs = [] if skip_conversation else [s for s in specs if s["level"] == CONVERSATION]

        ctx = RunContext(project_id, trace_id, agent_run_id, spans, root)
        results = self._dispatch_specs(trace_specs, ctx)
        if results:
            self.score_writer.write_eval_scores(
                project_id, trace_id, agent_run_id, results, thread_id=thread_id
            )
            self._emit(on_result, results, trace_id=trace_id, thread_id=thread_id)

        fail_results = [r for r in results if r.verdict == "FAIL"]
        if fail_results and root.get("agent_id"):
            self._cluster_failure(project_id, root["agent_id"], trace_id, fail_results, spans)

        conv_count = 0
        if conv_specs:
            conv_count = self._evaluate_conversation(project_id, thread_id, conv_specs, on_result)

        log.info(
            "evaluated", trace_id=trace_id, scores=len(results) + conv_count, failures=len(fail_results)
        )
        return {"scores": len(results) + conv_count, "failures": len(fail_results)}

    def evaluate_thread(
        self,
        project_id: str,
        thread_id: str,
        specs: list[dict] | None = None,
        on_result: OnResult | None = None,
    ) -> dict:
        """Evaluate a whole conversation row: every turn with the trace/span-level evaluators,
        then the conversation-level evaluators once across the full thread.

        Metrics with `config.execution_mode == "sequential"` chain across the turns: each
        trace's run receives the previous turn's result of the SAME metric (injected as
        `config.__previous_result__`; within a turn the judge chains its own steps)."""
        if specs is None:
            specs = self.load_enabled_evaluators(project_id)
        trace_specs = [s for s in specs if s["level"] != CONVERSATION]
        conv_specs = [s for s in specs if s["level"] == CONVERSATION]
        total = failures = 0
        if trace_specs:
            sequential_names = {
                s["score_name"] for s in trace_specs
                if str((s.get("config") or {}).get("execution_mode") or "batch") == "sequential"
            }
            chain: dict[str, dict] = {}

            def capture(score: dict) -> None:
                if score["name"] in sequential_names:
                    chain[score["name"]] = _chain_payload(score)
                if on_result is not None:
                    on_result(score)

            for tid in self.trace_reader.thread_trace_ids(project_id, thread_id):
                staged = [_with_previous(s, chain) for s in trace_specs]
                r = self.evaluate_trace(
                    project_id, tid, specs=staged, on_result=capture, skip_conversation=True
                )
                total += r.get("scores", 0)
                failures += r.get("failures", 0)
        if conv_specs:
            total += self._evaluate_conversation(project_id, thread_id, conv_specs, on_result)
        return {"scores": total, "failures": failures}

    # ── internals ─────────────────────────────────────────────────────────────

    def _evaluate_conversation(
        self, project_id: str, thread_id: str, specs: list[dict], on_result: OnResult | None
    ) -> int:
        """Run CONVERSATION-level specs over every span in the thread; persist thread-scoped."""
        spans = self.trace_reader.read_thread_spans(project_id, thread_id)
        if not spans:
            return 0
        ctx = RunContext(project_id, "", "", spans, root_span(spans), thread_id=thread_id)
        results = self._dispatch_specs(specs, ctx)
        if results:
            self.score_writer.write_eval_scores(project_id, "", "", results, thread_id=thread_id)
            self._emit(on_result, results, trace_id="", thread_id=thread_id)
        return len(results)

    def _dispatch_specs(self, specs: list[dict], ctx: RunContext) -> list[EvalResult]:
        results: list[EvalResult] = []
        for spec in specs:
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
    def _emit(
        on_result: OnResult | None, results: list[EvalResult], *, trace_id: str, thread_id: str
    ) -> None:
        if on_result is None:
            return
        for r in results:
            try:
                on_result({
                    "name": r.name,
                    "evaluation_level": r.level,
                    "observation_id": r.target_span_id or None,
                    "value": r.value,
                    "string_value": r.string_value,
                    "verdict": r.verdict,
                    "comment": r.comment,
                    "data_type": r.data_type,
                    "trace_id": None if r.level == CONVERSATION else trace_id,
                    "session_id": thread_id or None,
                })
            except Exception as exc:  # a slow/broken consumer must not sink the run
                log.warning("eval_emit_failed", error=str(exc))

    @staticmethod
    def load_enabled_evaluators(
        project_id: str, evaluator_ids: list[str] | None = None
    ) -> list[dict]:
        """The evaluators to run: the project's enabled `Evaluator` records (optionally narrowed
        to `evaluator_ids`). With none configured, online evaluation is a no-op — evaluators are
        opt-in, not auto-run."""
        try:
            with SyncSessionLocal() as s:
                return repositories.evaluator_enabled_specs(s, project_id, evaluator_ids)
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
