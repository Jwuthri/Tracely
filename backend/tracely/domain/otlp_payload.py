"""Shared builders for the OTLP/JSON payloads Tracely emits about itself.

Two features write traces rather than only reading them — emulated conversations
(`domain/simulation/emit.py`) and internal-run recording (`domain/introspection.py`) — and both
hit the same trap, so the encoding lives here once.

**IDs are base64, never hex.** `parse_otlp_traces_json` runs protobuf's `json_format.Parse`, whose
canonical mapping decodes `bytes` fields as *base64*. Handing it hex does NOT raise: protobuf
base64-decodes the hex text into 24 bytes of garbage and the span lands under a trace id nothing
can look up. Pinned by `test_simulation.py::test_turn_payload_ids_survive_the_json_parser`.
"""

from __future__ import annotations

import base64
from typing import Any


def attr(key: str, value: Any) -> dict:
    """One OTLP KeyValue. bool is checked before int — `bool` is an `int` subclass, and an
    `intValue` of 1 would lose the boolean-ness `_truthy` looks for."""
    if isinstance(value, bool):
        inner: dict = {"boolValue": value}
    elif isinstance(value, int):
        inner = {"intValue": str(value)}
    else:
        inner = {"stringValue": str(value)}
    return {"key": key, "value": inner}


def span(
    *,
    trace_id: bytes,
    span_id: bytes,
    name: str,
    start_ns: int,
    end_ns: int,
    attributes: list[dict],
    parent_span_id: bytes | None = None,
    error: str = "",
) -> dict:
    """One OTLP span. `error` sets STATUS_CODE_ERROR (2), which the mapper reads as level=ERROR."""
    out: dict[str, Any] = {
        "traceId": base64.b64encode(trace_id).decode(),
        "spanId": base64.b64encode(span_id).decode(),
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attributes,
    }
    if parent_span_id:
        out["parentSpanId"] = base64.b64encode(parent_span_id).decode()
    if error:
        out["status"] = {"code": 2, "message": error[:500]}
    return out


def request(spans: list[dict], scope_name: str) -> dict:
    """Wrap spans in an ExportTraceServiceRequest."""
    return {
        "resourceSpans": [{
            "resource": {"attributes": [attr("service.name", "tracely")]},
            "scopeSpans": [{"scope": {"name": scope_name}, "spans": spans}],
        }]
    }
