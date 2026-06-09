"""OpenAI — automatic tracing of a real tool-calling agent (PRD 12, P0).

A support agent answers a multi-part question by calling fake-DB tools (`get_order_status`,
`check_inventory`) in an agentic loop, then summarizing. Every model call is captured automatically
as a GENERATION span by the OpenAI instrumentor — **no span code on the LLM calls**. One
`@observe(as_type="agent")` on the loop gives the run a single AGENT root so the generations + tool
spans land in one trace tree (instead of each chat.completions.create() becoming its own trace);
`tracely.trace(...)` attaches the run's agent/conversation/user metadata onto every span inside.

    pip install "tracely-sdk[openai]"
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openai.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM, observed_tools

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


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
    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        messages: list = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
        for _ in range(5):  # agentic loop: call tools until the model gives a final answer
            resp = client.chat.completions.create(
                model="gpt-5.4-mini", messages=messages, tools=OPENAI_TOOLS
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return msg.content or ""
            for call in msg.tool_calls:  # dispatch as usual — the decorator makes each a TOOL span
                args = json.loads(call.function.arguments)
                result = tools[call.function.name](**args)
                print(f"  tool {call.function.name}{args} -> {result}")
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )
        return "(loop limit hit)"

    with tracely.trace(
        agent="support-agent",
        conversation=os.path.basename(__file__),
        user="ada@example.com",
        example=os.path.basename(__file__),
    ):
        print("agent:", support_agent(QUESTION))

    tracely.flush()
    print(
        "sent — open Tracely → Traces: each generation + tool round-trip is captured, no span code."
    )


if __name__ == "__main__":
    main()
