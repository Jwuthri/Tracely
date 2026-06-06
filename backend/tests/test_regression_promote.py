"""Silent-failure regression promotion — required-tools derivation (no infra).

A "silent failure" is a run where the model REQUESTED a tool (tool_call_names) but the agent never
EXECUTED it (no TOOL span). `promote_trace` must still build a meaningful case: the required-tools
set has to include that requested-but-not-executed tool, so the source FAILs (fail-to-pass) and a
fix that actually calls the tool PASSes. These tests drive the pure trajectory logic that backs it
(no Postgres / ClickHouse / S3).
"""

from __future__ import annotations

from tracely.trajectory import (
    build_trajectory,
    required_tools,
    requested_tools,
    tool_sequence,
    tools_satisfied,
)


def _span(span_id: str, type_: str, name: str, *, parent: str = "", level: str = "DEFAULT",
          tool_calls: list[str] | None = None) -> dict:
    return {
        "trace_id": "trace-1", "span_id": span_id, "parent_span_id": parent,
        "type": type_, "name": name, "level": level, "agent_run_id": "run-1",
        "is_app_root": parent == "", "tool_call_names": tool_calls or [], "output": None,
    }


def _silent() -> list[dict]:
    """Model asks for get_weather, but it's never executed (no TOOL span) — the silent failure."""
    return [
        _span("a", "AGENT", "planner"),
        _span("g", "GENERATION", "gpt-4o", parent="a", tool_calls=["get_weather"]),
    ]


def _fixed() -> list[dict]:
    """The fix: the agent actually executes get_weather."""
    return [
        _span("a", "AGENT", "planner"),
        _span("g", "GENERATION", "gpt-4o", parent="a", tool_calls=["get_weather"]),
        _span("t", "TOOL", "get_weather", parent="a"),
    ]


def test_silent_failure_requires_the_unexecuted_tool():
    traj = build_trajectory(_silent())
    assert tool_sequence(traj) == []                 # nothing actually ran
    assert requested_tools(traj) == ["get_weather"]  # but the model asked for it
    assert required_tools(traj) == ["get_weather"]   # so the case requires it


def test_fixed_run_executes_the_required_tool():
    traj = build_trajectory(_fixed())
    assert tool_sequence(traj) == ["get_weather"]
    assert required_tools(traj) == ["get_weather"]


def test_fail_to_pass_contract_holds_under_superset():
    required = required_tools(build_trajectory(_silent()))  # ["get_weather"]
    # the source (silent) executed nothing -> FAILs the case
    ok, missing, _ = tools_satisfied("superset", produced=[], reference=required)
    assert not ok and missing == ["get_weather"]
    # a fix that calls the tool -> PASSes
    ok, missing, _ = tools_satisfied("superset", produced=["get_weather"], reference=required)
    assert ok and missing == []


def test_executed_tools_without_requests_are_unchanged():
    # backward-compat: a normal run (executed == requested) keeps required == executed
    spans = [_span("a", "AGENT", "planner"), _span("t", "TOOL", "search", parent="a")]
    traj = build_trajectory(spans)
    assert required_tools(traj) == ["search"]


def test_required_tools_dedupes_and_preserves_order():
    spans = [
        _span("a", "AGENT", "planner"),
        _span("g", "GENERATION", "gpt-4o", parent="a", tool_calls=["search", "get_weather"]),
        _span("t", "TOOL", "search", parent="a"),  # executed one of the two requested
    ]
    traj = build_trajectory(spans)
    # executed (search) first, then the requested-but-not-executed (get_weather); no dupes
    assert required_tools(traj) == ["search", "get_weather"]
