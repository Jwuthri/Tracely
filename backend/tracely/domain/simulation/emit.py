"""Build the OTLP/JSON payload for one emulated conversation turn.

Pure dict-building; the service does the HTTP call and hands the bytes to `ingest_otlp`, so an
emulated turn walks the exact same blob → Celery → ClickHouse → auto-eval path as production
traffic. That reuse is the point: emulated traces are graded by the customer's own evaluators,
with no parallel scoring path to keep in sync.

**The ID encoding is a trap.** `parse_otlp_traces_json` runs protobuf's `json_format.Parse`,
whose canonical mapping decodes `bytes` fields as *base64* — not the hex that OTLP/JSON normally
carries. Handing it hex does NOT raise: protobuf base64-decodes the hex text into 24 bytes of
garbage and the turn lands under a trace id nothing can look up. Always base64 (see
`test_simulation.py::test_turn_payload_ids_survive_the_json_parser`).
"""

from __future__ import annotations

import base64
from typing import Any


def _attr(key: str, value: Any) -> dict:
    """One OTLP KeyValue. bool is checked before int — `bool` is an `int` subclass, and an
    `intValue` of 1 would lose the boolean-ness `_truthy` looks for."""
    if isinstance(value, bool):
        inner: dict = {"boolValue": value}
    elif isinstance(value, int):
        inner = {"intValue": str(value)}
    else:
        inner = {"stringValue": str(value)}
    return {"key": key, "value": inner}


def turn_payload(
    *,
    trace_id: bytes,
    span_id: bytes,
    agent_slug: str,
    conversation_id: str,
    turn_index: int,
    user_message: str,
    agent_reply: str,
    env: str,
    start_ns: int,
    end_ns: int,
    scenario_title: str = "",
    error: str = "",
) -> dict:
    """One emulated turn as an ExportTraceServiceRequest (JSON form).

    The span is a root AGENT observation carrying the simulated user's message as input and the
    endpoint's reply as output. When the customer's own service is OTel-instrumented and honours
    the `traceparent` we send, its internal spans arrive separately under this same `trace_id`
    and nest underneath — so the graded trace contains the agent's real tool calls, not just the
    text it returned.
    """
    attrs = [
        _attr("tracely.observation.type", "AGENT"),
        _attr("tracely.env", env),
        _attr("tracely.agent.id", agent_slug),
        _attr("tracely.conversation.id", conversation_id),
        _attr("tracely.turn.id", f"{conversation_id}:{turn_index}"),
        _attr("tracely.turn.index", turn_index),
        _attr("tracely.is_app_root", True),
        _attr("tracely.input", user_message),
        _attr("tracely.output", agent_reply),
    ]
    if scenario_title:
        attrs.append(_attr("tracely.trace.name", scenario_title))

    span: dict[str, Any] = {
        "traceId": base64.b64encode(trace_id).decode(),
        "spanId": base64.b64encode(span_id).decode(),
        "name": "emulated.turn",
        "kind": 3,  # CLIENT — Tracely is calling the customer's endpoint
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attrs,
    }
    if error:
        # code 2 = ERROR; span_mapper turns this into level=ERROR + status_message, which is what
        # the no_error assertions and the failure-clustering pipeline key off.
        span["status"] = {"code": 2, "message": error[:500]}

    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr("service.name", agent_slug or "tracely-sim")]},
                "scopeSpans": [
                    {"scope": {"name": "tracely.simulation"}, "spans": [span]},
                ],
            }
        ]
    }
