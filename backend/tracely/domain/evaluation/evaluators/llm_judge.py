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
  boolean         → BOOLEAN 1/0, PASS/FAIL
  category        → CATEGORICAL string_value (PASS/FAIL only when `fail_categories` is set);
                    `config.categories` constrain the schema via a Literal field
  text            → TEXT string_value, no verdict
  json            → rubric-defined object stored as TEXT string_value (+ value/verdict when it
                    carries a numeric `score` and a `threshold` is configured)
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
from tracely.domain.evaluation.results import EvalResult, RunContext
from tracely.domain.evaluation.text import answer_for, content_text, first_io
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.llm import provider

log = structlog.get_logger()

OUTPUT_TYPES = ("score", "boolean", "category", "text", "json")

_TRUNC_IO = 1500  # per-step input/output excerpt
_TRUNC_TURN = 800  # per-turn excerpt in the conversation transcript
_DEFAULT_MAX_SPANS = 30  # cost guard for per-step judges


# ── structured response schemas (create_agent response_format) ───────────────


class ScoreVerdict(BaseModel):
    """Quality grade with a normalized score."""

    score: float = Field(description="0..1 quality score: 0 = total failure, 0.5 = mediocre, 1 = flawless")
    reason: str = Field(default="", description="one or two sentences citing the decisive evidence")


class PassFailVerdict(BaseModel):
    """Binary check outcome."""

    passed: bool = Field(description="true when the graded content passes this check")
    reason: str = Field(default="", description="the strongest signal behind the decision")


class TextVerdict(BaseModel):
    """Free-text observation."""

    text: str = Field(description="the observation — a short, specific paragraph")


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
        result = self._grade(config, body)
        return [result] if result else []

    def _run_steps(self, ctx: RunContext, config: dict) -> list[EvalResult]:
        """One grade per step. Level SPAN grades `config.span_types` (default TOOL+GENERATION);
        a TOOL/GENERATION/CHAIN-level judge grades exactly that span type."""
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
        user_in = content_text(ctx.root.get("input")) or first_io(ctx.spans, "input")
        out: list[EvalResult] = []
        for i, s in enumerate(candidates):
            body = (
                f"User request (the goal of the whole run):\n{_clip(user_in, 1200)}\n\n"
                f"Step {i + 1} of {len(candidates)} — {s.get('type')} `{s.get('name') or s.get('step_id') or ''}`\n"
                f"Step input:\n{_clip(content_text(s.get('input')), _TRUNC_IO)}\n\n"
                f"Step output:\n{_clip(content_text(s.get('output')), _TRUNC_IO)}"
            )
            result = self._grade(config, body)
            if result:
                result.target_span_id = s.get("span_id", "")
                out.append(result)
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

    # ── grading + output-type handling ───────────────────────────────────────

    def _grade(self, config: dict, body: str) -> EvalResult | None:
        rubric = config.get("prompt") or DEFAULT_JUDGE_PROMPT
        output_type = str(config.get("output_type") or "score").lower()
        if output_type not in OUTPUT_TYPES:
            output_type = "score"
        model = config.get("model") or None
        try:
            if output_type == "json":
                text = provider.run_text_agent(
                    body + "\n\nRespond with ONE strict JSON object shaped exactly as your "
                    'instructions describe. Always include a "reason" field.',
                    system_prompt=rubric,
                    model=model,
                )
                return self._json_result(config, _parse_json_object(text))
            verdict = provider.run_structured_agent(
                body,
                response_format=self._response_format(output_type, config),
                system_prompt=rubric,
                model=model,
            )
        except Exception as exc:
            log.warning("llm_judge_failed", error=str(exc))
            return None
        return self._to_result(config, output_type, verdict)

    @staticmethod
    def _response_format(output_type: str, config: dict) -> type[BaseModel]:
        if output_type == "boolean":
            return PassFailVerdict
        if output_type == "category":
            return _category_model([str(c) for c in (config.get("categories") or [])])
        if output_type == "text":
            return TextVerdict
        return ScoreVerdict

    def _to_result(self, config: dict, output_type: str, verdict: Any) -> EvalResult:
        reason = str(getattr(verdict, "reason", ""))[:500]
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
            )
        # default: score
        score_val = min(max(float(verdict.score), 0.0), 1.0)
        threshold = float(config.get("threshold", 0.6))
        ok = score_val >= threshold
        return EvalResult(
            "", self.level, "PASS" if ok else "FAIL", data_type="NUMERIC", value=score_val, comment=reason,
        )

    def _json_result(self, config: dict, parsed: dict) -> EvalResult:
        score = parsed.get("score")
        value = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
        verdict = ""
        if value is not None and config.get("threshold") is not None:
            verdict = "PASS" if value >= float(config["threshold"]) else "FAIL"
        return EvalResult(
            "", self.level, verdict, data_type="TEXT", value=value,
            string_value=json.dumps(parsed, ensure_ascii=False)[:4000],
            comment=str(parsed.get("reason", ""))[:500],
        )
