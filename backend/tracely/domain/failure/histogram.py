"""Pure occurrence-over-time bucketing for the cluster detail histogram."""

from __future__ import annotations

from datetime import datetime, timedelta


def histogram(timestamps: list[datetime | None], buckets: int = 12) -> list[dict]:
    """Bucket `timestamps` evenly across [first, last seen] into `buckets` intervals."""
    ts = sorted(t for t in timestamps if t)
    if not ts:
        return []
    lo, hi = ts[0], ts[-1]
    span = (hi - lo).total_seconds()
    if span <= 0:
        return [{"t": lo.isoformat(), "count": len(ts)}]
    width = span / buckets
    counts = [0] * buckets
    for t in ts:
        counts[min(buckets - 1, int((t - lo).total_seconds() / width))] += 1
    return [
        {"t": (lo + timedelta(seconds=width * i)).isoformat(), "count": counts[i]}
        for i in range(buckets)
    ]
