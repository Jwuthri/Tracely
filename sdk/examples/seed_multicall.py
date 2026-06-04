"""Seed a production trace that calls get_weather twice, where the SECOND call errors — to
demo faithful (args-keyed, error-preserving) fixtures.

    TRACELY_API=http://localhost:8088 uv run python sdk/examples/seed_multicall.py

Prints the trace id. Promote it (POST /api/traces/<id>/promote) to mint a regression case whose
fixture bundle records both calls in order WITH the 2nd call's error.
"""

from __future__ import annotations

import os

import tracely_sdk as tracely

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(endpoint=API, api_key=KEY, service_name="multiweather", env="prod")

with tracely.agent("multiweather") as a:
    tracely.set_io(a, input="weather in SF and NYC?", output="Sorry, the NYC lookup failed.")
    with tracely.llm("gpt-4o") as g:
        tracely.set_io(g, input="weather in SF and NYC?", output="(calls get_weather twice)")
    with tracely.tool("get_weather") as s1:
        tracely.set_io(s1, input='{"city":"SF"}', output='{"tempF": 64}')
    with tracely.tool("get_weather") as s2:
        tracely.set_io(s2, input='{"city":"NYC"}', output='{"tempF": 50}')
        tracely.error(s2, "upstream timeout")  # the 2nd tool call errored in production
    trace_id = format(a.get_span_context().trace_id, "032x")

tracely.flush()
print("trace_id:", trace_id)
