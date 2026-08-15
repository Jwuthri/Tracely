"""Replay script derivation: actor nesting, ordering, and the sub-agent relation."""

from datetime import datetime, timedelta

from tracely.domain.traces.replay import build_replay

T0 = datetime(2026, 8, 15, 12, 0, 0)


def span(sid, parent, stype, name, at_ms, dur_ms=100, agent="", level="", **extra):
    return {
        "span_id": sid,
        "parent_span_id": parent,
        "type": stype,
        "name": name,
        "level": level,
        "agent_id": agent,
        "start_time": T0 + timedelta(milliseconds=at_ms),
        "end_time": T0 + timedelta(milliseconds=at_ms + dur_ms),
        "trace_id": "t1",
        **extra,
    }


def _conversation():
    # support-agent runs, calls an llm + a tool, then spawns a research sub-agent that
    # itself calls a tool (which fails).
    return [
        span("a", "", "AGENT", "support.run", 0, 900, agent="support"),
        span("b", "a", "GENERATION", "chat gpt-4o", 20, 120, agent="support", model_id="gpt-4o"),
        span("c", "a", "TOOL", "lookup_order", 160, 90, agent="support"),
        span("d", "a", "SUBAGENT", "research.run", 300, 500, agent="research"),
        span("e", "d", "TOOL", "web_search", 340, 200, agent="research", level="ERROR"),
    ]


def test_actors_and_nesting():
    r = build_replay(_conversation(), {"support": "support-agent", "research": "research-agent"})
    actors = {a["id"]: a for a in r["actors"]}
    assert [a["id"] for a in r["actors"]] == ["support", "research"]  # first-appearance order
    assert actors["support"]["kind"] == "agent" and actors["support"]["depth"] == 0
    assert actors["research"]["kind"] == "subagent"
    assert actors["research"]["parent"] == "support"
    assert actors["support"]["name"] == "support-agent"  # registry display name


def test_child_spans_attribute_to_their_owning_actor():
    r = build_replay(_conversation())
    by_name = {e["name"]: e for e in r["events"]}
    assert by_name["lookup_order"]["actor"] == "support"
    assert by_name["web_search"]["actor"] == "research"  # nested under the sub-agent, not support
    assert by_name["web_search"]["status"] == "error"
    assert by_name["chat gpt-4o"]["kind"] == "llm"


def test_timeline_is_relative_and_ordered():
    r = build_replay(_conversation())
    assert [e["t_ms"] for e in r["events"]] == sorted(e["t_ms"] for e in r["events"])
    assert r["events"][0]["t_ms"] == 0            # clock starts at the first span
    assert r["duration_ms"] == 900                # last end relative to t0
    assert r["events"][1]["dur_ms"] == 120


def test_error_counts_land_on_the_actor_that_failed():
    r = build_replay(_conversation())
    actors = {a["id"]: a for a in r["actors"]}
    assert actors["research"]["errors"] == 1
    assert actors["support"]["errors"] == 0


def test_empty_and_malformed_are_safe():
    assert build_replay([]) == {"duration_ms": 0, "actors": [], "events": []}
    # a parent chain pointing at a missing span must not hang or crash
    r = build_replay([span("x", "ghost", "TOOL", "orphan", 0, 5, agent="solo")])
    assert r["actors"][0]["id"] == "solo" and r["events"][0]["actor"] == "solo"


def test_turns_reusing_span_ids_stay_separate():
    """Two turns of one conversation, each numbering spans from 1 — the parent chain must not
    resolve across traces (that merged both turns' agents into one actor)."""
    turn1 = [
        dict(span("1", "", "AGENT", "support.run", 0, 500, agent="support"), trace_id="t1"),
        dict(span("2", "1", "TOOL", "lookup", 50, 80, agent="support"), trace_id="t1"),
    ]
    turn2 = [
        dict(span("1", "", "AGENT", "billing.run", 900, 400, agent="billing"), trace_id="t2"),
        dict(span("2", "1", "AGENT", "audit.run", 950, 200, agent="audit"), trace_id="t2"),
    ]
    r = build_replay(turn1 + turn2)
    actors = {a["id"]: a for a in r["actors"]}
    assert set(actors) == {"support", "billing", "audit"}
    assert actors["audit"]["parent"] == "billing"   # not support, whose span also had id "1"
    assert actors["support"]["parent"] == ""
    assert actors["support"]["events"] == 2
