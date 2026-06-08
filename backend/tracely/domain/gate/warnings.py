"""Soft (non-blocking) gate warnings — pure deltas vs the last green gate."""

from __future__ import annotations

from tracely.config import settings

# Floor: don't flag noise on tiny hermetic latencies (~0 ms replays).
_BASELINE_LATENCY_FLOOR_MS = 50


def delta_warnings(latency_ms: float, total_tokens: int, baseline) -> list[str]:
    """Compare this run's latency/tokens to a baseline GateRun and emit % regressions.

    `baseline` is the agent's last PASS gate (or None — first gate ever, no comparison). Returns
    an empty list if there's nothing to flag. Thresholds come from `settings.gate_*_warn_pct`.
    """
    if baseline is None:
        return []
    warns: list[str] = []
    if (baseline.latency_ms or 0) >= _BASELINE_LATENCY_FLOOR_MS:
        d = (latency_ms - baseline.latency_ms) / baseline.latency_ms * 100
        if d >= settings.gate_latency_warn_pct:
            warns.append(
                f"latency +{d:.0f}% vs baseline ({baseline.latency_ms:.0f}→{latency_ms:.0f} ms)"
            )
    if (baseline.total_tokens or 0) > 0:
        d = (total_tokens - baseline.total_tokens) / baseline.total_tokens * 100
        if d >= settings.gate_tokens_warn_pct:
            warns.append(
                f"tokens +{d:.0f}% vs baseline ({baseline.total_tokens}→{total_tokens})"
            )
    return warns
