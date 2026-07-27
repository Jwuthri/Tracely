"""DELETE /api/sessions — the traces table's multi-select conversation delete.

ClickHouse is stubbed (the tests are hermetic); what's locked down here is the wiring: project
scoping, de-duplication of the thread list, and the empty-body guard.
"""

from __future__ import annotations

import pytest

from tracely.api.routers import sessions as sessions_router


@pytest.fixture
def captured(monkeypatch):
    calls: list[tuple[str, list[str]]] = []

    async def fake_delete(project_id: str, threads: list[str]) -> int:
        calls.append((project_id, threads))
        return len(threads) * 2  # pretend every thread had 2 traces

    monkeypatch.setattr(sessions_router.deletes, "delete_threads", fake_delete)
    return calls


async def _token(client) -> str:
    r = await client.post("/auth/register", json={"email": "o@x.test", "password": "hunter2-pw"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def test_delete_sessions_scopes_and_dedupes(client, captured):
    tok = await _token(client)
    r = await client.request(
        "DELETE",
        "/api/sessions",
        headers={"Authorization": f"Bearer {tok}"},
        json={"threads": ["t-1", "t-2", "t-1", ""]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"threads": 2, "traces": 4}
    (project_id, threads), = captured
    assert project_id and threads == ["t-1", "t-2"]


async def test_delete_sessions_rejects_empty(client, captured):
    tok = await _token(client)
    r = await client.request(
        "DELETE",
        "/api/sessions",
        headers={"Authorization": f"Bearer {tok}"},
        json={"threads": [""]},
    )
    assert r.status_code == 400
    assert captured == []


async def test_delete_sessions_requires_auth(client, captured):
    r = await client.request("DELETE", "/api/sessions", json={"threads": ["t-1"]})
    assert r.status_code in (401, 403)
    assert captured == []
