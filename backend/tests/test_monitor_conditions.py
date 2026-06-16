"""Monitor condition evaluation — pure tests, no infra.

Locks down the threshold semantics that decide whether a Slack page goes out:
- `fail_rate_over` / `trace_failure_rate`: strictly **over** threshold → fires (ties don't page).
- `score_below`: strictly **under** threshold → fires.
- `min_samples` guards against alerts on tiny denominators (1 of 1 ≠ 100% fail rate that wakes
  the team).
- Unknown condition types are a soft no-op (the worker keeps running, the monitor stays silent).
"""

from __future__ import annotations

from tracely.domain.monitoring.conditions import Sample, evaluate_condition


def _samples(verdicts: list[str], values: list[float | None] | None = None) -> list[Sample]:
    if values is None:
        values = [None] * len(verdicts)
    return [Sample(verdict=v, value=val) for v, val in zip(verdicts, values)]


# ── fail_rate_over ────────────────────────────────────────────────────────────
def _fro(window_min: int = 60, min_samples: int = 5, threshold: float = 0.20) -> dict:
    return {
        "type": "fail_rate_over",
        "score_name": "tracely.run.quality",
        "window_minutes": window_min,
        "min_samples": min_samples,
        "threshold": threshold,
    }


def test_fail_rate_fires_when_strictly_over_threshold():
    # 3 of 5 = 60%, threshold 20% → fires.
    v = evaluate_condition(_fro(), _samples(["PASS", "FAIL", "FAIL", "FAIL", "PASS"]))
    assert v.fires is True
    assert v.score == 0.6
    assert "60%" in v.summary and "FAIL rate" in v.summary


def test_fail_rate_does_not_fire_at_exact_threshold():
    # 1 of 5 = 20%, threshold 20% → does NOT fire (ties don't page).
    v = evaluate_condition(_fro(threshold=0.20), _samples(["PASS", "PASS", "PASS", "PASS", "FAIL"]))
    assert v.fires is False
    assert v.score == 0.2


def test_fail_rate_below_threshold_quiet():
    v = evaluate_condition(_fro(threshold=0.50), _samples(["PASS"] * 9 + ["FAIL"]))
    assert v.fires is False
    assert "≤50%" in v.summary


def test_fail_rate_min_samples_skips_tiny_windows():
    # 1 of 1 is "100%" but with min_samples=5 we don't fire.
    v = evaluate_condition(_fro(min_samples=5), _samples(["FAIL"]))
    assert v.fires is False
    assert v.skipped_reason == "min_samples_unmet"
    assert v.score is None
    assert v.sample_size == 1


def test_fail_rate_ignores_empty_verdicts():
    # Informational scores ("" verdict) count as samples but aren't FAIL.
    v = evaluate_condition(_fro(), _samples(["PASS", "PASS", "", "", "FAIL"]))
    assert v.fires is False  # 1 fail / 5 samples = 20% (not strictly > 20%)
    assert v.score == 0.2


# ── score_below ──────────────────────────────────────────────────────────────
def _sb(threshold: float = 0.6, min_samples: int = 5) -> dict:
    return {
        "type": "score_below",
        "score_name": "tracely.conv.goal_success",
        "window_minutes": 60,
        "min_samples": min_samples,
        "threshold": threshold,
    }


def test_score_below_fires_when_average_drops():
    # avg = (0.3+0.4+0.5+0.5+0.5)/5 = 0.44 < 0.6 → fires.
    v = evaluate_condition(_sb(), _samples(["FAIL"] * 5, [0.3, 0.4, 0.5, 0.5, 0.5]))
    assert v.fires is True
    assert v.score is not None and abs(v.score - 0.44) < 0.001
    assert "<0.60" in v.summary


def test_score_below_quiet_at_or_above_threshold():
    v = evaluate_condition(_sb(), _samples(["PASS"] * 5, [0.6, 0.6, 0.6, 0.6, 0.6]))
    assert v.fires is False
    assert v.score == 0.6 and "≥0.60" in v.summary


def test_score_below_ignores_none_values_in_average():
    # Only the 3 with values contribute; the 2 None entries are ignored.
    v = evaluate_condition(_sb(min_samples=5), _samples(["PASS"] * 5, [0.2, None, 0.4, None, 0.6]))
    assert v.fires is True
    assert v.score is not None and abs(v.score - 0.4) < 0.001
    # sample_size reports the count of samples that contributed (the values), not the raw window.
    assert v.sample_size == 3


def test_score_below_no_numeric_values_is_quiet():
    # All samples are text-only — can't compute an average, must not fire.
    v = evaluate_condition(_sb(), _samples(["PASS"] * 5, [None] * 5))
    assert v.fires is False
    assert v.skipped_reason == "no_numeric_values"


# ── trace_failure_rate ───────────────────────────────────────────────────────
def test_trace_failure_rate_uses_label_in_summary():
    spec = {"type": "trace_failure_rate", "window_minutes": 60, "min_samples": 10, "threshold": 0.10}
    v = evaluate_condition(spec, _samples(["FAIL"] * 3 + ["PASS"] * 7))
    assert v.fires is True
    assert "trace failure rate" in v.summary


# ── safety net: unknown / malformed conditions ───────────────────────────────
def test_unknown_condition_type_is_soft_noop():
    v = evaluate_condition({"type": "magic"}, _samples(["FAIL"] * 100))
    assert v.fires is False
    assert v.skipped_reason == "unknown_condition"
    # `score` is None — caller should NOT display "0%" for an unevaluated condition.
    assert v.score is None


def test_missing_min_samples_defaults_to_one():
    # No `min_samples` set → defaults to 1 (any sample is enough).
    v = evaluate_condition(
        {"type": "fail_rate_over", "threshold": 0.0},
        _samples(["FAIL"]),
    )
    assert v.fires is True


def test_zero_min_samples_clamps_to_one():
    # A weirdly-zero `min_samples` shouldn't divide-by-zero or skip everything.
    v = evaluate_condition(
        {"type": "fail_rate_over", "min_samples": 0, "threshold": 0.0},
        _samples(["FAIL"]),
    )
    assert v.fires is True
