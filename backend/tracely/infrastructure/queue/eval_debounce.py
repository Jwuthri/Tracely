"""Debounce online-eval scheduling so a trace whose spans arrive across several OTLP batches is
evaluated ONCE, after it goes quiet — not once per batch.

A single agent run can land in multiple OTLP export batches (the SDK flushes spans in chunks). The
old scheduler fired an `evaluate_run_task` `countdown` seconds after *every* batch touching the
trace, which (a) re-ran the evaluators — and the paid LLM judge — once per batch, and (b) could
evaluate a still-partial trace.

The fix is a trailing debounce keyed on the trace: each batch bumps a per-trace *generation* counter
in Redis and schedules the eval tagged with that generation; when a scheduled eval fires it runs only
if its generation is still the latest (no newer batch arrived). So only the final batch's task runs,
`countdown` seconds after the last span was seen.

Best-effort by design: any Redis error falls back to "run" (`bump` returns the `0` sentinel →
ungated). Over-evaluating is safe — online scores use a stable uuid5 id under `ReplacingMergeTree`, so
a re-eval replaces rather than duplicates — whereas under-evaluating would silently drop scores.
"""

from __future__ import annotations

import redis

from tracely.config import settings

_KEY = "tracely:eval:gen:{project}:{trace}"
# The counter only needs to outlive the debounce window; it then self-expires so idle traces don't
# accumulate keys. An hour is comfortably longer than any sane `eval_debounce_seconds`.
_TTL_SECONDS = 3600

_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url)
    return _client


def _should_run(gen: int, current: int | None) -> bool:
    """Pure debounce decision: should the eval tagged with `gen` run, given the trace's `current`
    latest generation? `gen <= 0` is the ungated sentinel (Redis was down when scheduling) and a
    missing `current` (key expired) both fail open to True; otherwise only the latest gen runs."""
    if gen <= 0:
        return True
    if current is None:
        return True
    return current == gen


def bump(project_id: str, trace_id: str) -> int:
    """Record a new batch for this trace; returns the generation to tag the scheduled eval with.
    Returns 0 (the ungated sentinel → the eval always runs) on any Redis error."""
    try:
        key = _KEY.format(project=project_id, trace=trace_id)
        pipe = _get_client().pipeline()
        pipe.incr(key)
        pipe.expire(key, _TTL_SECONDS)
        gen, _ = pipe.execute()
        return int(gen)
    except Exception:
        return 0


def is_latest(project_id: str, trace_id: str, gen: int) -> bool:
    """True if `gen` is still the latest batch for this trace (so this eval should run). Fails open
    (returns True) on the ungated sentinel or any Redis error — never silently drops an evaluation."""
    if gen <= 0:
        return True
    try:
        cur = _get_client().get(_KEY.format(project=project_id, trace=trace_id))
    except Exception:
        return True
    return _should_run(gen, int(cur) if cur is not None else None)
