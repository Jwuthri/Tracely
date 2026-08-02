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

from tracely.config import settings
from tracely.domain import introspection
from tracely.domain.evaluation.evaluators import EvalResult, RunContext, default_registry
from tracely.domain.evaluation.evaluators.base import CONVERSATION, RUN
from tracely.domain.evaluation.targeting import spec_applies
from tracely.domain.evaluation.template_resolver import references_conversation_scope
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.clickhouse.score_writer import ScoreWriter
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db import repositories
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.llm import provider
from tracely.services.introspection_service import record
from tracely.services.structural_clustering_service import StructuralClusteringService

log = structlog.get_logger()

OnResult = Callable[[dict], None]


def _execution_mode(spec: dict) -> str:
    """The evaluator's item-ordering mode. Unknown/legacy values are safely batch."""
    mode = str((spec.get("config") or {}).get("execution_mode") or "batch").lower()
    return "sequential" if mode == "sequential" else "batch"


# The table calls its three levels conversation / message / step, so the recording does too — a
# recording that says "turn" or "AGENT_RUN" for the row the table labels `M` makes the reader
# translate between two vocabularies for the same thing.
_LEVEL_NAME = {
    "CONVERSATION": "conv",
    "AGENT_RUN": "msg",
    "SPAN": "step",
    "TOOL": "step",
    "GENERATION": "step",
    "CHAIN": "step",
}


def level_name(level: str) -> str:
    return _LEVEL_NAME.get(str(level).upper(), str(level or "?").lower())


def _spec_label(spec: dict) -> str:
    """`llm_judge · msg · basic` — what an evaluator column actually is, for the recording. The
    column name alone doesn't say whether it graded the message, each step, or the whole thread."""
    cfg = spec.get("config") or {}
    bits = [str(spec.get("kind") or "?"), level_name(spec.get("level", ""))]
    if spec.get("kind") == "llm_judge":
        bits.append("advanced" if cfg.get("is_advanced") else "basic")
        if cfg.get("model"):
            bits.append(str(cfg["model"]))
    if cfg.get("advisory"):
        bits.append("advisory")
    return " · ".join(bits)


def _subject_label(ctx) -> str:
    """What is being graded, in words — the recording's title line. Falls back to the id, but the
    id alone was the whole complaint: a row reading `0000…1f1ffee` tells you nothing."""
    from tracely.domain.evaluation.text import content_text

    text = (content_text(ctx.root.get("input")) or "").strip()
    where = "conversation" if not ctx.trace_id else "message"
    subject = ctx.trace_id or ctx.thread_id
    return f"grading {where} {subject}" + (f"\n\n{text[:600]}" if text else "")


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


def _topo_sort(specs: list[dict]) -> list[dict]:
    """Reorder specs so `depends_on` dependencies run before their dependents.
    Falls back to original order when a cycle is detected (logged as a warning)."""
    from collections import deque
    by_name = {s["score_name"]: s for s in specs}
    dependents: dict[str, list[str]] = {s["score_name"]: [] for s in specs}
    in_degree: dict[str, int] = {}
    for s in specs:
        deps = [d for d in ((s.get("config") or {}).get("depends_on") or []) if d in by_name]
        in_degree[s["score_name"]] = len(deps)
        for dep in deps:
            dependents[dep].append(s["score_name"])
    queue = deque(s for s in specs if in_degree[s["score_name"]] == 0)
    ordered: list[dict] = []
    while queue:
        spec = queue.popleft()
        ordered.append(spec)
        for dep_name in dependents[spec["score_name"]]:
            in_degree[dep_name] -= 1
            if in_degree[dep_name] == 0:
                queue.append(by_name[dep_name])
    if len(ordered) != len(specs):
        log.warning("eval_dependency_cycle", evaluators=[s["score_name"] for s in specs])
        return specs
    return ordered


def _inject_dependencies(spec: dict, completed: dict[str, list[dict]]) -> dict:
    """Return a copy of spec with its declared dependencies' results injected as
    `config.__dependencies__` — `{score_name: [{span_id, payload}, ...]}`. Only deps that have
    already produced results are included; the evaluator resolves the per-span slice it needs."""
    depends_on = (spec.get("config") or {}).get("depends_on") or []
    deps = {name: completed[name] for name in depends_on if name in completed}
    if not deps:
        return spec
    return {**spec, "config": {**(spec.get("config") or {}), "__dependencies__": deps}}


def _needs_thread_context(specs: list[dict]) -> bool:
    """True when a message/step-level eval needs the WHOLE thread fetched (one extra read), which
    is two cases:

    - an advanced llm_judge referencing a conversation-scoped variable (`@HISTORY`/`@MESSAGES`/
      `@PREVIOUS_*`/`@GOAL`/`@LIST_AGENT`). Purely step-local advanced columns (only
      `@CURRENT_STEP.*` / `@METRIC_PREVIOUS_RESULT`) pay nothing;
    - any SEQUENTIAL judge, which by definition grades this message in the light of the earlier
      turns — without the thread it would fall back to grading it alone, i.e. batch.
    """
    return any(
        s.get("kind") == "llm_judge"
        and (
            _execution_mode(s) == "sequential"
            or (
                (s.get("config") or {}).get("is_advanced")
                and references_conversation_scope((s.get("config") or {}).get("template_variables"))
            )
        )
        for s in specs
    )


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
        thread_spans: list[dict] | None = None,
        execution_mode: str | None = None,
        apply_targeting: bool = False,
    ) -> dict:
        spans = self.trace_reader.read_spans(project_id, trace_id)
        if not spans:
            return {"scores": 0}
        # Second guard on the infinite loop (the first is at ingest, which never schedules these).
        # Both are needed: a monitor, a manual re-run, or a backfill can call this directly, and
        # grading a recording of a grading would record another one, without end.
        if any(s.get("internal_kind") for s in spans):
            return {"scores": 0, "skipped": "internal"}
        root = root_span(spans)
        agent_run_id = root.get("agent_run_id") or trace_id
        thread_id = next((s.get("conversation_id") for s in spans if s.get("conversation_id")), "") or trace_id
        if specs is None:
            # Auto (on-ingest) run: honor each evaluator's targeting + sampling. An explicit
            # on-demand run passes `specs` and always grades (the user chose them).
            specs = self._apply_targeting(
                project_id, self.load_enabled_evaluators(project_id), root, trace_id
            )
        elif apply_targeting:
            # `evaluate_thread` reuses an already-loaded list to avoid treating its automatic
            # settled-thread pass like an on-demand run. Keep the same targeting guarantee that
            # the ordinary ingest path has, but decide it against this individual trace.
            specs = self._apply_targeting(project_id, specs, root, trace_id)
        trace_specs = [s for s in specs if s["level"] != CONVERSATION]
        if execution_mode is not None:
            trace_specs = [s for s in trace_specs if _execution_mode(s) == execution_mode]
        conv_specs = [] if skip_conversation else [s for s in specs if s["level"] == CONVERSATION]

        # Advanced judges that read @HISTORY/@PREVIOUS_* need the whole thread (one extra read,
        # gated). `evaluate_thread` passes `thread_spans` in so the per-turn loop fetches once.
        if thread_spans is None and thread_id != trace_id and _needs_thread_context(trace_specs):
            thread_spans = self.trace_reader.read_thread_spans(project_id, thread_id)

        ctx = RunContext(
            project_id, trace_id, agent_run_id, spans, root,
            thread_id=thread_id, thread_spans=thread_spans,
        )
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
        return {
            "scores": len(results) + conv_count,
            "failures": len(fail_results),
            "thread_id": thread_id,
        }

    def evaluate_thread(
        self,
        project_id: str,
        thread_id: str,
        specs: list[dict] | None = None,
        on_result: OnResult | None = None,
        execution_mode: str | None = None,
    ) -> dict:
        """Evaluate a whole conversation row: every turn with the trace/span-level evaluators,
        then the conversation-level evaluators once across the full thread.

        Metrics with `config.execution_mode == "sequential"` chain across the turns: each
        trace's run receives the previous turn's result of the SAME metric (injected as
        `config.__previous_result__`; within a turn the judge chains its own steps)."""
        automatic = specs is None
        if specs is None:
            specs = self.load_enabled_evaluators(project_id)
        trace_specs = [s for s in specs if s["level"] != CONVERSATION]
        if execution_mode is not None:
            trace_specs = [s for s in trace_specs if _execution_mode(s) == execution_mode]
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

            # Fetch the thread's spans ONCE (not once per turn) when an advanced judge needs the
            # full transcript — `evaluate_trace` reuses what we pass instead of re-reading.
            thread_spans = (
                self.trace_reader.read_thread_spans(project_id, thread_id)
                if _needs_thread_context(trace_specs) else None
            )
            for tid in self.trace_reader.thread_trace_ids(project_id, thread_id):
                staged = [_with_previous(s, chain) for s in trace_specs]
                r = self.evaluate_trace(
                    project_id, tid, specs=staged, on_result=capture, skip_conversation=True,
                    thread_spans=thread_spans, apply_targeting=automatic,
                )
                total += r.get("scores", 0)
                failures += r.get("failures", 0)
        if conv_specs:
            total += self._evaluate_conversation(
                project_id, thread_id, conv_specs, on_result, apply_targeting=automatic
            )
        return {"scores": total, "failures": failures}

    def _apply_targeting(
        self, project_id: str, specs: list[dict], root: dict, trace_id: str
    ) -> list[dict]:
        """Drop evaluators whose target_agent/target_env don't match this trace, then roll each
        one's sampling die. The agent slug is resolved only when some evaluator actually targets
        an agent (avoids a DB hit on the common no-targeting path)."""
        agent_id = root.get("agent_id") or ""
        env = root.get("env") or ""
        agent_slug = ""
        if agent_id and any((s.get("target_agent") or "").strip() for s in specs):
            try:
                with SyncSessionLocal() as sess:
                    agent_slug = repositories.agent_slug(sess, project_id, agent_id)
            except Exception as exc:  # slug lookup must never break evaluation
                log.warning("agent_slug_lookup_failed", agent_id=agent_id, error=str(exc))
        return [
            s
            for s in specs
            if spec_applies(
                s, agent_id=agent_id, agent_slug=agent_slug, env=env, trace_id=trace_id
            )
        ]

    # ── answer-quality grading for the CI gate (non-persisting) ─────────────────

    def quality_specs(
        self, project_id: str, only_names: list[str] | None = None
    ) -> list[dict]:
        """The answer-quality judge(s) the gate replays — enabled AGENT_RUN-level LLM judges.

        Narrowed (in priority order) to: the explicit `only_names` a case recorded it was promoted
        from; else the single canonical answer-quality judge (`settings.gate_quality_score_name`)
        so the gate enforces "the answer is wrong/unfaithful", NOT every AGENT_RUN judge (some are
        signal detectors with inverted thresholds — blocking on those is noise). Blank config →
        every AGENT_RUN llm_judge (legacy broad behavior)."""
        specs = [
            s
            for s in self.load_enabled_evaluators(project_id)
            if s["kind"] == "llm_judge" and s["level"] == RUN
        ]
        if only_names:
            wanted = set(only_names)
            specs = [s for s in specs if s["score_name"] in wanted]
        elif settings.gate_quality_score_name:
            specs = [s for s in specs if s["score_name"] == settings.gate_quality_score_name]
        return specs

    def grade_trace_quality(
        self,
        project_id: str,
        spans: list[dict],
        only_names: list[str] | None = None,
        specs: list[dict] | None = None,
    ) -> list[EvalResult]:
        """Run answer-quality judge(s) on an arbitrary set of spans (a promote source trace or a
        replayed gate trace) WITHOUT persisting — returns the `EvalResult`s so the caller can
        gate on them. Empty when there are no quality judges, no spans, or grading fails (a
        missing LLM key degrades to structural-only, never a false fail)."""
        if specs is None:
            specs = self.quality_specs(project_id, only_names)
        if not spans or not specs:
            return []
        root = root_span(spans)
        ctx = RunContext(
            project_id,
            root.get("trace_id", "") or "",
            root.get("agent_run_id", "") or "",
            spans,
            root,
        )
        return self._dispatch_specs(specs, ctx)

    # ── internals ─────────────────────────────────────────────────────────────

    def evaluate_conversation(
        self, project_id: str, thread_id: str, on_result: OnResult | None = None
    ) -> dict:
        """Grade a thread with its CONVERSATION-level evaluators, once.

        Split out of `evaluate_trace` because it must NOT run per turn: the ingest path calls
        `evaluate_trace` for every turn, so an inline conversation pass re-graded the whole thread
        on each one — the same judge, the same transcript, N times, N times the spend, N identical
        rows in the recording. Callers run this once after the thread settles (the ingest hop
        debounces it per thread; the gate calls it after driving every turn).
        """
        specs = [
            s for s in self.load_enabled_evaluators(project_id) if s["level"] == CONVERSATION
        ]
        if not specs:
            return {"scores": 0}
        return {
            "scores": self._evaluate_conversation(
                project_id, thread_id, specs, on_result, apply_targeting=True
            )
        }

    def _evaluate_conversation(
        self,
        project_id: str,
        thread_id: str,
        specs: list[dict],
        on_result: OnResult | None,
        apply_targeting: bool = False,
    ) -> int:
        """Run CONVERSATION-level specs over every span in the thread; persist thread-scoped."""
        spans = self.trace_reader.read_thread_spans(project_id, thread_id)
        if not spans:
            return 0
        if apply_targeting:
            specs = self._apply_conversation_targeting(project_id, specs, spans, thread_id)
        if not specs:
            return 0
        ctx = RunContext(project_id, "", "", spans, root_span(spans), thread_id=thread_id)
        results = self._dispatch_specs(specs, ctx)
        if results:
            self.score_writer.write_eval_scores(project_id, "", "", results, thread_id=thread_id)
            self._emit(on_result, results, trace_id="", thread_id=thread_id)
        return len(results)

    def _apply_conversation_targeting(
        self, project_id: str, specs: list[dict], spans: list[dict], thread_id: str
    ) -> list[dict]:
        """Target a whole-thread evaluator once, deterministically.

        A conversation can include several agent runs. Agent/environment targeting therefore
        matches when *any* turn belongs to the selected target, while sampling is keyed by the
        thread id because the conversation — not an arbitrary turn — is the subject being scored.
        """
        by_trace: dict[str, list[dict]] = {}
        for span in spans:
            by_trace.setdefault(span.get("trace_id") or "", []).append(span)
        roots = [root_span(trace_spans) for trace_spans in by_trace.values()]
        slug_by_agent: dict[str, str] = {}

        def slug_for(agent_id: str) -> str:
            if not agent_id:
                return ""
            if agent_id not in slug_by_agent:
                try:
                    with SyncSessionLocal() as sess:
                        slug_by_agent[agent_id] = repositories.agent_slug(sess, project_id, agent_id)
                except Exception as exc:
                    log.warning("agent_slug_lookup_failed", agent_id=agent_id, error=str(exc))
                    slug_by_agent[agent_id] = ""
            return slug_by_agent[agent_id]

        applicable: list[dict] = []
        for spec in specs:
            target_only = {**spec, "sampling": 1.0}
            target_matches = any(
                spec_applies(
                    target_only,
                    agent_id=root.get("agent_id") or "",
                    agent_slug=slug_for(root.get("agent_id") or ""),
                    env=root.get("env") or "",
                    trace_id=thread_id,
                )
                for root in roots
            )
            if not target_matches:
                continue
            # Reuse the canonical deterministic sampler after separating it from target matching.
            sample_only = {**spec, "target_agent": "", "target_env": ""}
            if spec_applies(sample_only, agent_id="", agent_slug="", env="", trace_id=thread_id):
                applicable.append(spec)
        return applicable

    def _dispatch_specs(self, specs: list[dict], ctx: RunContext) -> list[EvalResult]:
        specs = _topo_sort(specs)
        # Each completed evaluator's results, kept per `span_id` so a dependent grading at step
        # level can line up THIS step's prerequisite verdicts (a trace/conversation result lands
        # under span_id "" — see `_inject_dependencies` / the judge's per-span resolution).
        completed: dict[str, list[dict]] = {}
        results: list[EvalResult] = []
        subject = ctx.trace_id or ctx.thread_id
        # THE chokepoint every eval path funnels through (on-ingest, on-demand run, gate quality
        # grading) — scoping here once covers every llm_judge call this dispatch makes, and the
        # recording captures each of those calls' prompt and reply without per-evaluator wiring.
        # The three eval levels land on the traces table's three levels: every recording about
        # one conversation shares a namespaced conversation id, so a 3-turn thread shows as ONE
        # row with 4 runs (turn 1, 2, 3, and the conversation-level pass) rather than 4 orphans.
        thread = ctx.thread_id or ctx.trace_id
        with provider.use_project_key(ctx.project_id), record(
            introspection.EVAL, subject,
            # `{level}`/`{n}` are filled per emitted trace: one dispatch grades message columns
            # AND step columns, and they land as two rows, each titled for what it actually did.
            "eval · {level} · {n} column(s)", project_id=ctx.project_id,
            subject_label=_subject_label(ctx),
            conversation_id=f"eval:{thread}" if thread else "",
            # The conversation-level pass re-grades the whole thread every time it grows, so its
            # recording replaces the last one instead of stacking a near-identical run beside it.
            # A message pass grades one message, once — nothing to replace.
            stable=not ctx.trace_id,
        ) as rec:
            for spec in specs:
                spec = _inject_dependencies(spec, completed)
                if rec:
                    # One span per evaluator, named for the column, describing WHICH kind at
                    # WHAT level — "why did this column say that" starts with knowing what it is.
                    rec.label = spec.get("score_name") or spec.get("kind") or "evaluator"
                    rec.describe(input=_spec_label(spec), meta={
                        "evaluator": spec.get("score_name", ""),
                        # The table's word for it (msg/step/conv), not the enum — and the key the
                        # recording splits its traces on, so a row is one level throughout.
                        "level": level_name(spec.get("level", "")),
                        "kind": spec.get("kind", ""),
                    })
                try:
                    new_results = self.registry.dispatch(
                        spec["kind"], spec["config"], spec["score_name"], spec["level"], ctx
                    )
                    if rec:
                        # The verdict lands ON the evaluator's own span rather than in a child
                        # "verdict" event — one row per evaluator, not two.
                        rec.describe(output="; ".join(
                            f"{r.verdict or r.value}" + (f" — {r.comment}" if r.comment else "")
                            for r in new_results
                        ) or "(no result — not applicable to this trace)")
                    results.extend(new_results)
                    if new_results:
                        completed[spec["score_name"]] = [
                            {
                                "span_id": r.target_span_id,
                                "payload": _chain_payload({
                                    "string_value": r.string_value, "value": r.value,
                                    "verdict": r.verdict, "comment": r.comment,
                                }),
                            }
                            for r in new_results
                        ]
                except Exception as exc:  # one bad evaluator must not sink the rest
                    if rec:
                        rec.describe(error=str(exc)[:500])
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
