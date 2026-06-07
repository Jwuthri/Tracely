"""Seed a production trace where a tool errors AND the agent crashes (mishandles it) — the
canonical 'error-handling regression'. Promoting it mints a case with allow_tool_errors=True, so
a graceful fix (run_handles) can go GREEN while the crashing agent (run_crashes) FAILs.

    TRACELY_API=http://localhost:8088 uv run python sdk/examples/seed_handler.py
"""

from __future__ import annotations

import os

import tracely_sdk as tracely

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(endpoint=API, api_key=KEY, service_name="handler", env="prod")

with tracely.trace(example=os.path.basename(__file__)), tracely.agent("handler") as a:
    tracely.set_io(a, input="what's the weather in SF?", output="<crashed: unhandled tool error>")
    with tracely.llm("gpt-4o") as g:
        tracely.set_io(g, input="what's the weather in SF?", output="(calls get_weather)")
    with tracely.tool("get_weather") as s:
        tracely.set_io(s, output='{"tempF": 64}')
        tracely.error(s, "upstream timeout")  # the tool failed...
    tracely.error(a, "unhandled tool error: upstream timeout")  # ...and the agent crashed
    trace_id = format(a.get_span_context().trace_id, "032x")

tracely.flush()
print("trace_id:", trace_id)
