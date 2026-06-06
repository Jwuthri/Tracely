"""LiteLLM — automatic tracing of a real tool-calling agent across 100+ providers (PRD 12, R12).

`init(instrument=["litellm"])` wires `litellm.callbacks=["otel"]`, so every `litellm.completion()`
(to any provider) — including the tool round-trips — exports through Tracely as a GENERATION span.
LiteLLM normalizes everything to the OpenAI shape, so the loop matches `auto_openai.py`.

    pip install "tracely-sdk[litellm]"
    export OPENAI_API_KEY=sk-...        # or any provider key LiteLLM routes to (change the model)
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_litellm.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM, run_tool

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["litellm"]
)


def main() -> None:
    if "litellm" not in tracely._instrumented:
        print('LiteLLM not active — pip install "tracely-sdk[litellm]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY (or change the model to another provider LiteLLM routes to).")
        return

    import litellm

    messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]
    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        for _ in range(5):
            resp = litellm.completion(model="gpt-4o-mini", messages=messages, tools=OPENAI_TOOLS)
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                print("agent:", msg.content)
                break
            for call in msg.tool_calls:
                result = run_tool(call.function.name, json.loads(call.function.arguments))
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )

    tracely.flush()
    print("sent — open Tracely → Traces: the tool-calling loop, traced via one LiteLLM callback.")


if __name__ == "__main__":
    main()
