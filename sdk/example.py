"""Emit the demo agent trace via the Tracely SDK.

    uv run python sdk/example.py     (API + worker must be running)
"""

import tracely_sdk as tracely

tracely.init(endpoint="http://localhost:8000", api_key="tracely_dev_key", service_name="demo-agent")

with tracely.agent("planner", version="v1"):
    with tracely.llm("gpt-4o") as g:
        tracely.set_io(
            g,
            input=[
                {"role": "system", "content": "You are a helpful weather assistant."},
                {"role": "user",   "content": "weather in SF?"},
            ],
            output={
                "role": "assistant",
                "content": None,
                "finish_reason": "tool_calls",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
                }],
            },
        )
        tracely.set_usage(g, input_tokens=812, output_tokens=96)
    with tracely.tool("get_weather") as t:
        tracely.set_io(t, input={"city": "SF"})
        tracely.error(t, "upstream timeout")  # demo failure signal (level=ERROR)

tracely.flush()
print("sent demo trace via SDK")
