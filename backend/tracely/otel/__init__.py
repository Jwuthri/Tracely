"""OTLP → Tracely event row mapping. Re-exports the parser entry points so consumers can
`from tracely.otel import parse_otlp_traces`."""

from tracely.otel.parser import (
    events_from_request,
    parse_otlp_traces,
    parse_otlp_traces_json,
)

__all__ = ["events_from_request", "parse_otlp_traces", "parse_otlp_traces_json"]
