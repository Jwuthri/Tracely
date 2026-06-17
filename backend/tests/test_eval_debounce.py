"""Eval-on-ingest debounce — pure/fake-Redis tests, no broker, no DB.

Locks down the trailing-debounce that collapses a multi-batch trace into one evaluation: each batch
`bump`s a per-trace generation; a scheduled eval runs only if its generation is still the latest.
Redis is faked in-memory so the test stays offline. See infrastructure/queue/eval_debounce.py.
"""

from __future__ import annotations

import pytest

from tracely.infrastructure.queue import eval_debounce


# ── in-memory fake Redis (just the bits bump/is_latest use) ───────────────────
class _FakePipe:
    def __init__(self, store: dict) -> None:
        self._store = store
        self._ops: list[tuple] = []

    def incr(self, key: str):
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self) -> list:
        out = []
        for op in self._ops:
            if op[0] == "incr":
                self._store[op[1]] = self._store.get(op[1], 0) + 1
                out.append(self._store[op[1]])
            else:
                out.append(True)
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def pipeline(self) -> _FakePipe:
        return _FakePipe(self.store)

    def get(self, key: str):
        v = self.store.get(key)
        return None if v is None else str(v).encode()  # real redis returns bytes


class _BoomRedis:
    """Every call raises — stands in for a Redis outage."""

    def pipeline(self):
        raise RuntimeError("redis down")

    def get(self, key):
        raise RuntimeError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    r = _FakeRedis()
    monkeypatch.setattr(eval_debounce, "_get_client", lambda: r)
    return r


# ── _should_run: the pure debounce decision ──────────────────────────────────
def test_should_run_only_latest_generation():
    assert eval_debounce._should_run(3, 3) is True   # latest → run
    assert eval_debounce._should_run(2, 3) is False  # superseded → skip
    assert eval_debounce._should_run(1, 3) is False  # older still skips
    # `current` is the monotonic INCR max, so it can never trail `gen` in practice.


def test_should_run_fails_open():
    assert eval_debounce._should_run(0, 5) is True      # ungated sentinel
    assert eval_debounce._should_run(-1, 5) is True
    assert eval_debounce._should_run(2, None) is True   # key expired/missing → run


# ── bump + is_latest against a fake broker ────────────────────────────────────
def test_bump_increments_per_trace(fake_redis):
    assert eval_debounce.bump("p", "trace-a") == 1
    assert eval_debounce.bump("p", "trace-a") == 2
    assert eval_debounce.bump("p", "trace-a") == 3
    # a different trace counts independently
    assert eval_debounce.bump("p", "trace-b") == 1
    # and a different project is isolated from trace-a
    assert eval_debounce.bump("p2", "trace-a") == 1


def test_only_last_batch_runs(fake_redis):
    # three batches for one trace; only the third-scheduled eval should run.
    g1 = eval_debounce.bump("p", "t")
    g2 = eval_debounce.bump("p", "t")
    g3 = eval_debounce.bump("p", "t")
    assert eval_debounce.is_latest("p", "t", g1) is False
    assert eval_debounce.is_latest("p", "t", g2) is False
    assert eval_debounce.is_latest("p", "t", g3) is True


def test_single_batch_runs(fake_redis):
    g = eval_debounce.bump("p", "solo")
    assert eval_debounce.is_latest("p", "solo", g) is True


# ── fail-open on Redis errors (never silently drop an evaluation) ─────────────
def test_bump_returns_sentinel_on_redis_error(monkeypatch):
    monkeypatch.setattr(eval_debounce, "_get_client", lambda: _BoomRedis())
    assert eval_debounce.bump("p", "t") == 0          # ungated
    assert eval_debounce.is_latest("p", "t", 0) is True


def test_is_latest_runs_when_redis_unreachable(monkeypatch):
    monkeypatch.setattr(eval_debounce, "_get_client", lambda: _BoomRedis())
    # a real gen was assigned earlier, but the get() now fails → fail open to run
    assert eval_debounce.is_latest("p", "t", 7) is True
