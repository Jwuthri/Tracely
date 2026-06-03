"""Online evaluators — run automatically on every ingested trace and emit pass/fail
Scores. Multi-level (agent_run / turn / step / tool). Structural evaluators need no
LLM; the optional LLM-judge activates only when an API key is configured.

This is what turns Tracely from "wait for an ERROR span" into "automatically detect
failures" — including SILENT ones (e.g. a tool the model requested but never executed).
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from tracely.config import settings

log = structlog.get_logger()

RUN = "AGENT_RUN"
TURN = "TURN"
TOOL = "TOOL"


@dataclass
class EvalResult:
    name: str
    level: str
    verdict: str  # PASS | FAIL
    data_type: str = "BOOLEAN"  # BOOLEAN | NUMERIC | CATEGORICAL
    value: float | None = None
    target_span_id: str = ""  # the span this result is about (tool/step level)
    comment: str = ""


@dataclass
class RunContext:
    project_id: str
    trace_id: str
    agent_run_id: str
    spans: list[dict[str, Any]]
    root: dict[str, Any] = field(default_factory=dict)


class Evaluator(Protocol):
    key: str

    def evaluate(self, ctx: RunContext) -> list[EvalResult]: ...


# ── structural evaluators (no LLM needed) ────────────────────────────────────


class RunOutcomeEvaluator:
    key = "run_outcome"

    def evaluate(self, ctx: RunContext) -> list[EvalResult]:
        errs = [s for s in ctx.spans if s.get("level") == "ERROR"]
        ok = not errs
        comment = "" if ok else "errors: " + ", ".join(s.get("name", "") for s in errs)
        return [EvalResult("tracely.run.outcome", RUN, "PASS" if ok else "FAIL",
                           value=1.0 if ok else 0.0, comment=comment)]


class ToolSuccessEvaluator:
    key = "tool_success"

    def evaluate(self, ctx: RunContext) -> list[EvalResult]:
        out: list[EvalResult] = []
        for s in ctx.spans:
            if s.get("type") == "TOOL":
                ok = s.get("level") != "ERROR"
                out.append(EvalResult(
                    "tracely.tool.success", TOOL, "PASS" if ok else "FAIL",
                    value=1.0 if ok else 0.0, target_span_id=s.get("span_id", ""),
                    comment="" if ok else (s.get("status_message", "") or "tool error"),
                ))
        return out


class ToolConsistencyEvaluator:
    """Every tool the model REQUESTED (tool_call_names on a generation) must have an
    executed TOOL span. Catches silent failures: requested-but-never-run."""

    key = "tool_consistency"

    def evaluate(self, ctx: RunContext) -> list[EvalResult]:
        requested: set[str] = set()
        for s in ctx.spans:
            for t in s.get("tool_call_names") or []:
                if t:
                    requested.add(t)
        if not requested:
            return []
        executed = {s.get("name") for s in ctx.spans if s.get("type") == "TOOL"}
        missing = sorted(requested - executed)
        ok = not missing
        return [EvalResult(
            "tracely.run.tool_consistency", RUN, "PASS" if ok else "FAIL",
            value=1.0 if ok else 0.0,
            comment="" if ok else "requested but not executed: " + ", ".join(missing),
        )]


class LatencyEvaluator:
    key = "latency"

    def evaluate(self, ctx: RunContext) -> list[EvalResult]:
        starts, ends = [], []
        for s in ctx.spans:
            if s.get("start_time"):
                starts.append(s["start_time"])
            ends.append(s.get("end_time") or s.get("start_time"))
        if not starts:
            return []
        ms = (max(ends) - min(starts)).total_seconds() * 1000.0
        ok = ms <= settings.eval_latency_budget_ms
        return [EvalResult("tracely.run.latency_ms", RUN, "PASS" if ok else "FAIL",
                           data_type="NUMERIC", value=round(ms, 2),
                           comment="" if ok else f"over budget ({settings.eval_latency_budget_ms}ms)")]


# ── optional LLM-as-judge (activates only if an API key is configured) ────────


class LlmJudgeEvaluator:
    key = "llm_judge"

    def evaluate(self, ctx: RunContext) -> list[EvalResult]:
        if not settings.llm_judge_api_key:
            return []  # skipped — no key
        user_in = ctx.root.get("input") or _first_io(ctx.spans, "input")
        answer = ctx.root.get("output") or _first_io(ctx.spans, "output")
        if not answer:
            return []
        try:
            score, reason = _judge(user_in or "", answer)
        except Exception as exc:  # never break ingestion on judge failure
            log.warning("llm_judge_failed", error=str(exc))
            return []
        ok = score >= 0.6
        return [EvalResult("tracely.run.quality", RUN, "PASS" if ok else "FAIL",
                           data_type="NUMERIC", value=score, comment=reason)]


def _first_io(spans: list[dict], key: str) -> str:
    for s in reversed(spans):
        if s.get(key):
            return str(s[key])
    return ""


def _judge(user_in: str, answer: str) -> tuple[float, str]:
    prompt = (
        "You are grading an AI agent's answer for correctness and helpfulness. "
        "Respond with strict JSON {\"score\": 0..1, \"reason\": \"...\"}.\n\n"
        f"User request:\n{user_in[:2000]}\n\nAgent answer:\n{answer[:2000]}"
    )
    body = json.dumps({
        "model": settings.llm_judge_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{settings.llm_judge_base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {settings.llm_judge_api_key}", "content-type": "application/json"},
    )
    resp = json.load(urllib.request.urlopen(req, timeout=30))
    content = resp["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return float(parsed.get("score", 0.0)), str(parsed.get("reason", ""))[:500]


# Registry — order is informational; all run on every trace.
EVALUATORS: list[Evaluator] = [
    RunOutcomeEvaluator(),
    ToolSuccessEvaluator(),
    ToolConsistencyEvaluator(),
    LatencyEvaluator(),
    LlmJudgeEvaluator(),
]
