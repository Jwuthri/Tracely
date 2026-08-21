"""Replay script derivation: actor nesting, ordering, and the sub-agent relation."""

import json
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


def test_chain_wrappers_are_containers_not_work():
    """A harness's turn wrapper (CHAIN) brackets everyone else's spans; scoring it as activity
    made its agent look busy for the whole conversation (real trace: `agent_teams.turn`)."""
    spans = [
        span("w", "", "CHAIN", "agent_teams.turn", 0, 6000, agent="team"),
        span("g", "", "GENERATION", "chat", 100, 400, agent="supervisor"),
    ]
    r = build_replay(spans)
    by_name = {e["name"]: e for e in r["events"]}
    assert by_name["agent_teams.turn"]["kind"] == "turn"
    assert by_name["agent_teams.turn"]["container"] is True
    assert by_name["chat"]["container"] is False


def test_subagent_edge_from_a_tool_call_named_after_an_agent():
    """Real multi-agent traces call a sub-agent as a tool and often lose the parent span, so the
    nesting is gone — the tool NAME is the surviving edge."""
    spans = [
        dict(span("s", "missing-parent", "GENERATION", "chat", 0, 300, agent="sup"),
             tool_call_names=["agent_faq"]),
        span("f", "also-missing", "GENERATION", "chat", 400, 300, agent="faq"),
    ]
    r = build_replay(spans, {"sup": "supervisor", "faq": "agent_faq"})
    actors = {a["id"]: a for a in r["actors"]}
    assert actors["faq"]["parent"] == "sup"
    assert actors["faq"]["kind"] == "subagent"
    assert actors["sup"]["depth"] == 0


def test_tool_call_edges_cannot_build_a_cycle():
    spans = [
        dict(span("a", "", "GENERATION", "chat", 0, 100, agent="one"), tool_call_names=["two"]),
        dict(span("b", "", "GENERATION", "chat", 200, 100, agent="two"), tool_call_names=["one"]),
    ]
    r = build_replay(spans, {"one": "one", "two": "two"})
    depths = {a["id"]: a["depth"] for a in r["actors"]}
    assert max(depths.values()) <= 1        # terminates, no runaway walk


# ── fleet enrichment: stations, delegation targets, speech ────────────────────


def test_stations_route_events_to_the_right_furniture():
    spans = [
        span("a", "", "AGENT", "run", 0, 2000, agent="a1"),
        span("b", "a", "GENERATION", "chat", 10, 100, agent="a1"),
        span("c", "a", "THINKING", "thinking", 120, 50, agent="a1"),
        span("d", "a", "TOOL", "charge_card", 200, 100, agent="a1"),
        span("e", "a", "TOOL", "lookup_faq", 320, 100, agent="a1"),
        span("f", "a", "RETRIEVER", "vector_fetch", 440, 100, agent="a1"),
        span("g", "a", "SKILL", "refund-flow", 560, 300, agent="a1"),
    ]
    r = build_replay(spans)
    st = {e["name"]: e["station"] for e in r["events"]}
    assert st["chat"] == "desk"
    assert st["thinking"] == "desk"
    assert st["charge_card"] == "computer"  # TOOL -> the computer, whatever its name
    assert st["lookup_faq"] == "computer"   # a TOOL named lookup is still a tool — the span
    assert st["vector_fetch"] == "library"  # TYPE decides: RETRIEVER -> the bookshelf
    assert st["refund-flow"] == "library"   # SKILL -> the bookshelf
    kinds = {e["name"]: e["kind"] for e in r["events"]}
    assert kinds["thinking"] == "think"
    assert kinds["refund-flow"] == "skill"


def test_delegate_span_resolves_callee_via_alias_and_carries_the_task():
    spans = [
        span("a", "", "AGENT", "sup.run", 0, 3000, agent="sup-uuid"),
        dict(span("b", "a", "DELEGATE", "delegate:billing", 100, 2000, agent="sup-uuid"),
             callee_agent_id="billing", input="refund order 4471, card ending 1234"),
        span("c", "b", "AGENT", "billing.run", 200, 1500, agent="billing-uuid"),
    ]
    r = build_replay(spans, aliases={"billing": "billing-uuid"})
    d = next(e for e in r["events"] if e["kind"] == "delegate")
    assert d["container"] is True
    assert d["delegate_to"] == "billing-uuid"
    assert d["say"] == "refund order 4471, card ending 1234"
    actors = {a["id"]: a for a in r["actors"]}
    assert actors["billing-uuid"]["parent"] == "sup-uuid"


def test_tool_call_handoff_gets_delegate_to_and_the_arguments_as_speech():
    import json as _json
    out = _json.dumps([{"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "agent_faq", "arguments": _json.dumps({"query": "find the remote"})}}]}])
    spans = [
        dict(span("s", "", "GENERATION", "chat", 0, 400, agent="sup"),
             tool_call_names=["agent_faq"], output=out),
        span("f", "", "GENERATION", "chat", 500, 300, agent="faq"),
    ]
    r = build_replay(spans, {"faq": "agent_faq"})
    ev = r["events"][0]
    assert ev["delegate_to"] == "faq"
    assert ev["station"] == "peer"
    assert ev["say"] == "find the remote"


def test_plain_tools_never_become_delegations():
    spans = [
        dict(span("s", "", "GENERATION", "chat", 0, 300, agent="a1"), tool_call_names=["lookup_faq"]),
        span("t", "", "TOOL", "lookup_faq", 350, 200, agent="a1"),
    ]
    r = build_replay(spans)
    assert all(e["delegate_to"] == "" for e in r["events"])


def test_detail_shows_the_words_not_the_json_envelope():
    out = '[{"role": "assistant", "content": "Done — refund issued."}]'
    r = build_replay([dict(span("a", "", "GENERATION", "chat", 0, 100, agent="x"), output=out)])
    assert r["events"][0]["detail"] == "Done — refund issued."


# ── review-pass regressions ───────────────────────────────────────────────────


def test_say_never_shows_the_prompt_envelope():
    """A GENERATION span's input is the prompt as JSON — the bubble must dig the ARGUMENTS out
    of the output instead of parroting the envelope (system prompt included)."""
    import json as _json
    prompt = _json.dumps([{"role": "system", "content": "You are the supervisor..."}])
    out = _json.dumps([{"role": "assistant", "content": "", "tool_calls": [
        {"id": "c", "type": "function",
         "function": {"name": "agent_faq", "arguments": _json.dumps({"query": "find the remote"})}}]}])
    spans = [
        dict(span("s", "", "GENERATION", "chat", 0, 300, agent="sup"),
             tool_call_names=["agent_faq"], input=prompt, output=out),
        span("f", "", "GENERATION", "chat", 400, 100, agent="faq"),
    ]
    r = build_replay(spans, {"faq": "agent_faq"})
    assert r["events"][0]["say"] == "find the remote"


def test_malformed_tool_calls_never_crash_say():
    out = '[{"role": "assistant", "tool_calls": [{"id": "x", "function": "agent_faq"}]}]'
    spans = [
        dict(span("d", "", "DELEGATE", "delegate:faq", 0, 300, agent="sup"),
             callee_agent_id="faq", output=out),
        span("f", "d", "AGENT", "faq.run", 50, 200, agent="faq-uuid"),
    ]
    r = build_replay(spans, aliases={"faq": "faq-uuid"})  # must not raise
    assert r["events"][0]["say"] == ""


def test_tool_sharing_an_agent_slug_stays_a_plain_tool():
    """Agent slugs and tool names share a namespace — a TOOL named "search" next to an agent
    whose slug is "search" must not become a walk-over delegation."""
    spans = [
        span("t", "", "TOOL", "search", 0, 100, agent="concierge-uuid"),
        span("g", "", "GENERATION", "chat", 200, 100, agent="search-uuid"),
    ]
    r = build_replay(spans, aliases={"search": "search-uuid"})
    tool_ev = r["events"][0]
    assert tool_ev["delegate_to"] == ""
    assert tool_ev["station"] == "computer"


def test_containers_never_get_inferred_delegations():
    """A turn envelope listing an agent-named tool call must not walk its agent for the turn."""
    spans = [
        dict(span("w", "", "CHAIN", "agent_teams.turn", 0, 5000, agent="team"),
             tool_call_names=["agent_faq"]),
        span("f", "", "GENERATION", "chat", 100, 300, agent="faq"),
    ]
    r = build_replay(spans, {"faq": "agent_faq"})
    wrapper = next(e for e in r["events"] if e["name"] == "agent_teams.turn")
    assert wrapper["delegate_to"] == ""


def test_text_of_never_shows_the_message_envelope():
    """A tool-calling turn has empty content — the bubble must say what it reached for, never
    dump `[{"role": "assistant", "tool_calls": [...]}]`."""
    from tracely.domain.traces.replay import _text_of

    calls = json.dumps(
        [{"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "agent_faq.retrieve", "arguments": "{}"}},
            {"id": "call_2", "type": "function", "function": {"name": "lookup_kb"}},
        ]}]
    )
    assert _text_of(calls) == "→ agent_faq.retrieve, lookup_kb"

    # nothing sayable at all → silence, not JSON
    assert _text_of(json.dumps([{"role": "assistant", "content": ""}])) == ""
    assert _text_of(json.dumps([{"role": "assistant", "tool_calls": "junk"}])) == ""
    # content blocks
    assert _text_of(json.dumps([{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}])) == "hi"
    # a plain tool output is NOT a message envelope — it still previews (the tool-sheet card)
    assert _text_of(json.dumps({"total": 1299})) == '{"total": 1299}'


def test_declared_tools_tolerates_junk():
    from tracely.api.routers.sessions import _declared_tools

    assert _declared_tools({"tools": 42}) == []
    assert _declared_tools({"tools": "lookup"}) == []
    assert _declared_tools({"tools": True}) == []
    assert _declared_tools({"tools": {"a": {}, "b": {}}}) == [
        {"name": "a", "description": ""},
        {"name": "b", "description": ""},
    ]
    assert _declared_tools({"tools": [{"name": "x", "description": "does x"}, "y"]}) == [
        {"name": "x", "description": "does x"},
        {"name": "y", "description": ""},
    ]


def test_agent_envelope_never_swallows_the_team():
    """Julien's real supervisor trace: the turn wrapper is an AGENT span, and every child span
    carries its OWN agent_id (supervisor, balance specialist). The envelope must not absorb
    them into one actor — own agent_id beats the ancestor walk."""
    team, sup, bal = "team-uuid", "sup-uuid", "bal-uuid"
    spans = [
        span("a", "", "AGENT", "agent_teams.turn", 0, 4800, agent=team),
        dict(span("b", "a", "GENERATION", "gpt", 5, 1500, agent=sup), tool_call_names=["balance"]),
        dict(span("c", "a", "DELEGATE", "balance", 1570, 2400, agent=sup), input="current balance"),
        span("d", "c", "GENERATION", "gpt", 1580, 1100, agent=bal),
        span("e", "c", "TOOL", "mock_get_balance", 2700, 10, agent=bal),
        span("f", "a", "GENERATION", "gpt", 3980, 800, agent=sup),
    ]
    r = build_replay(
        spans,
        names={team: "tracely_demo_team", sup: "supervisor", bal: "balance"},
        aliases={"balance": bal, "supervisor": sup},
    )
    actors = {a["id"]: a for a in r["actors"]}
    assert set(actors) == {team, sup, bal}, "three actors, not one"
    by = {e["name"]: e for e in r["events"]}
    assert by["mock_get_balance"]["actor"] == bal      # specialist's tool is theirs
    assert by["gpt"]["actor"] == sup                    # supervisor's llm is theirs
    assert actors[bal]["parent"] == sup                 # DELEGATE name -> callee edge
    assert actors[bal]["kind"] == "subagent"
    # the delegation resolves by NAME and carries the task
    deleg = by["balance"]
    assert deleg["delegate_to"] == bal
    assert deleg["say"] == "current balance"
    assert deleg["container"] is True                   # DELEGATE brackets the callee's work
    # the supervisor's llm requesting "balance" is the SAME handoff — no second walk
    assert by["gpt"]["delegate_to"] == ""


def test_bubbles_decode_json_encoded_scalars():
    """`set_io` strings arrive JSON-encoded, so a plain sentence reaches us as
    '"Delegating the FAQ \\u2014 one specialist…"'. A bubble must show the sentence, not the
    quotes and escapes."""
    encoded = '"Delegating the FAQ \\u2014 one specialist should own it."'
    spans = [
        span("a", "", "AGENT", "turn", 0, 900, agent="team"),
        dict(span("t", "a", "THINKING", "thinking", 10, 200, agent="sup"), output=encoded),
        dict(span("d", "a", "DELEGATE", "faq", 300, 400, agent="sup"),
             input='"Return policy \\u2014 window and condition?"'),
        span("f", "d", "GENERATION", "gpt", 320, 100, agent="faq"),
    ]
    r = build_replay(spans, aliases={"faq": "faq"})
    by = {e["name"]: e for e in r["events"]}
    assert by["thinking"]["detail"] == "Delegating the FAQ — one specialist should own it."
    assert by["faq"]["say"] == "Return policy — window and condition?"


def test_detail_names_the_tool_when_the_model_answered_with_a_call():
    # A model turn whose answer IS a tool call exports no sayable output — the office bubble
    # came up empty. `tool_call_names` is indexed on the span; say what it reached for.
    r = build_replay(
        [span("b", "", "GENERATION", "chat gpt-4o", 0, agent="support", tool_call_names=["get_order"])]
    )
    assert r["events"][0]["detail"] == "→ get_order"


def test_spoken_output_still_wins_over_the_tool_names():
    r = build_replay(
        [
            span(
                "b", "", "GENERATION", "chat", 0, agent="support",
                output=json.dumps([{"role": "assistant", "content": "on it"}]),
                tool_call_names=["get_order"],
            )
        ]
    )
    assert r["events"][0]["detail"] == "on it"
