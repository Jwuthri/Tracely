"""The ClickHouse `events` row: one row per span (Langfuse events_full + Tracely columns,
minus the dropped prompt_*/experiment_* blocks). Column list here is the single source of
truth for inserts; the 0001_events.up.sql migration matches it. See design 03 + 09.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

EVENT_COLUMNS: list[str] = [
    "project_id", "trace_id", "span_id", "parent_span_id",
    "start_time", "end_time", "completion_start_time",
    "name", "type", "environment", "env", "version", "release", "level",
    "status_message", "is_app_root",
    "trace_name", "user_id", "session_id", "tags",
    "agent_id", "agent_version_id", "agent_run_id", "conversation_id",
    "turn_id", "turn_index", "step_id", "step_name",
    "tool_call_id", "caller_agent_id", "callee_agent_id", "edge_type",
    "evaluation_case_id", "gate_run_id", "failure_cluster_id",
    "model_id", "model_parameters", "usage_details", "cost_details",
    "tool_definitions", "tool_calls", "tool_call_names",
    "input", "output", "metadata",
    "source", "service_name", "scope_name",
    "telemetry_sdk_language", "telemetry_sdk_name", "telemetry_sdk_version",
    "event_ts", "is_deleted", "created_at",
]

_NULLABLE = {"end_time", "completion_start_time", "input", "output"}
_MAPS = {"usage_details", "cost_details", "tool_definitions", "metadata"}
_ARRAYS = {"tags", "tool_calls", "tool_call_names"}
_INTS = {"turn_index", "is_deleted"}
_BOOLS = {"is_app_root"}


def _default(col: str) -> Any:
    if col in _NULLABLE:
        return None
    if col in _MAPS:
        return {}
    if col in _ARRAYS:
        return []
    if col in _INTS:
        return 0
    if col in _BOOLS:
        return False
    return ""


def to_rows(events: list[dict[str, Any]]) -> list[list[Any]]:
    """Build column-aligned rows from loosely-typed event dicts, filling defaults + timestamps."""
    now = datetime.now(timezone.utc)
    rows: list[list[Any]] = []
    for ev in events:
        ev.setdefault("event_ts", now)
        ev.setdefault("created_at", now)
        rows.append([ev.get(col, _default(col)) if ev.get(col) is not None else _default(col)
                     for col in EVENT_COLUMNS])
    return rows
