"""Seed a production trace that calls get_weather twice, where the SECOND call errors — to
demo faithful (args-keyed, error-preserving) fixtures.

    TRACELY_API=http://localhost:8088 uv run python sdk/examples/seed_multicall.py

Prints the trace id. Promote it (POST /api/traces/<id>/promote) to mint a regression case whose
fixture bundle records both calls in order WITH the 2nd call's error.
"""

from __future__ import annotations

import os
import time

import tracely_sdk as tracely

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(endpoint=API, api_key=KEY, service_name="multiweather", env="prod")

with tracely.trace(example=os.path.basename(__file__)), tracely.agent("multiweather") as a:
    # message-level I/O as structured message objects (role + typed content blocks)
    tracely.set_io(
        a,
        input={"role": "user", "content": [{"type": "text", "text": "weather in SF and NYC?"}]},
        output={
            "role": "assistant",
            "content": [{"type": "text", "text": "Sorry, the NYC lookup failed."}],
        },
    )
    with tracely.llm("gpt-4o") as g:
        tracely.set_io(
            g,
            input=[
                {"role": "system", "content": "You are a helpful weather assistant."},
                {"role": "user", "content": "weather in SF and NYC?"},
            ],
            output={
                "role": "assistant",
                "content": None,
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"SF"}'},
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "get_weather", "arguments": '{"city":"NYC"}'},
                    },
                ],
            },
        )
        tracely.set_usage(g, input_tokens=320, output_tokens=48)
        time.sleep(0.35)
    with tracely.tool("get_weather") as s1:
        tracely.set_io(s1, input={"city": "SF"}, output={"tempF": 64})
        time.sleep(0.12)
    with tracely.tool("get_weather") as s2:
        tracely.set_io(s2, input={"city": "NYC"}, output={"tempF": 50})
        tracely.error(s2, "upstream timeout")  # the 2nd tool call errored in production
        time.sleep(0.18)
    trace_id = format(a.get_span_context().trace_id, "032x")

tracely.flush()
print("trace_id:", trace_id)
