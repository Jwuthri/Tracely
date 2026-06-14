"""`/health` is a real readiness probe: 200 only when every dependency answers, 503 otherwise.

The endpoint talks to ClickHouse + Postgres directly (not the overridden auth session), so we
monkeypatch both seams to assert the status mapping hermetically — the behavior that used to be a
static `ok` and let a backend with a dead DB keep reporting healthy.
"""

from __future__ import annotations


class _FakeCH:
    def __init__(self, ping_result):
        self._ping_result = ping_result

    async def ping(self) -> bool:
        if isinstance(self._ping_result, Exception):
            raise self._ping_result
        return self._ping_result


class _FakeSession:
    def __init__(self, fail: bool):
        self._fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *a, **k):
        if self._fail:
            raise RuntimeError("postgres unreachable")
        return None


def _patch(monkeypatch, *, ch, pg_fails: bool):
    async def _get_async_client(*a, **k):
        return _FakeCH(ch)

    monkeypatch.setattr("tracely.api.routers.health.get_async_client", _get_async_client)
    monkeypatch.setattr(
        "tracely.api.routers.health.AsyncSessionLocal", lambda: _FakeSession(pg_fails)
    )


async def test_health_ok_when_all_deps_up(client, monkeypatch):
    _patch(monkeypatch, ch=True, pg_fails=False)
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "dependencies": {"clickhouse": "ok", "postgres": "ok"}}


async def test_health_503_when_clickhouse_unreachable(client, monkeypatch):
    _patch(monkeypatch, ch=RuntimeError("ch down"), pg_fails=False)
    r = await client.get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["dependencies"] == {"clickhouse": "error", "postgres": "ok"}


async def test_health_503_when_postgres_down(client, monkeypatch):
    _patch(monkeypatch, ch=True, pg_fails=True)
    r = await client.get("/health")
    assert r.status_code == 503
    assert r.json()["dependencies"]["postgres"] == "error"
