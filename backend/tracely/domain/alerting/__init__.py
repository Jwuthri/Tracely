"""Alert rule flows: the pure half — DAG resolution over the canvas's own edge list, the variable
namespace every step template renders against, and each step type's declared output.

The engine (Jinja rendering, HTTP/email/LLM side effects, execution rows) lives in
`services/alert_flow_service.py`; nothing here does I/O.
"""

from tracely.domain.alerting.context import (
    BASE_INPUTS,
    build_context,
    catalog_for_trigger,
    declared_outputs,
)
from tracely.domain.alerting.flow import (
    CYCLE_ERROR,
    TRIGGER_NODE_ID,
    ancestor_step_ids,
    flow_layout_error,
    linear_flow_layout,
    ordered_steps,
)

__all__ = [
    "BASE_INPUTS",
    "CYCLE_ERROR",
    "TRIGGER_NODE_ID",
    "ancestor_step_ids",
    "build_context",
    "catalog_for_trigger",
    "declared_outputs",
    "flow_layout_error",
    "linear_flow_layout",
    "ordered_steps",
]
