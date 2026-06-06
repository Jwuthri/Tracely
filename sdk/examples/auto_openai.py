"""OpenAI — automatic tracing of a real tool-calling agent (PRD 12, P0).

A support agent answers a multi-part question by calling fake-DB tools (`get_order_status`,
`check_inventory`) in an agentic loop, then summarizing. Every model call and tool round-trip is
captured automatically as a GENERATION span — **no span code**. `tracely.trace(...)` attaches the
run's agent/conversation/user to all of them.

    pip install "tracely-sdk[openai]"
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openai.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM, run_tool

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["openai"]
)


def main() -> None:
    if "openai" not in tracely._instrumented:
        print('OpenAI instrumentation not active — pip install "tracely-sdk[openai]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call (the span shape is identical either way).")
        return

    from openai import OpenAI

    client = OpenAI()
    messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]

    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        for _ in range(5):  # agentic loop: call tools until the model gives a final answer
            resp = client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, tools=OPENAI_TOOLS
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                print("agent:", msg.content)
                break
            for call in msg.tool_calls:  # run each requested tool against the fake DB
                result = run_tool(call.function.name, json.loads(call.function.arguments))
                print(
                    f"  tool {call.function.name}{json.loads(call.function.arguments)} -> {result}"
                )
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )

    tracely.flush()
    print(
        "sent — open Tracely → Traces: each generation + tool round-trip is captured, no span code."
    )


if __name__ == "__main__":
    main()
