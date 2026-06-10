"""Shape of an evaluator's return value + the trace context it's given.

`EvalResult` is the raw output of a single check — many checks emit one result, but
`ToolSuccessEvaluator` emits one per TOOL span and SPAN-level judges emit one per step.

`RunContext` is the bundle the runner hands every evaluator: trace identifiers, all spans,
and the root span pre-computed (so each evaluator doesn't re-derive it). For CONVERSATION-level
evaluation `spans` holds EVERY span across the thread (each row carries its `trace_id`) and
`thread_id` is set; trace-scoped fields are left blank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    name: str
    level: str
    verdict: str  # PASS | FAIL | "" (neutral — informational scores carry no verdict)
    data_type: str = "BOOLEAN"
    value: float | None = None
    string_value: str = ""  # CATEGORICAL / TEXT / JSON payloads
    target_span_id: str = ""
    comment: str = ""


@dataclass
class RunContext:
    project_id: str
    trace_id: str
    agent_run_id: str
    spans: list[dict[str, Any]]
    root: dict[str, Any] = field(default_factory=dict)
    # Set for CONVERSATION-level evaluation: the thread being graded (spans then covers the
    # whole thread, ordered by start_time, each span dict carrying its own trace_id).
    thread_id: str = ""
