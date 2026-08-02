"""Keep SDK tests capable of producing their in-memory spans.

The tests install their own in-memory exporters and assert on completed OpenTelemetry spans.
`OTEL_SDK_DISABLED=true` makes the SDK a no-op, which means every tracing test necessarily sees
an empty exporter. The batch OTLP processor is not flushed by these tests, so no test span is sent
to a developer's running Tracely stack during the test process.
"""

from __future__ import annotations

import os

# Assigned rather than setdefault: a shell that disables OTel would otherwise make the suite
# falsely exercise only non-recording spans.
os.environ["OTEL_SDK_DISABLED"] = "false"
