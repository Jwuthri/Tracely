"""Shape of an evaluator's return value + the trace context it's given.

`EvalResult` is the raw output of a single check — many checks emit one result, but
`ToolSuccessEvaluator` emits one per TOOL span.

`RunContext` is the bundle the runner hands every evaluator: trace identifiers, all spans,
and the root span pre-computed (so each evaluator doesn't re-derive it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    name: str
    level: str
    verdict: str  # PASS | FAIL
    data_type: str = "BOOLEAN"
    value: float | None = None
    target_span_id: str = ""
    comment: str = ""


@dataclass
class RunContext:
    project_id: str
    trace_id: str
    agent_run_id: str
    spans: list[dict[str, Any]]
    root: dict[str, Any] = field(default_factory=dict)
