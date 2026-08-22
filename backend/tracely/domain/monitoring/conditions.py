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

Conditions come in two families, and a monitor is exactly one of them:

- **polled** (`POLLED_TYPES`) — a threshold over a sliding window, evaluated by the Celery beat
  every 5 minutes via `evaluate_condition`. Answers "is the failure rate creeping up?".
- **event** (`EVENT_TYPES`) — a discrete thing that just happened (a CI gate failed, a
  conversation broke, a new failure mode appeared), matched by `event_matches` inline in the
  pipeline that produced it. No window, no beat, no min_samples: the event IS the signal.

Same table, same channels, same dedup — only the trigger differs. `evaluate_condition` refuses
event types (and vice versa) so a mis-typed condition stays silent instead of paging on nothing.
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


# Windowed thresholds — the beat evaluates these (`evaluate_condition`).
POLLED_TYPES = frozenset({"fail_rate_over", "score_below", "trace_failure_rate"})
# Discrete events — the pipeline fires these (`event_matches`).
EVENT_TYPES = frozenset({"gate_failed", "trace_failed", "cluster_new"})
_TYPES = POLLED_TYPES


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


# ── event conditions ──────────────────────────────────────────────────────────


def is_event_condition(spec: dict) -> bool:
    """True when this monitor is fired by the pipeline rather than polled by the beat. The beat
    skips these — otherwise every tick would overwrite the event's `last_fired_summary` with
    "unknown condition type"."""
    return str((spec or {}).get("type") or "").strip() in EVENT_TYPES


def event_matches(spec: dict, event: dict, target_agent: str = "") -> bool:
    """Does `event` match this monitor's event condition? Pure — the whole "which alerts fire"
    decision, testable without a database.

    `event` is what the pipeline reports: `{type, agent, agent_id, env, text, score_names}`.
    Every filter is optional and ANDed; an event condition with no filters means "every one of
    these". Filters:

    - `target_agent` (a column on the monitor, not the condition): the monitor's scope — matches
      the agent's slug OR its registry id, so a UI that stores either keeps working.
    - `env`: gate environment (`ci`, `staging`, …).
    - `score_name`: only when THIS evaluator is among the ones that failed.
    - `contains`: case-insensitive substring of `text` (the failure reason, gate summary or
      cluster label) — this is the "page me when a conversation errors with xyz" knob.
    """
    if str((spec or {}).get("type") or "").strip() != str((event or {}).get("type") or "").strip():
        return False
    scope = (target_agent or "").strip()
    if scope and scope not in {str(event.get("agent") or ""), str(event.get("agent_id") or "")}:
        return False
    env = str(spec.get("env") or "").strip()
    if env and env != str(event.get("env") or "").strip():
        return False
    score_name = str(spec.get("score_name") or "").strip()
    if score_name and score_name not in [str(n) for n in event.get("score_names") or []]:
        return False
    needle = str(spec.get("contains") or "").strip().lower()
    if needle and needle not in str(event.get("text") or "").lower():
        return False
    return True
