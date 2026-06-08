"""Structural evaluators: deterministic checks over the trace's spans (no LLM)."""

from __future__ import annotations

import json
from typing import ClassVar

from tracely.config import settings
from tracely.domain.evaluation.evaluators.base import (
    GENERATION,
    RUN,
    TOOL,
    Evaluator,
    default_registry,
)
from tracely.domain.evaluation.results import EvalResult, RunContext


@default_registry.register
class RunOutcomeEvaluator(Evaluator):
    """FAIL if any span in the run errored."""

    kind: ClassVar[str] = "structural"
    check: ClassVar[str] = "run_outcome"

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        errs = [s for s in ctx.spans if s.get("level") == "ERROR"]
        ok = not errs
        return [EvalResult(
            "", RUN, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
            comment="" if ok else "errors: " + ", ".join(s.get("name", "") for s in errs),
        )]


@default_registry.register
class ToolSuccessEvaluator(Evaluator):
    """FAIL per TOOL span that errored. Emits one result per tool call."""

    kind: ClassVar[str] = "structural"
    check: ClassVar[str] = "tool_success"
    default_level: ClassVar[str] = TOOL

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        out: list[EvalResult] = []
        for s in ctx.spans:
            if s.get("type") == TOOL:
                ok = s.get("level") != "ERROR"
                out.append(EvalResult(
                    "", TOOL, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
                    target_span_id=s.get("span_id", ""),
                    comment="" if ok else (s.get("status_message", "") or "tool error"),
                ))
        return out


@default_registry.register
class ToolConsistencyEvaluator(Evaluator):
    """FAIL if the model requested a tool that never executed (the 'silent failure' case).

    Tools may be dispatched in user code without a TOOL span (e.g. a plain run_tool() loop with
    no tracely.tool() context manager). When that happens the model's next turn carries the
    tool result as a `{role:'tool', tool_call_id, content}` message in its input, and the
    previous assistant message has `tool_calls[].id` ↔ `tool_calls[].function.name`. We walk
    GENERATION inputs/outputs and resolve names via that map so we don't FAIL when the loop ran
    fine but just wasn't span-wrapped.
    """

    kind: ClassVar[str] = "structural"
    check: ClassVar[str] = "tool_consistency"

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        requested: set[str] = set()
        for s in ctx.spans:
            for t in s.get("tool_call_names") or []:
                if t:
                    requested.add(t)
        if not requested:
            return []
        executed = {s.get("name") for s in ctx.spans if s.get("type") == TOOL}
        executed |= self._executed_via_generation_messages(ctx.spans)
        missing = sorted(requested - executed)
        ok = not missing
        return [EvalResult(
            "", RUN, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
            comment="" if ok else "requested but not executed: " + ", ".join(missing),
        )]

    @staticmethod
    def _executed_via_generation_messages(spans: list[dict]) -> set[str]:
        """Resolve tools that ran without a TOOL span by walking the `{role:'tool'}` messages
        in GENERATION span inputs/outputs and matching `tool_call_id` ↔ the previous assistant
        message's `tool_calls[].id`/`function.name`."""
        executed: set[str] = set()
        call_id_to_name: dict[str, str] = {}
        tool_msg_ids: set[str] = set()
        for s in spans:
            if s.get("type") != GENERATION:
                continue
            for field_key in ("input", "output"):
                try:
                    parsed = json.loads(s.get(field_key) or "")
                except (ValueError, TypeError):
                    continue
                if not isinstance(parsed, list):
                    continue
                for m in parsed:
                    if not isinstance(m, dict):
                        continue
                    role = str(m.get("role") or "").lower()
                    if role == "tool":
                        cid = m.get("tool_call_id") or m.get("id")
                        if cid:
                            tool_msg_ids.add(str(cid))
                        if m.get("name"):
                            executed.add(str(m["name"]))
                    elif role == "assistant":
                        for tc in m.get("tool_calls") or []:
                            if not isinstance(tc, dict):
                                continue
                            cid = tc.get("id")
                            fn = tc.get("function") or {}
                            name = fn.get("name") if isinstance(fn, dict) else tc.get("name")
                            if cid and name:
                                call_id_to_name[str(cid)] = str(name)
        for cid in tool_msg_ids:
            if cid in call_id_to_name:
                executed.add(call_id_to_name[cid])
        return executed


@default_registry.register
class LatencyEvaluator(Evaluator):
    """FAIL if the run exceeds the latency budget (ms). Budget comes from `params.budget_ms`,
    falling back to `settings.eval_latency_budget_ms`."""

    kind: ClassVar[str] = "structural"
    check: ClassVar[str] = "latency"

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        budget = int(params.get("budget_ms") or settings.eval_latency_budget_ms)
        starts, ends = [], []
        for s in ctx.spans:
            if s.get("start_time"):
                starts.append(s["start_time"])
            ends.append(s.get("end_time") or s.get("start_time"))
        if not starts:
            return []
        ms = (max(ends) - min(starts)).total_seconds() * 1000.0
        ok = ms <= budget
        return [EvalResult(
            "", RUN, "PASS" if ok else "FAIL", data_type="NUMERIC", value=round(ms, 2),
            comment="" if ok else f"over budget ({budget}ms)",
        )]


@default_registry.register
class RequiredToolsEvaluator(Evaluator):
    """FAIL if any tool in `params.tools` was not called. Off by default — projects opt in by
    listing tools in the evaluator config."""

    kind: ClassVar[str] = "structural"
    check: ClassVar[str] = "required_tools"

    def run(self, ctx: RunContext, params: dict) -> list[EvalResult]:
        required = params.get("tools") or []
        if not required:
            return []
        executed = [s.get("name") for s in ctx.spans if s.get("type") == TOOL]
        missing = [t for t in required if t not in executed]
        ok = not missing
        return [EvalResult(
            "", RUN, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
            comment="" if ok else "missing required tools: " + ", ".join(missing),
        )]
