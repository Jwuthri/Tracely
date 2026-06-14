"""LLM-as-judge evaluator — one class, three granularities, every call through LangChain's
`create_agent` on OpenRouter (see `infrastructure.llm.provider`).

The judge's rubric prompt becomes the agent's SYSTEM prompt; the trace content (request /
answer / tool grounding, thread transcript, or step I/O) is the user message; and
`config.output_type` picks the structured response schema the agent must return:

- level CONVERSATION  → one grade for the whole thread (multi-turn transcript)
- level AGENT_RUN     → one grade per trace/turn (user request vs final answer + tool results)
- level SPAN/TOOL/GENERATION → one grade per step (the span's own input/output in context)

Output types → persisted score shape:
  score (default) → NUMERIC value 0..1, PASS/FAIL via `threshold`
  number          → NUMERIC value (any range), PASS/FAIL only when `threshold` is set
  boolean         → BOOLEAN 1/0, PASS/FAIL
  text            → TEXT string_value (+ optional reason), no verdict
  json            → the user's `config.output_schema` compiled to a pydantic contract (enums
                    become Literal constraints). Exactly the user's fields — nothing appended. A
                    numeric `score` field (if present) drives the 0..1 `value` + PASS/FAIL via
                    `threshold`; a `reason`/`reasoning`/`summary` field becomes the comment. With
                    neither, the column is informational (no value, no verdict).
  category        → LEGACY alias (superseded by json + enum schemas); kept for old rows

Execution mode (`config.execution_mode`, default "batch"): "sequential" chains items of the
SAME metric — each step's prompt carries the previous step's result, and in thread runs each
turn carries the previous turn's (`config.__previous_result__`, injected by the service).
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Literal

import structlog
from pydantic import BaseModel, Field, create_model

from tracely.domain.evaluation.evaluators.base import (
    CHAIN,
    CONVERSATION,
    GENERATION,
    SPAN,
    STEP_LEVELS,
    TOOL,
    Evaluator,
    default_registry,
)
from tracely.domain.evaluation.evaluators.catalog import DEFAULT_JUDGE_PROMPT
from tracely.domain.evaluation.output_schema import model_from_json_schema
from tracely.domain.evaluation.results import EvalResult, RunContext
from tracely.domain.evaluation.template_resolver import (
    build_context,
    extract_template_variables,
    template_resolver,
)
from tracely.domain.evaluation.text import answer_for, content_text, first_io
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.llm import provider

log = structlog.get_logger()

OUTPUT_TYPES = ("score", "number", "boolean", "category", "text", "json")

_TRUNC_IO = 1500  # per-step input/output excerpt
_TRUNC_TURN = 800  # per-turn excerpt in the conversation transcript
_DEFAULT_MAX_SPANS = 30  # cost guard for per-step judges


# ── structured response schemas (create_agent response_format) ───────────────


class ScoreVerdict(BaseModel):
    """Quality grade with a normalized score."""

    score: float = Field(description="0..1 quality score: 0 = total failure, 0.5 = mediocre, 1 = flawless")
    reason: str = Field(default="", description="one or two sentences citing the decisive evidence")


class NumberVerdict(BaseModel):
    """Numeric measurement (any range)."""

    value: float = Field(description="the numeric evaluation result")
    reason: str = Field(default="", description="one or two sentences justifying the number")


class PassFailVerdict(BaseModel):
    """Binary check outcome."""

    passed: bool = Field(description="true when the graded content passes this check")
    reason: str = Field(default="", description="the strongest signal behind the decision")


class TextVerdict(BaseModel):
    """Free-text observation."""

    text: str = Field(description="the observation — a short, specific paragraph")
    reason: str = Field(default="", description="one sentence on why this observation matters")


def _category_model(categories: list[str]) -> type[BaseModel]:
    """A CategoryVerdict whose `category` field is constrained to the configured labels."""
    cat_type: Any = Literal[tuple(categories)] if categories else str
    return create_model(
        "CategoryVerdict",
        category=(cat_type, Field(description="exactly one category")),
        reason=(str, Field(default="", description="why this category fits")),
    )


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse_json_object(text: str) -> dict:
    """Best-effort strict-JSON parse of a model reply (tolerates ```json fences)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    parsed = json.loads(t)
    if not isinstance(parsed, dict):
        raise ValueError(f"judge returned non-object JSON: {type(parsed).__name__}")
    return parsed


def _result_payload(r: EvalResult) -> dict:
    """The chained-context view of a result (sequential mode): the schema-shaped object for
    json outputs (with the score/verdict/reason envelope re-attached), else a compact
    {value, verdict, reason}."""
    if r.string_value:
        try:
            parsed = json.loads(r.string_value)
            if isinstance(parsed, dict):
                out = dict(parsed)
                if r.value is not None:
                    out.setdefault("score", r.value)
                if r.verdict:
                    out.setdefault("verdict", r.verdict)
                if r.comment:
                    out.setdefault("reason", r.comment)
                return out
        except ValueError:
            pass
    payload = {"value": r.value, "verdict": r.verdict or None, "reason": r.comment or None}
    return {k: v for k, v in payload.items() if v is not None}


def _deps_all(config: dict) -> dict:
    """All dependency results, flattened to `{score_name: payload | [payloads]}` — for
    trace/conversation grades (one item, so every dependency result applies)."""
    raw = config.get("__dependencies__") or {}
    out: dict = {}
    for name, records in raw.items():
        if not isinstance(records, list) or not records:
            continue
        payloads = [rec.get("payload") for rec in records]
        out[name] = payloads[0] if len(payloads) == 1 else payloads
    return out


def _deps_for_span(config: dict, span_id: str) -> dict:
    """The dependency results that apply to ONE step: each dependency's result for this exact
    `span_id`, falling back to a trace/conversation-level result (recorded under span_id "")
    that applies to every step. So a step-level composite lines up step N's prerequisite
    verdicts, while a dependency on a per-turn metric is shared across the run's steps."""
    raw = config.get("__dependencies__") or {}
    out: dict = {}
    for name, records in raw.items():
        if not isinstance(records, list):
            continue
        match = [rec for rec in records if rec.get("span_id") == span_id]
        if not match:  # trace/conversation-level dependency → applies to every step
            match = [rec for rec in records if not rec.get("span_id")]
        if match:
            out[name] = match[0].get("payload") if len(match) == 1 else [m.get("payload") for m in match]
    return out


def _is_sequential(config: dict) -> bool:
    return str(config.get("execution_mode") or "batch") == "sequential"


def _previous_from_config(config: dict) -> dict | None:
    """The cross-item seed for sequential mode (set by EvaluationService for thread runs)."""
    if not _is_sequential(config):
        return None
    prev = config.get("__previous_result__")
    return prev if isinstance(prev, dict) else None


@default_registry.register
class LLMJudgeEvaluator(Evaluator):
    """Runs the configured rubric through `create_agent` with a structured response schema.
    Skipped entirely when no LLM credential is configured so the rest of the pipeline runs
    unchanged."""

    kind: ClassVar[str] = "llm_judge"

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        if not provider.llm_enabled():
            return []
        # Note: for the judge, `params` is actually the full evaluator config (the runner
        # passes config|params transparently — both .get("prompt"/"threshold") and
        # .get("params").get("prompt"/"threshold") work). Resolve both shapes.
        config = params.get("params") or params
        if config.get("is_advanced"):
            return self._run_advanced(ctx, config)
        if self.level == CONVERSATION:
            return self._run_conversation(ctx, config)
        if self.level in STEP_LEVELS:
            return self._run_steps(ctx, config)
        return self._run_trace(ctx, config)

    # ── per-level context builders ───────────────────────────────────────────

    def _run_trace(self, ctx: RunContext, config: dict) -> list[EvalResult]:
        """One grade for the trace: user request vs final answer, grounded in tool results."""
        user_in = content_text(ctx.root.get("input")) or first_io(ctx.spans, "input")
        answer = answer_for(ctx.root, ctx.spans, TOOL, GENERATION, CHAIN)
        if not answer:
            return []
        grounding = ""
        tool_outputs = [
            f"- {s.get('name')}: {_clip(content_text(s.get('output')), 600)}"
            for s in ctx.spans
            if s.get("type") == TOOL and s.get("output")
        ]
        if tool_outputs:
            grounding = "\n\nTool results the answer must be consistent with:\n" + "\n".join(tool_outputs)
        body = (
            f"User request:\n{_clip(user_in, 2000)}\n\n"
            f"Agent answer:\n{_clip(answer, 2000)}{grounding}"
        )
        result = self._grade(config, body, previous=_previous_from_config(config))
        return [result] if result else []

    def _step_candidates(self, ctx: RunContext, config: dict) -> list[dict]:
        """The spans a step-level judge grades: the level's span type(s) (SPAN ⇒ `config.span_types`,
        default TOOL+GENERATION; TOOL/GENERATION/CHAIN ⇒ exactly that type), with I/O, capped at
        `max_spans`. Shared by the basic and advanced step paths."""
        if self.level == SPAN:
            wanted = {str(t).upper() for t in (config.get("span_types") or [TOOL, GENERATION])}
        else:
            wanted = {self.level}
        candidates = [
            s for s in ctx.spans
            if s.get("type") in wanted and (s.get("input") or s.get("output"))
        ]
        max_spans = int(config.get("max_spans") or _DEFAULT_MAX_SPANS)
        if len(candidates) > max_spans:
            log.info(
                "llm_judge_step_cap", trace_id=ctx.trace_id, candidates=len(candidates), cap=max_spans
            )
            candidates = candidates[:max_spans]
        return candidates

    def _run_steps(self, ctx: RunContext, config: dict) -> list[EvalResult]:
        """One grade per step. Level SPAN grades `config.span_types` (default TOOL+GENERATION);
        a TOOL/GENERATION/CHAIN-level judge grades exactly that span type."""
        candidates = self._step_candidates(ctx, config)
        user_in = content_text(ctx.root.get("input")) or first_io(ctx.spans, "input")
        sequential = _is_sequential(config)
        previous = _previous_from_config(config)
        out: list[EvalResult] = []
        for i, s in enumerate(candidates):
            body = (
                f"User request (the goal of the whole run):\n{_clip(user_in, 1200)}\n\n"
                f"Step {i + 1} of {len(candidates)} — {s.get('type')} `{s.get('name') or s.get('step_id') or ''}`\n"
                f"Step input:\n{_clip(content_text(s.get('input')), _TRUNC_IO)}\n\n"
                f"Step output:\n{_clip(content_text(s.get('output')), _TRUNC_IO)}"
            )
            result = self._grade(
                config, body, previous=previous, deps=_deps_for_span(config, s.get("span_id", ""))
            )
            if result:
                result.target_span_id = s.get("span_id", "")
                out.append(result)
                if sequential:
                    previous = _result_payload(result)
        return out

    def _run_conversation(self, ctx: RunContext, config: dict) -> list[EvalResult]:
        """One grade for the whole thread: a turn-by-turn transcript (ctx.spans spans every
        trace in the thread; each span carries its trace_id)."""
        by_trace: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for s in ctx.spans:
            tid = s.get("trace_id") or ctx.trace_id
            if tid not in by_trace:
                by_trace[tid] = []
                order.append(tid)
            by_trace[tid].append(s)
        lines: list[str] = []
        for n, tid in enumerate(order, start=1):
            spans = by_trace[tid]
            root = root_span(spans)
            user_in = content_text(root.get("input")) or first_io(spans, "input")
            answer = answer_for(root, spans, TOOL, GENERATION, CHAIN)
            if user_in:
                lines.append(f"Turn {n} — user: {_clip(user_in, _TRUNC_TURN)}")
            if answer:
                lines.append(f"Turn {n} — agent: {_clip(answer, _TRUNC_TURN)}")
        if not lines:
            return []
        transcript = _clip("\n".join(lines), 8000)
        body = f"Full conversation ({len(order)} turn{'s' if len(order) != 1 else ''}):\n{transcript}"
        result = self._grade(config, body)
        return [result] if result else []

    # ── advanced (template) grading ──────────────────────────────────────────

    def _history_override(self, ctx: RunContext, wanted: list[str]) -> str | None:
        """The rolling summary for this thread, when one exists — it backs `@ROLLING_SUMMARY` and
        is a compact, prefix-stable substitute for the raw transcript at `@HISTORY`/`@MESSAGES`.
        None (the default) leaves the raw transcript in place, so behavior is unchanged when no
        summary has been generated."""
        names = {w.split(".", 1)[0] for w in (wanted or [])}
        if not ({"HISTORY", "MESSAGES", "ROLLING_SUMMARY"} & names):
            return None
        try:
            from tracely.services.rolling_summary_service import RollingSummaryService

            return RollingSummaryService.history_override(
                ctx.project_id, ctx.thread_id or ctx.trace_id
            )
        except Exception:  # a cache miss/error must never block a grade
            return None

    def _declared_agents(self, ctx: RunContext, wanted: list[str]) -> list[dict] | None:
        """The user-declared agent catalog for `@LIST_AGENT`, when one was sent for this thread —
        a richer (description + tool params) substitute for the spans-derived agent list."""
        names = {w.split(".", 1)[0] for w in (wanted or [])}
        if "LIST_AGENT" not in names:
            return None
        try:
            from tracely.services.conversation_agents_service import ConversationAgentsService

            return ConversationAgentsService.for_thread(
                ctx.project_id, ctx.thread_id or ctx.trace_id
            )
        except Exception:
            return None

    def _run_advanced(self, ctx: RunContext, config: dict) -> list[EvalResult]:
        """Advanced judge: resolve the user's `@VARIABLE` template against the trace/thread, then
        grade. Mirrors the basic per-level dispatch — but the user controls the context. Uses
        `ctx.thread_spans` (the whole thread, set by the service when conversation-scoped vars are
        referenced) for @HISTORY/@PREVIOUS_*, falling back to the current trace's `spans`."""
        template = config.get("prompt") or ""
        wanted = config.get("template_variables") or extract_template_variables(template)
        thread_spans = ctx.thread_spans or ctx.spans
        history_override = self._history_override(ctx, wanted)
        declared_agents = self._declared_agents(ctx, wanted)
        if self.level in STEP_LEVELS:
            return self._run_advanced_steps(
                ctx, config, template, wanted, thread_spans, history_override, declared_agents
            )
        context = build_context(
            self.level,
            thread_spans=thread_spans,
            current_trace_id=ctx.trace_id,
            metric_previous_result=_previous_from_config(config),
            wanted_vars=wanted,
            history_override=history_override,
            declared_agents=declared_agents,
        )
        result = self._grade_resolved(config, template, context)
        return [result] if result else []

    def _run_advanced_steps(
        self,
        ctx: RunContext,
        config: dict,
        template: str,
        wanted: list[str],
        thread_spans: list[dict],
        history_override: str | None = None,
        declared_agents: list[dict] | None = None,
    ) -> list[EvalResult]:
        """One advanced grade per qualifying step (reusing the basic candidate selection + cap),
        threading the previous result into `@METRIC_PREVIOUS_RESULT` in sequential mode."""
        sequential = _is_sequential(config)
        previous = _previous_from_config(config)
        out: list[EvalResult] = []
        for s in self._step_candidates(ctx, config):
            context = build_context(
                self.level,
                thread_spans=thread_spans,
                current_trace_id=ctx.trace_id,
                current_span_id=s.get("span_id"),
                metric_previous_result=previous,
                wanted_vars=wanted,
                history_override=history_override,
                declared_agents=declared_agents,
            )
            result = self._grade_resolved(config, template, context)
            if result:
                result.target_span_id = s.get("span_id", "")
                out.append(result)
                if sequential:
                    previous = _result_payload(result)
        return out

    def _grade_resolved(self, config: dict, template: str, context) -> EvalResult | None:
        resolved = template_resolver.resolve(template, context)
        return self._grade_advanced(config, resolved.resolved_text)

    # ── grading + output-type handling ───────────────────────────────────────

    def _grade(
        self, config: dict, body: str, previous: dict | None = None, deps: dict | None = None
    ) -> EvalResult | None:
        """Basic grade: assemble the prompt (rubric system prompt + auto previous/deps context),
        then hand off to the shared model-call tail."""
        rubric = config.get("prompt") or DEFAULT_JUDGE_PROMPT
        if previous:
            body += (
                "\n\nPrevious result of this metric (the preceding item in the sequence — use "
                "it for continuity and comparison):\n"
                + _clip(json.dumps(previous, ensure_ascii=False), 1500)
            )
        if deps is None:  # trace/conversation grades use every dependency result
            deps = _deps_all(config)
        if deps:
            dep_lines = "\n".join(
                f"- {name}: {_clip(json.dumps(v, ensure_ascii=False), 600)}"
                for name, v in deps.items()
            )
            body += (
                "\n\nResults from prerequisite evaluations (use these as additional context):\n"
                + dep_lines
            )
        return self._call_and_build(config, system_prompt=rubric, body=body)

    def _grade_advanced(self, config: dict, resolved_text: str) -> EvalResult | None:
        """Advanced grade: the resolved `@VARIABLE` template IS the prompt — used as both the
        system prompt and the human message (the user's placeholders already carry every piece of
        context they chose). No auto previous/deps append — `@METRIC_PREVIOUS_RESULT` handles
        sequential chaining inside the template."""
        return self._call_and_build(config, system_prompt=resolved_text, body=resolved_text)

    def _call_and_build(
        self, config: dict, *, system_prompt: str, body: str
    ) -> EvalResult | None:
        """The model call + output-type→result tail shared by basic and advanced grading —
        everything after the prompt is assembled. Picks the response schema from `output_type`,
        invokes the agent at temp 0, and stamps token usage onto the result."""
        output_type = str(config.get("output_type") or "score").lower()
        if output_type not in OUTPUT_TYPES:
            output_type = "score"
        model = config.get("model") or None
        usage: dict = {}
        try:
            if output_type == "json":
                schema_model = model_from_json_schema(config.get("output_schema"))
                if schema_model is not None:
                    verdict = provider.run_structured_agent(
                        body,
                        response_format=schema_model,
                        system_prompt=system_prompt,
                        model=model,
                        on_usage=usage.update,
                    )
                    return self._attach_usage(self._json_result(config, verdict.model_dump()), usage)
                # no usable schema: free-form strict JSON (the rubric defines the shape)
                text = provider.run_text_agent(
                    body + "\n\nRespond with ONE strict JSON object shaped exactly as your "
                    "instructions describe.",
                    system_prompt=system_prompt,
                    model=model,
                    on_usage=usage.update,
                )
                return self._attach_usage(self._json_result(config, _parse_json_object(text)), usage)
            verdict = provider.run_structured_agent(
                body,
                response_format=self._response_format(output_type, config),
                system_prompt=system_prompt,
                model=model,
                on_usage=usage.update,
            )
        except Exception as exc:
            log.warning("llm_judge_failed", error=str(exc))
            return None
        return self._attach_usage(self._to_result(config, output_type, verdict), usage)

    @staticmethod
    def _attach_usage(result: EvalResult | None, usage: dict) -> EvalResult | None:
        """Stamp this grade's LLM token usage onto the result (for per-evaluator cost)."""
        if result is not None and usage:
            result.usage = dict(usage)
        return result

    @staticmethod
    def _response_format(output_type: str, config: dict) -> type[BaseModel]:
        if output_type == "number":
            return NumberVerdict
        if output_type == "boolean":
            return PassFailVerdict
        if output_type == "category":  # legacy alias — new columns use json + enum schemas
            return _category_model([str(c) for c in (config.get("categories") or [])])
        if output_type == "text":
            return TextVerdict
        return ScoreVerdict

    def _to_result(self, config: dict, output_type: str, verdict: Any) -> EvalResult:
        reason = str(getattr(verdict, "reason", ""))[:500]
        if output_type == "number":
            value = float(verdict.value)
            v = ""
            if config.get("threshold") is not None:
                v = "PASS" if value >= float(config["threshold"]) else "FAIL"
            return EvalResult(
                "", self.level, v, data_type="NUMERIC", value=value, comment=reason,
            )
        if output_type == "boolean":
            ok = bool(verdict.passed)
            return EvalResult(
                "", self.level, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0, comment=reason,
            )
        if output_type == "category":
            cat = str(verdict.category)[:120]
            fails = {str(c) for c in (config.get("fail_categories") or [])}
            v = "" if not fails else ("FAIL" if cat in fails else "PASS")
            return EvalResult(
                "", self.level, v, data_type="CATEGORICAL", string_value=cat, comment=reason,
            )
        if output_type == "text":
            return EvalResult(
                "", self.level, "", data_type="TEXT", string_value=str(verdict.text)[:2000],
                comment=reason,
            )
        # default: score
        score_val = min(max(float(verdict.score), 0.0), 1.0)
        threshold = float(config.get("threshold", 0.6))
        ok = score_val >= threshold
        return EvalResult(
            "", self.level, "PASS" if ok else "FAIL", data_type="NUMERIC", value=score_val, comment=reason,
        )

    def _json_result(self, config: dict, parsed: dict) -> EvalResult:
        """Persist a custom-schema result — exactly the user's fields, nothing appended. If the
        schema carries a numeric `score`/`overall_score`, it drives the normalized 0..1 `value`
        (PASS/FAIL via `threshold`); a `reason`/`reasoning`/`summary` string becomes the comment.
        With neither, the column is informational (no value, no verdict). All fields stay in
        string_value so the user sees exactly what they defined."""
        parsed = dict(parsed)
        candidate = parsed.get("score", parsed.get("overall_score"))
        raw_score = candidate if isinstance(candidate, (int, float)) and not isinstance(candidate, bool) else None
        reason = parsed.get("reason") or parsed.get("reasoning") or parsed.get("summary")
        value = min(max(float(raw_score), 0.0), 1.0) if raw_score is not None else None
        verdict = ""
        if value is not None and config.get("threshold") is not None:
            verdict = "PASS" if value >= float(config["threshold"]) else "FAIL"
        return EvalResult(
            "", self.level, verdict, data_type="TEXT", value=value,
            string_value=json.dumps(parsed, ensure_ascii=False)[:4000],
            comment=str(reason or "")[:500],
        )
