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

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
        for _ in range(5):
            resp = litellm.completion(model="gpt-5.4-mini", messages=messages, tools=OPENAI_TOOLS)
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return msg.content or ""
            for call in msg.tool_calls:
                result = run_tool(call.function.name, json.loads(call.function.arguments))
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )
        return "(loop limit hit)"

    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        print("agent:", support_agent(QUESTION))

    tracely.flush()
    print("sent — open Tracely → Traces: the tool-calling loop, traced via one LiteLLM callback.")


if __name__ == "__main__":
    main()
