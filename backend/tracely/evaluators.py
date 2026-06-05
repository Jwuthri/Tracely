"""Online evaluator IMPLEMENTATIONS + the recommended template catalog.

Evaluators are user-configured data (see models.Evaluator). This module no longer auto-runs a
fixed list — it provides the check implementations a configured evaluator dispatches to via
`run_evaluator`, plus `TEMPLATES` (the recommended set, seeded as editable records).
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Any

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
    data_type: str = "BOOLEAN"
    value: float | None = None
    target_span_id: str = ""
    comment: str = ""


@dataclass
class RunContext:
    project_id: str
    trace_id: str
    agent_run_id: str
    spans: list[dict[str, Any]]
    root: dict[str, Any] = field(default_factory=dict)


# ── structural checks: (ctx, params) -> [EvalResult] (name filled in by run_evaluator) ────────


def check_run_outcome(ctx: RunContext, params: dict) -> list[EvalResult]:
    errs = [s for s in ctx.spans if s.get("level") == "ERROR"]
    ok = not errs
    return [EvalResult("", RUN, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
                       comment="" if ok else "errors: " + ", ".join(s.get("name", "") for s in errs))]


def check_tool_success(ctx: RunContext, params: dict) -> list[EvalResult]:
    out: list[EvalResult] = []
    for s in ctx.spans:
        if s.get("type") == TOOL:
            ok = s.get("level") != "ERROR"
            out.append(EvalResult("", TOOL, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
                                  target_span_id=s.get("span_id", ""),
                                  comment="" if ok else (s.get("status_message", "") or "tool error")))
    return out


def check_tool_consistency(ctx: RunContext, params: dict) -> list[EvalResult]:
    requested: set[str] = set()
    for s in ctx.spans:
        for t in s.get("tool_call_names") or []:
            if t:
                requested.add(t)
    if not requested:
        return []
    executed = {s.get("name") for s in ctx.spans if s.get("type") == TOOL}
    missing = sorted(requested - executed)
    ok = not missing
    return [EvalResult("", RUN, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
                       comment="" if ok else "requested but not executed: " + ", ".join(missing))]


def check_latency(ctx: RunContext, params: dict) -> list[EvalResult]:
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
    return [EvalResult("", RUN, "PASS" if ok else "FAIL", data_type="NUMERIC", value=round(ms, 2),
                       comment="" if ok else f"over budget ({budget}ms)")]


def check_required_tools(ctx: RunContext, params: dict) -> list[EvalResult]:
    required = params.get("tools") or []
    if not required:
        return []
    executed = [s.get("name") for s in ctx.spans if s.get("type") == TOOL]
    missing = [t for t in required if t not in executed]
    ok = not missing
    return [EvalResult("", RUN, "PASS" if ok else "FAIL", value=1.0 if ok else 0.0,
                       comment="" if ok else "missing required tools: " + ", ".join(missing))]


STRUCTURAL = {
    "run_outcome": check_run_outcome,
    "tool_success": check_tool_success,
    "tool_consistency": check_tool_consistency,
    "latency": check_latency,
    "required_tools": check_required_tools,
}


# ── LLM-as-judge ──────────────────────────────────────────────────────────────

DEFAULT_JUDGE_PROMPT = (
    "You are grading an AI agent's answer for correctness, faithfulness to its tool results, and "
    "helpfulness. Give a LOW score to answers that are unhelpful, self-contradictory, absurd, or "
    "that state facts not supported by (or contradicting) the tool results."
)


def _first_io(spans: list[dict], key: str) -> str:
    for s in reversed(spans):
        if s.get(key):
            return str(s[key])
    return ""


def _answer(ctx: RunContext) -> str:
    if ctx.root.get("output"):
        return str(ctx.root["output"])
    for s in reversed(ctx.spans):
        if s.get("output") and s.get("type") != TOOL:
            return str(s["output"])
    return _first_io(ctx.spans, "output")


def check_llm_judge(ctx: RunContext, config: dict) -> list[EvalResult]:
    if not settings.llm_judge_api_key:
        return []  # no key -> judge skipped
    user_in = ctx.root.get("input") or _first_io(ctx.spans, "input")
    answer = _answer(ctx)
    if not answer:
        return []
    tool_outputs = [f"{s.get('name')}: {s.get('output')}" for s in ctx.spans
                    if s.get("type") == TOOL and s.get("output")]
    rubric = config.get("prompt") or DEFAULT_JUDGE_PROMPT
    threshold = float(config.get("threshold", 0.6))
    try:
        score, reason = _judge(rubric, user_in or "", answer, tool_outputs)
    except Exception as exc:
        log.warning("llm_judge_failed", error=str(exc))
        return []
    ok = score >= threshold
    return [EvalResult("", RUN, "PASS" if ok else "FAIL", data_type="NUMERIC", value=score, comment=reason)]


def _judge(rubric: str, user_in: str, answer: str, tool_outputs: list[str]) -> tuple[float, str]:
    grounding = ""
    if tool_outputs:
        joined = "\n".join(f"- {t}" for t in tool_outputs)
        grounding = f"\n\nTool results the answer must be consistent with:\n{joined}"
    prompt = (
        rubric + " Respond with strict JSON {\"score\": 0..1, \"reason\": \"...\"}.\n\n"
        f"User request:\n{user_in[:2000]}\n\nAgent answer:\n{answer[:2000]}{grounding}"
    )
    body = json.dumps({
        "model": settings.llm_judge_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        f"{settings.llm_judge_base_url.rstrip('/')}/chat/completions", data=body,
        headers={"Authorization": f"Bearer {settings.llm_judge_api_key}", "content-type": "application/json"},
    )
    resp = json.load(urllib.request.urlopen(req, timeout=30))
    parsed = json.loads(resp["choices"][0]["message"]["content"])
    return float(parsed.get("score", 0.0)), str(parsed.get("reason", ""))[:500]


# ── dispatch ──────────────────────────────────────────────────────────────────


def run_evaluator(kind: str, config: dict, score_name: str, level: str, ctx: RunContext) -> list[EvalResult]:
    """Run one configured evaluator and stamp its results with the evaluator's score name/level."""
    config = config or {}
    if kind == "structural":
        fn = STRUCTURAL.get(config.get("check"))
        results = fn(ctx, config.get("params") or {}) if fn else []
    elif kind == "llm_judge":
        results = check_llm_judge(ctx, config)
    else:
        results = []
    for r in results:
        r.name = score_name
        if level and r.level == RUN:
            r.level = level
    return results


# ── recommended catalog (seeded as editable Evaluator records) ────────────────

TEMPLATES = [
    {"name": "Run outcome", "kind": "structural", "score_name": "tracely.run.outcome", "level": "AGENT_RUN",
     "description": "Fails if any step in the run errored.", "config": {"check": "run_outcome"}, "recommended": True},
    {"name": "Tool success", "kind": "structural", "score_name": "tracely.tool.success", "level": "TOOL",
     "description": "Fails if a tool call errored.", "config": {"check": "tool_success"}, "recommended": True},
    {"name": "Tool consistency", "kind": "structural", "score_name": "tracely.run.tool_consistency",
     "level": "AGENT_RUN", "recommended": True,
     "description": "Fails if the model requested a tool that never executed (a silent failure).",
     "config": {"check": "tool_consistency"}},
    {"name": "Latency", "kind": "structural", "score_name": "tracely.run.latency_ms", "level": "AGENT_RUN",
     "description": "Fails if the run exceeds the latency budget.", "recommended": True,
     "config": {"check": "latency", "params": {"budget_ms": 60000}}},
    {"name": "Answer quality · LLM judge", "kind": "llm_judge", "score_name": "tracely.run.quality",
     "level": "AGENT_RUN", "recommended": True,
     "description": "An LLM grades the answer for correctness and faithfulness to the tool results.",
     "config": {"prompt": DEFAULT_JUDGE_PROMPT, "threshold": 0.6}},
    {"name": "Required tools", "kind": "structural", "score_name": "tracely.run.required_tools",
     "level": "AGENT_RUN", "recommended": False,
     "description": "Fails if specific tools weren't called.",
     "config": {"check": "required_tools", "params": {"tools": []}}},
]
