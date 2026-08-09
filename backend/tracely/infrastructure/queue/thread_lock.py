"""One writer per thread for the sequential-eval pass.

A thread's sequential pass mutates shared state that must stay ordered: the columns' durable
judge conversations and their chain-progress rows. Two passes interleaving (the debounced ingest
task racing an on-demand Run) would append items out of order. This is a plain Redis
SET-NX-with-TTL lock around the pass.

Best-effort, like the debounce next door: Redis down, or the wait timing out, yields WITHOUT the
lock (logged) — an eval that never runs is worse than a rare interleave, which the chain-progress
prefix check turns into a rebuild on the next pass rather than lasting corruption. The TTL backs
the same guarantee against a crashed holder.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from collections.abc import Iterator

import structlog

log = structlog.get_logger(__name__)

_KEY = "tracely:eval:threadlock:{project}:{thread}"
_TTL_SECONDS = 900  # generously above any real pass; a crashed holder frees itself here
_WAIT_SECONDS = 120  # how long a second pass waits before proceeding unlocked
_POLL_SECONDS = 0.5

# compare-and-delete, so an expired holder can't free the lock out from under its successor
_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end
"""


def _client():
    from tracely.infrastructure.queue.eval_debounce import _get_client

    return _get_client()


@contextlib.contextmanager
def thread_pass_lock(project_id: str, thread_id: str) -> Iterator[None]:
    key = _KEY.format(project=project_id, thread=thread_id)
    token = uuid.uuid4().hex
    acquired = False
    try:
        client = _client()
        deadline = time.monotonic() + _WAIT_SECONDS
        while True:
            if client.set(key, token, nx=True, ex=_TTL_SECONDS):
                acquired = True
                break
            if time.monotonic() >= deadline:
                log.warning("thread_pass_lock_timeout", thread_id=thread_id)
                break
            time.sleep(_POLL_SECONDS)
    except Exception as exc:  # Redis down → run unlocked rather than not at all
        log.warning("thread_pass_lock_unavailable", thread_id=thread_id, error=str(exc))
    try:
        yield
    finally:
        if acquired:
            try:
                _client().eval(_RELEASE, 1, key, token)
            except Exception as exc:
                log.warning("thread_pass_unlock_failed", thread_id=thread_id, error=str(exc))
