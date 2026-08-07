"""Shared Redis clients — the third Redis consumer is where the copies stop.

`eval_debounce` and `llm/provider` grew their own module-local clients; quota code uses these
instead. Both clients carry SHORT socket timeouts, because every caller here treats Redis as an
optimization with a fallback (count later / read Postgres / allow the request): a down Redis
must cost milliseconds, not a connect-timeout stall on the ingest hot path. The async client is
for FastAPI handlers — the sync one used from a route would block the event loop.
"""

from __future__ import annotations

from typing import Any

from tracely.config import settings

_SYNC: Any = None
_ASYNC: Any = None

# Fail-fast budget. The API edge calls Redis per ingest request; 200ms is the most a cache
# lookup is allowed to cost before the caller falls back.
_TIMEOUT_S = 0.2


def sync_redis():
    """Worker-side client (Celery tasks are sync)."""
    global _SYNC
    if _SYNC is None:
        import redis

        _SYNC = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=_TIMEOUT_S,
            socket_timeout=_TIMEOUT_S,
        )
    return _SYNC


def async_redis():
    """API-side client (FastAPI handlers are async)."""
    global _ASYNC
    if _ASYNC is None:
        import redis.asyncio as aredis

        _ASYNC = aredis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=_TIMEOUT_S,
            socket_timeout=_TIMEOUT_S,
        )
    return _ASYNC
