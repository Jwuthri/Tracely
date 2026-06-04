"""Standalone agent for `tracely replay --cmd`.

For agents that aren't a Python function (another language, a subprocess, a service call), the
`--cmd` path runs your command once per promoted case with the case input in `TRACELY_INPUT`.
Your command emits its own complete env-tagged trace; the gate then matches it to the case by
input digest, so structure the trace like production (here: input on the llm span, tool span
present). This mirrors weather_agent:run (the fixed agent).

    tracely replay planner --cmd "python sdk/examples/weather_agent_cli.py" --env ci
"""

from __future__ import annotations

import os

import tracely_sdk as tracely

tracely.init(
    endpoint=os.environ.get("TRACELY_API", "http://localhost:8000"),
    api_key=os.environ.get("TRACELY_KEY", "tracely_dev_key"),
    service_name="planner",
    env=os.environ.get("TRACELY_ENV", "ci"),
)

prompt = os.environ.get("TRACELY_INPUT", "")
with tracely.agent("planner"):
    with tracely.llm("gpt-4o") as g:
        tracely.set_io(g, input=prompt, output="(decides to call get_weather)")
    with tracely.tool("get_weather") as t:
        tracely.set_io(t, output='{"tempF": 64}')
tracely.flush()
