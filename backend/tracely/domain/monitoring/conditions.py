"""Pure monitor-condition evaluation: take a condition spec + a window's samples, return whether
the monitor should fire and a human-readable summary.

A "sample" is one observation in the window — the engine collects them as `{verdict, value}`
dicts so the same `evaluate_condition` works whether the source is an evaluator score row
(`tracely.run.quality` per trace) or a trace's overall failing status. The condition is dispatched
on `type`; unknown types are a soft no-op (the monitor stays silent rather than the worker
crashing). `min_samples` is a guardrail against alerts on tiny denominators (1 of 1 is not a 100%
failure rate worth waking someone for).

All math is dimensionless: rates are 0..1, thresholds compare to that, and `score_below`'s
threshold is on whatever scale the underlying numeric `value` uses (typically 0..1 for `score`
output_type judges). The orchestrator is responsible for windowing — this layer doesn't know what
time means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Sample:
    """One observation in the window. `verdict` ∈ {PASS, FAIL, ""} (empty for informational
    scores with no threshold); `value` is the numeric reading when the score is numeric, None
    otherwise."""
    verdict: str
    value: float | None = None


@dataclass(frozen=True)
class Verdict:
    """Outcome of evaluating a condition. `fires=True` means notify; `summary` is a one-liner
    persisted to the monitor row + shown in alerts. `score` is the metric the condition is
    watching (rate or average), surfaced in the UI even when the condition hasn't fired."""
    fires: bool
    summary: str
    score: float | None
    sample_size: int
    skipped_reason: str = ""  # "min_samples_unmet" / "unknown_condition" / "" if evaluated


_TYPES = {"fail_rate_over", "score_below", "trace_failure_rate"}


def evaluate_condition(spec: dict, samples: Iterable[Sample]) -> Verdict:
    """Evaluate `spec` (a `Monitor.condition` JSON dict) against `samples`. Pure. The orchestrator
    is responsible for filtering samples to the window + agent BEFORE calling this — so this
    layer can be tested without ClickHouse."""
    items = list(samples)
    cond_type = str(spec.get("type") or "").strip()
    if cond_type not in _TYPES:
        return Verdict(False, f"unknown condition type {cond_type!r}", None, 0, "unknown_condition")

    min_samples = max(int(spec.get("min_samples") or 1), 1)
    n = len(items)
    if n < min_samples:
        return Verdict(
            False,
            f"only {n} sample(s) in window; needs {min_samples}",
            None,
            n,
            "min_samples_unmet",
        )

    threshold = float(spec.get("threshold") or 0.0)
    if cond_type in ("fail_rate_over", "trace_failure_rate"):
        return _evaluate_rate(items, threshold, cond_type)
    # score_below
    return _evaluate_score_below(items, threshold)


def _evaluate_rate(samples: list[Sample], threshold: float, cond_type: str) -> Verdict:
    fails = sum(1 for s in samples if s.verdict == "FAIL")
    rate = fails / len(samples)
    fires = rate > threshold  # strictly over → ties don't page
    label = "FAIL rate" if cond_type == "fail_rate_over" else "trace failure rate"
    summary = (
        f"{label} {rate:.0%} (>{threshold:.0%}) over {len(samples)} samples — "
        f"{fails} failing"
    ) if fires else (
        f"{label} {rate:.0%} (≤{threshold:.0%}) over {len(samples)} samples"
    )
    return Verdict(fires, summary, rate, len(samples))


def _evaluate_score_below(samples: list[Sample], threshold: float) -> Verdict:
    # Average over samples that actually carry a numeric value; if NONE do, we can't evaluate.
    values = [s.value for s in samples if s.value is not None]
    if not values:
        return Verdict(False, "no numeric values in window", None, len(samples), "no_numeric_values")
    avg = sum(values) / len(values)
    fires = avg < threshold  # strictly below → ties don't page
    summary = (
        f"avg score {avg:.2f} (<{threshold:.2f}) over {len(values)} samples"
    ) if fires else (
        f"avg score {avg:.2f} (≥{threshold:.2f}) over {len(values)} samples"
    )
    return Verdict(fires, summary, avg, len(values))
