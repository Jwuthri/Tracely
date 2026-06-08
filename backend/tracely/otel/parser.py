"""Top-level OTLP entry points: protobuf + JSON parsers + the request → events orchestrator."""

from __future__ import annotations

from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from tracely.otel.attributes import _attrs
from tracely.otel.span_mapper import _map_span
from tracely.otel.tool_enrichment import _enrich_tool_io


def events_from_request(
    req: ExportTraceServiceRequest, project_id: str
) -> list[dict[str, Any]]:
    """Walk every resource span, scope span, and span in the request → list of event dicts."""
    events: list[dict[str, Any]] = []
    for rs in req.resource_spans:
        resource_attrs = _attrs(list(rs.resource.attributes))
        for ss in rs.scope_spans:
            scope_name = ss.scope.name if ss.scope else ""
            scope_version = ss.scope.version if ss.scope else ""
            # OTLP schema_url = the semantic-convention version (D4). Prefer scope-level (the
            # instrumentor's semconv), fall back to the resource's.
            schema_url = ss.schema_url or rs.schema_url
            for span in ss.spans:
                events.append(_map_span(
                    resource_attrs, scope_name, scope_version, span, project_id, schema_url,
                ))
    _enrich_tool_io(events)
    return events


def parse_otlp_traces(raw: bytes, project_id: str) -> list[dict[str, Any]]:
    """Parse an OTLP/protobuf ExportTraceServiceRequest into Tracely event dicts."""
    req = ExportTraceServiceRequest()
    req.ParseFromString(raw)
    return events_from_request(req, project_id)


def parse_otlp_traces_json(raw: bytes, project_id: str) -> list[dict[str, Any]]:
    """Parse OTLP/JSON into Tracely event dicts."""
    from google.protobuf import json_format

    req = ExportTraceServiceRequest()
    json_format.Parse(raw.decode("utf-8"), req)
    return events_from_request(req, project_id)
