"""Send a sample multi-span OTLP trace (agent -> llm -> failing tool) to the running API.

    uv run python scripts/send_test_trace.py
"""

from __future__ import annotations

import os
import time
import urllib.request

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import (
    AnyValue,
    ArrayValue,
    InstrumentationScope,
    KeyValue,
)
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


def kv_arr(k: str, items) -> KeyValue:
    return KeyValue(
        key=k,
        value=AnyValue(array_value=ArrayValue(values=[AnyValue(string_value=str(x)) for x in items])),
    )


def main() -> None:
    # Four demo runs of the same agent/input:
    #   default       -> get_weather ERRORS              (explicit failure)
    #   FIXED=1       -> get_weather SUCCEEDS            (the fix; gate PASS)
    #   SILENT=1      -> model requests get_weather but it NEVER runs  (SILENT failure:
    #                    no error span, but the requested tool was not executed)
    #   HALLUCINATE=1 -> get_weather SUCCEEDS but the model fabricates a wrong, self-
    #                    contradictory answer (quality failure caught by the LLM judge,
    #                    not by any structural check)
    fixed = os.environ.get("FIXED", "") not in ("", "0", "false")
    silent = os.environ.get("SILENT", "") not in ("", "0", "false")
    hallucinate = os.environ.get("HALLUCINATE", "") not in ("", "0", "false")
    env = os.environ.get("ENV", "")  # e.g. "ci" for a CI run; empty -> prod

    # Deterministic base time so re-sending dedups; distinct trace id per variant/env.
    base = 0xFACADE if hallucinate else 0x511EE7 if silent else 0xF0FFEE if fixed else 0xC0FFEE
    now = 1_717_400_000_000_000_000 + (
        3_000_000_000 if hallucinate else 1_000_000_000 if fixed else 2_000_000_000
    )
    if os.environ.get("RANDOM", "") not in ("", "0", "false"):
        import secrets

        trace_id = secrets.token_bytes(16)  # a distinct failing run (for cluster demos)
    else:
        trace_id = (base + (0x010000 if env == "ci" else 0)).to_bytes(16, "big")
    root_id, llm_id, tool_id = (1).to_bytes(8, "big"), (2).to_bytes(8, "big"), (3).to_bytes(8, "big")

    if hallucinate:
        # tool succeeds, but the model confidently fabricates an absurd, contradictory answer
        answer = (
            "It's 9000°F and snowing heavily in San Francisco right now, "
            "and the midnight sun is blazing over the bay."
        )
    elif fixed or silent:
        answer = "It's 64°F and sunny in San Francisco."
    else:
        answer = "Sorry, I couldn't fetch the weather right now."

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
                           kv("tracely.agent.id", "planner"),
                           kv("tracely.input", "what's the weather in SF?"),
                           kv("tracely.output", answer),
                           kv_arr("tracely.tool_calls", ["get_weather"])])  # model REQUESTS the tool

    spans = [root, llm]
    if not silent:
        tool = Span(name="get_weather", trace_id=trace_id, span_id=tool_id, parent_span_id=root_id,
                    start_time_unix_nano=now + 3_500_000, end_time_unix_nano=now + 4_000_000)
        if not fixed and not hallucinate:
            tool.status.code = 2  # ERROR
            tool.status.message = "upstream timeout"
        tool.attributes.extend([kv("gen_ai.operation.name", "execute_tool"),
                                kv("gen_ai.tool.name", "get_weather"),
                                kv("tracely.agent.id", "planner"),
                                kv("tracely.output", '{"tempF": 64}')])
        spans.append(tool)

    if env:
        for sp in spans:
            sp.attributes.append(kv("tracely.env", env))

    req = ExportTraceServiceRequest(resource_spans=[
        ResourceSpans(
            resource=Resource(attributes=[kv("service.name", "demo"),
                                          kv("telemetry.sdk.language", "python")]),
            scope_spans=[ScopeSpans(scope=InstrumentationScope(name="demo"), spans=spans)],
        )
    ])

    body = req.SerializeToString()
    request = urllib.request.Request(
        f"{API}/v1/traces", data=body,
        headers={"Content-Type": "application/x-protobuf", "Authorization": f"Bearer {KEY}"},
    )
    resp = urllib.request.urlopen(request)
    kind = (
        "hallucinated-answer" if hallucinate
        else "silent-failure" if silent
        else "fixed" if fixed
        else "failing"
    )
    suffix = f", env={env}" if env else ""
    print(f"POST /v1/traces -> {resp.status}  ({kind}{suffix})")
    print(f"trace_id (hex): {trace_id.hex()}")


if __name__ == "__main__":
    main()
