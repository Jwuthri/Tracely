"""Send a sample multi-span OTLP trace (agent -> llm -> failing tool) to the running API.

    uv run python scripts/send_test_trace.py
"""

from __future__ import annotations

import os
import time
import urllib.request

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, InstrumentationScope, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")


def kv(k: str, v) -> KeyValue:
    if isinstance(v, bool):
        return KeyValue(key=k, value=AnyValue(bool_value=v))
    if isinstance(v, int):
        return KeyValue(key=k, value=AnyValue(int_value=v))
    return KeyValue(key=k, value=AnyValue(string_value=str(v)))


def main() -> None:
    # FIXED=1 -> the "fixed" run: same agent/input, but get_weather SUCCEEDS (no error).
    # Use it to demo a regression case replaying PASS after the failure is fixed.
    fixed = os.environ.get("FIXED", "") not in ("", "0", "false")
    # Deterministic base time so re-sending the same demo trace dedups in ClickHouse
    # (ReplacingMergeTree's sort key includes start_time). Real spans are emitted once.
    now = 1_717_400_000_000_000_000 + (1_000_000_000 if fixed else 0)
    trace_id = (0xF0FFEE if fixed else 0xC0FFEE).to_bytes(16, "big")
    root_id, llm_id, tool_id = (1).to_bytes(8, "big"), (2).to_bytes(8, "big"), (3).to_bytes(8, "big")

    root = Span(name="planner", trace_id=trace_id, span_id=root_id,
                start_time_unix_nano=now, end_time_unix_nano=now + 5_000_000)
    root.attributes.extend([kv("tracely.agent.id", "planner"),
                            kv("tracely.observation.type", "AGENT"),
                            kv("session.id", "sess-1")])

    llm = Span(name="gpt-4o", trace_id=trace_id, span_id=llm_id, parent_span_id=root_id,
               start_time_unix_nano=now + 1_000_000, end_time_unix_nano=now + 3_000_000)
    llm.attributes.extend([kv("gen_ai.operation.name", "chat"),
                           kv("gen_ai.request.model", "gpt-4o"),
                           kv("gen_ai.usage.input_tokens", 812),
                           kv("gen_ai.usage.output_tokens", 96),
                           kv("tracely.agent.id", "planner")])

    tool = Span(name="get_weather", trace_id=trace_id, span_id=tool_id, parent_span_id=root_id,
                start_time_unix_nano=now + 3_500_000, end_time_unix_nano=now + 4_000_000)
    if not fixed:
        tool.status.code = 2  # ERROR — the demo "failure" signal
        tool.status.message = "upstream timeout"
    tool.attributes.extend([kv("gen_ai.operation.name", "execute_tool"),
                            kv("gen_ai.tool.name", "get_weather"),
                            kv("tracely.agent.id", "planner")])

    req = ExportTraceServiceRequest(resource_spans=[
        ResourceSpans(
            resource=Resource(attributes=[kv("service.name", "demo"),
                                          kv("telemetry.sdk.language", "python")]),
            scope_spans=[ScopeSpans(scope=InstrumentationScope(name="demo"),
                                    spans=[root, llm, tool])],
        )
    ])

    body = req.SerializeToString()
    request = urllib.request.Request(
        f"{API}/v1/traces", data=body,
        headers={"Content-Type": "application/x-protobuf", "Authorization": f"Bearer {KEY}"},
    )
    resp = urllib.request.urlopen(request)
    print(f"POST /v1/traces -> {resp.status}")
    print(f"trace_id (hex): {trace_id.hex()}")
    print(f"Read it:  curl -s -H 'Authorization: Bearer {KEY}' {API}/api/traces/{trace_id.hex()}")


if __name__ == "__main__":
    main()
