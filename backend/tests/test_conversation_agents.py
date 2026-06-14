"""Conversation agents: deriving agents + tools from a thread's spans (no stored catalog)."""

from __future__ import annotations

from tracely.infrastructure.clickhouse import async_reader


async def test_thread_agents_derivation(monkeypatch):
    spans = [
        # agent a1 executes `search`, then a generation that only *requests* `compare`
        {"agent_id": "a1", "type": "TOOL", "name": "search", "output": "ok"},
        {"agent_id": "a1", "type": "TOOL", "name": "search", "output": "ok"},
        {"agent_id": "a1", "type": "GENERATION", "output": "done", "tool_call_names": ["compare"]},
        # agent a2 executes `lookup` once
        {"agent_id": "a2", "type": "TOOL", "name": "lookup", "output": "ok"},
    ]

    async def fake_spans(project_id, thread_id):
        return spans

    monkeypatch.setattr(async_reader, "thread_spans_full", fake_spans)
    agents = await async_reader.thread_agents("p", "thread-1")

    by_id = {a["agent_id"]: a for a in agents}
    assert set(by_id) == {"a1", "a2"}

    a1 = by_id["a1"]
    tools = {t["name"]: t["count"] for t in a1["tools"]}
    assert tools == {"search": 2, "compare": 0}  # executed twice; compare only requested
    assert a1["tool_call_count"] == 2
    assert a1["span_count"] == 3

    # sorted by tool activity then span volume → a1 (2 calls) before a2 (1 call)
    assert agents[0]["agent_id"] == "a1"


async def test_thread_agents_empty(monkeypatch):
    async def fake_spans(project_id, thread_id):
        return []

    monkeypatch.setattr(async_reader, "thread_spans_full", fake_spans)
    assert await async_reader.thread_agents("p", "t") == []
