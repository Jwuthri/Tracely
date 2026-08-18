"""Keep SDK tests capable of producing their in-memory spans — and only those.

The tests install their own in-memory exporters and assert on completed OpenTelemetry spans.
`OTEL_SDK_DISABLED=true` makes the SDK a no-op, which means every tracing test necessarily sees
an empty exporter.
"""

from __future__ import annotations

import os

from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

import tracely_sdk

# Assigned rather than setdefault: a shell that disables OTel would otherwise make the suite
# falsely exercise only non-recording spans.
os.environ["OTEL_SDK_DISABLED"] = "false"


class _NullExporter(SpanExporter):
    """Swallows exported batches instead of POSTing them anywhere."""

    def export(self, spans):  # noqa: ARG002
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: ARG002
        return True


# Every test module calls `init()`, whose defaults are endpoint=localhost:8000 + the seeded dev key
# — and BatchSpanProcessor flushes on its own 5s timer and again at interpreter exit. So on any
# machine running the stack, the suite really did ship its spans into that workspace: `planner`,
# `weather-agent`, `cust-1` and friends showed up as REGISTERED AGENTS in a developer's real
# project, one per fixture name. (The old comment here claimed the opposite.) Point at a dead
# endpoint instead and the exporter retries noisily for 30s at shutdown, so swap the class itself.
tracely_sdk.OTLPSpanExporter = lambda **_: _NullExporter()
