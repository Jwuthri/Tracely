"""GET /api/export — the whole workspace as NDJSON.

ClickHouse is stubbed (hermetic, like the other router tests); what's locked down is the part that
can silently lose data: the paging loop must walk past the first page and stop, every thread must
come out as exactly one line of the single-thread export shape, and a datetime in a score row must
not truncate the stream.
"""

from __future__ import annotations

import json

import pytest

from tracely.api.routers import sessions as sessions_router


@pytest.fixture
def stub_ch(monkeypatch):
    threads = [f"t-{i}" for i in range(5)]
    calls: list[tuple[int, int]] = []

    async def sessions_overview(project_id, limit, offset, *a, **kw):
        calls.append((limit, offset))
        return [
            # every other conversation belongs to tenant A, and t-4 carries broken metadata
            {"thread": t, "metadata": (
                "not json" if t == "t-4" else
                json.dumps({"business_id": "A" if i % 2 == 0 else "B", "env": "sandbox"})
            )}
            for i, t in enumerate(threads)
        ][offset : offset + limit]

    async def session_turns(project_id, thread_id, advisory):
        return [{"trace_id": f"{thread_id}-tr", "input": "hi", "output": "yo", "tokens": 3}]

    async def thread_spans_full(project_id, thread_id):
        return [{
            "trace_id": f"{thread_id}-tr", "span_id": "s1", "name": "root",
            "tool_calls": '[{"name": "search"}]', "tool_call_names": ["search"],
        }]

    async def conversation_scores(project_id, thread_id):
        # a datetime here is what breaks a naive json.dumps
        from datetime import datetime
        return [{"name": "helpfulness", "verdict": "PASS", "ts": datetime(2026, 1, 1)}]

    async def scores_by_trace(project_id, trace_ids):
        return {}

    for fn in (sessions_overview, session_turns, thread_spans_full,
               conversation_scores, scores_by_trace):
        monkeypatch.setattr(sessions_router.async_reader, fn.__name__, fn)

    async def advisory_score_names(project_id):  # reads Postgres; nothing advisory here
        return []

    monkeypatch.setattr(sessions_router, "advisory_score_names", advisory_score_names)
    monkeypatch.setattr(sessions_router, "_EXPORT_PAGE", 2)
    return calls


async def _token(client) -> str:
    r = await client.post("/auth/register", json={"email": "x@x.test", "password": "hunter2-pw"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def test_export_streams_every_thread_across_pages(client, stub_ch):
    tok = await _token(client)
    r = await client.get("/api/export", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-ndjson")

    lines = [json.loads(x) for x in r.text.strip().split("\n")]
    assert [x["thread_id"] for x in lines] == [f"t-{i}" for i in range(5)]
    step = lines[0]["messages"][0]["steps"][0]
    assert step["span_id"] == "s1"
    # a span export that drops the tool calls cannot answer "what did the agent call?"
    assert step["tool_call_names"] == ["search"] and "search" in step["tool_calls"]
    assert lines[0]["conversation_scores"][0]["ts"] == "2026-01-01 00:00:00"
    # paged, and stopped on the short page instead of looping forever
    assert stub_ch == [(2, 0), (2, 2), (2, 4)]


async def test_export_honours_limit(client, stub_ch):
    tok = await _token(client)
    r = await client.get("/api/export?limit=3", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert len(r.text.strip().split("\n")) == 3


async def test_export_requires_auth(client, stub_ch):
    r = await client.get("/api/export")
    assert r.status_code in (401, 403)


# ── metadata filter ──────────────────────────────────────────────────────────


async def test_meta_filter_keeps_only_matching_conversations(client, stub_ch):
    tok = await _token(client)
    r = await client.get(
        "/api/export?meta=business_id=A", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200, r.text
    lines = [json.loads(x) for x in r.text.strip().split("\n")]
    assert [x["thread_id"] for x in lines] == ["t-0", "t-2"]  # t-4's metadata is unparseable


async def test_unparseable_metadata_does_not_abort_the_stream(client, stub_ch):
    """A malformed map on one conversation must not kill an export that is already streaming."""
    tok = await _token(client)
    r = await client.get(
        "/api/export?meta=env=sandbox", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200
    assert [json.loads(x)["thread_id"] for x in r.text.strip().split("\n")] == [
        "t-0", "t-1", "t-2", "t-3",
    ]


async def test_no_meta_filter_exports_everything(client, stub_ch):
    tok = await _token(client)
    r = await client.get("/api/export", headers={"Authorization": f"Bearer {tok}"})
    assert len(r.text.strip().split("\n")) == 5
