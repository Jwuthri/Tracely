"""Conversation agents: deriving agents from spans, the declared-catalog formatter (@LIST_AGENT),
and the panel shaper that merges observed tool counts into the declared catalog."""

from __future__ import annotations

import json

from tracely.api.routers.sessions import _shape_declared_agent
from tracely.domain.evaluation.template_resolver import _format_agent_catalog, build_context
from tracely.domain.traces.spans import system_prompt
from tracely.infrastructure.clickhouse import async_reader

_CATALOG = [
    {
        "name": "Support Agent",
        "description": "Handles customer inquiries",
        "tools": {
            "lookup_order": {
                "name": "lookup_order",
                "description": "Look up order by ID",
                "parameters": {"order_id": "string"},
            }
        },
    }
]


def test_format_agent_catalog_includes_desc_and_params():
    out = _format_agent_catalog(_CATALOG)
    assert "Support Agent: Handles customer inquiries" in out
    assert "lookup_order" in out
    assert "Look up order by ID" in out
    assert "params: order_id" in out


def test_list_agent_prefers_declared_catalog():
    # @LIST_AGENT resolves from the declared catalog when provided, ignoring spans
    ctx = build_context(
        "AGENT_RUN", thread_spans=[{"trace_id": "t", "agent_id": "x"}],
        current_trace_id="t", wanted_vars=["LIST_AGENT"], declared_agents=_CATALOG,
    )
    assert ctx.agents and "Support Agent" in ctx.agents and "lookup_order" in ctx.agents


def test_shape_declared_agent_merges_observed_counts():
    shaped = _shape_declared_agent(_CATALOG[0], {"lookup_order": 3})
    assert shaped["name"] == "Support Agent"
    tool = shaped["tools"][0]
    assert tool["name"] == "lookup_order"
    assert tool["count"] == 3  # observed execution count merged in
    assert tool["parameters"] == {"order_id": "string"}


def test_shape_declared_agent_passes_extra_config_through():
    # config the trace can't show (guardrails, prompts, model) must survive the panel shaper
    shaped = _shape_declared_agent(
        {
            "name": "router",
            "system_prompt": "You route.",
            "model": {"name": "claude-opus-4", "temperature": 0.2},
            "guardrails": [{"name": "pii_filter", "on": "output"}],
            "tools": {"search": {"description": "web search", "timeout_s": 30}},
        },
        {"search": 1},
    )
    assert shaped["system_prompt"] == "You route."
    assert shaped["model"] == {"name": "claude-opus-4", "temperature": 0.2}
    assert shaped["guardrails"][0]["name"] == "pii_filter"
    assert shaped["tools"][0]["timeout_s"] == 30  # per-tool extras survive too
    assert shaped["tools"][0]["count"] == 1  # …without clobbering the derived count


def test_shape_declared_agent_extras_never_override_panel_keys():
    shaped = _shape_declared_agent(
        {"tools": {"t": {"name": "t", "count": 999}}}, {"t": 2}
    )
    assert shaped["name"] == "agent"  # missing name still defaulted
    assert shaped["tools"][0]["count"] == 2  # observed count wins over a declared one


def test_system_prompt_from_spans():
    spans = [
        {"input": json.dumps([{"role": "user", "content": "hi"}])},  # no system message
        {"input": json.dumps([
            {"role": "system", "content": "You are terse."},
            {"role": "user", "content": "hi"},
        ])},
        {"input": json.dumps([{"role": "system", "content": "later, ignored"}])},
    ]
    assert system_prompt(spans) == "You are terse."  # first one wins


def test_system_prompt_handles_blocks_and_absence():
    blocks = [{"input": json.dumps([
        {"role": "system", "content": [
            {"type": "text", "text": "line one"},
            {"type": "image", "url": "x"},  # non-text blocks ignored
            {"type": "text", "text": "line two"},
        ]}
    ])}]
    assert system_prompt(blocks) == "line one\nline two"
    assert system_prompt([{"input": json.dumps([{"role": "user", "content": "hi"}])}]) == ""
    assert system_prompt([{"input": "not json {\"system\"}"}, {"input": None}, {}]) == ""


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
