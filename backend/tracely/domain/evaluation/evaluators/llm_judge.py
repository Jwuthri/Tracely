"""LLM-as-judge evaluator: grades the agent's answer for faithfulness to its tool results.

A single class handles every LLM-judge config; the rubric prompt + score threshold come from
the evaluator's `config` (so a project can have multiple judges with different rubrics)."""

from __future__ import annotations

import structlog
from typing import ClassVar

from tracely.config import settings
from tracely.domain.evaluation.evaluators.base import (
    CHAIN,
    GENERATION,
    RUN,
    TOOL,
    Evaluator,
    default_registry,
)
from tracely.domain.evaluation.evaluators.catalog import DEFAULT_JUDGE_PROMPT
from tracely.domain.evaluation.results import EvalResult, RunContext
from tracely.domain.evaluation.text import answer_for, content_text, first_io
from tracely.infrastructure.llm import judge as judge_http

log = structlog.get_logger()


@default_registry.register
class LLMJudgeEvaluator(Evaluator):
    """Calls the configured chat-completions endpoint with a strict-JSON rubric. Skipped
    entirely when no `llm_judge_api_key` is set so the rest of the pipeline runs unchanged."""

    kind: ClassVar[str] = "llm_judge"

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        if not settings.llm_judge_api_key:
            return []
        # Note: for the judge, `params` is actually the full evaluator config (the runner
        # passes config|params transparently — both .get("prompt"/"threshold") and
        # .get("params").get("prompt"/"threshold") work). Resolve both shapes.
        config = params.get("params") or params
        user_in = content_text(ctx.root.get("input")) or first_io(ctx.spans, "input")
        answer = answer_for(ctx.root, ctx.spans, TOOL, GENERATION, CHAIN)
        if not answer:
            return []
        tool_outputs = [
            f"{s.get('name')}: {s.get('output')}"
            for s in ctx.spans
            if s.get("type") == TOOL and s.get("output")
        ]
        rubric = config.get("prompt") or DEFAULT_JUDGE_PROMPT
        threshold = float(config.get("threshold", 0.6))
        try:
            score, reason = judge_http.judge(rubric, user_in or "", answer, tool_outputs)
        except Exception as exc:
            log.warning("llm_judge_failed", error=str(exc))
            return []
        ok = score >= threshold
        return [EvalResult(
            "", RUN, "PASS" if ok else "FAIL", data_type="NUMERIC", value=score, comment=reason,
        )]
