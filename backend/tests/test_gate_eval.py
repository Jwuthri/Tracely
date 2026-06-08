"""CI-gate verdict logic — evaluate_case (PASS/FAIL engine) and delta_warnings (soft gate).

Both are pure functions: evaluate_case scores a produced trajectory against a case's assertions;
delta_warnings flags a run that's materially slower / more expensive than the baseline green gate.
No Postgres / ClickHouse — models are built in memory only for attribute access.
"""

from __future__ import annotations

from tracely.config import settings
from tracely.domain.gate.warnings import delta_warnings
from tracely.domain.regression.contract import evaluate_case
from tracely.domain.trajectory import build_trajectory
from tracely.infrastructure.db.models import EvaluationCase, GateRun


def _span(span_id: str, type_: str, name: str, *, parent: str = "", level: str = "DEFAULT") -> dict:
    return {
        "trace_id": "t", "span_id": span_id, "parent_span_id": parent, "type": type_,
        "name": name, "level": level, "agent_run_id": "r", "is_app_root": parent == "",
        "tool_call_names": [], "output": None,
    }


def _case(**assertions) -> EvaluationCase:
    a = {"no_error": True, "required_tools": ["get_weather"], "match_mode": "superset", **assertions}
    return EvaluationCase(assertions=a, match_mode="superset")


def _traj(*spans: dict):
    return build_trajectory([_span("a", "AGENT", "planner"), *spans])


# ── evaluate_case ────────────────────────────────────────────────────────────
def test_pass_when_required_tool_runs_cleanly():
    traj = _traj(_span("t", "TOOL", "get_weather", parent="a"))
    verdict, detail = evaluate_case(_case(), traj)
    assert verdict == "PASS"
    assert detail["tools_ok"] and detail["error_ok"]


def test_fail_when_required_tool_missing():
    verdict, detail = evaluate_case(_case(), _traj())  # no TOOL span
    assert verdict == "FAIL"
    assert detail["missing_tools"] == ["get_weather"]


def test_fail_when_tool_errors_and_errors_not_allowed():
    traj = _traj(_span("t", "TOOL", "get_weather", parent="a", level="ERROR"))
    verdict, _ = evaluate_case(_case(allow_tool_errors=False), traj)
    assert verdict == "FAIL"


def test_pass_when_tool_errors_but_run_is_clean_and_errors_allowed():
    # the tool (replayed environment) errors, but the agent handled it -> no run-level error
    traj = _traj(_span("t", "TOOL", "get_weather", parent="a", level="ERROR"))
    verdict, detail = evaluate_case(_case(allow_tool_errors=True), traj)
    assert verdict == "PASS"
    assert detail["tool_errors"] == ["get_weather"] and detail["run_errors"] == []


def test_no_error_assertion_off_ignores_errors():
    traj = _traj(_span("t", "TOOL", "get_weather", parent="a", level="ERROR"))
    verdict, _ = evaluate_case(_case(no_error=False), traj)
    assert verdict == "PASS"


# ── delta_warnings ──────────────────────────────────────────────────────────
def _baseline(latency_ms: float, tokens: int) -> GateRun:
    return GateRun(latency_ms=latency_ms, total_tokens=tokens, status="PASS")


def test_no_baseline_no_warnings():
    assert delta_warnings(9999.0, 99999, None) == []


def test_latency_regression_warns():
    base = _baseline(200.0, 1000)
    over = 200.0 * (1 + (settings.gate_latency_warn_pct + 20) / 100)
    warns = delta_warnings(over, 1000, base)
    assert any("latency" in w for w in warns)
    assert not any("tokens" in w for w in warns)


def test_token_regression_warns():
    base = _baseline(200.0, 1000)
    over = int(1000 * (1 + (settings.gate_tokens_warn_pct + 20) / 100))
    warns = delta_warnings(200.0, over, base)
    assert any("tokens" in w for w in warns)


def test_tiny_baseline_latency_is_floored():
    # baseline < 50ms (e.g. hermetic replay) -> latency noise never warns, even at +1000%
    base = _baseline(10.0, 0)
    assert delta_warnings(1000.0, 0, base) == []


def test_within_threshold_no_warning():
    base = _baseline(200.0, 1000)
    assert delta_warnings(200.0, 1000, base) == []  # identical -> 0% delta
