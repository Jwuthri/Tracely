"""Automatic tracing — a full `@observe` agent: thinking → tools → answer (PRD 12, P1).

`@observe` turns functions into spans (args→input, return→output, latency, errors), auto-nested via
OTel context. The OpenAI calls inside are captured by the auto-instrumentor. One enclosing
`tracely.trace(...)` flows the run's agent/conversation onto every span.

Produces a real agent tree:
    support-agent (AGENT)
      ├─ plan (THINKING)
      ├─ chat.completions (GENERATION)   ← model requests the tools
      ├─ get_order_status (TOOL)         ← fake-DB lookup
      ├─ check_inventory (TOOL)          ← fake-DB lookup
      └─ chat.completions (GENERATION)   ← final answer

    pip install "tracely-sdk[openai]"
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_agent.py
"""

from __future__ import annotations

import json
import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["openai"]
)


@tracely.observe(as_type="thinking")
def plan(question: str) -> str:
    """A reasoning step — emitted as a THINKING span (here a fixed plan; in real agents, a model call)."""
    return (
        "Plan: 1) look up the order status, 2) check coat inventory, 3) summarize for the customer."
    )


@tracely.observe(as_type="tool")
def get_order_status(order_id: str) -> dict:
    return _fake_db.get_order_status(order_id)


@tracely.observe(as_type="tool")
def check_inventory(sku: str) -> dict:
    return _fake_db.check_inventory(sku)


_TOOLS = {"get_order_status": get_order_status, "check_inventory": check_inventory}


@tracely.observe(as_type="agent")
def support_agent(question: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    plan(question)  # THINKING span
    messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    for _ in range(5):
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, tools=OPENAI_TOOLS
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            return msg.content or ""
        for call in msg.tool_calls:  # each runs an @observe-decorated TOOL span
            result = _TOOLS[call.function.name](**json.loads(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )
    return ""


def main() -> None:
    if "openai" not in tracely._instrumented or not os.environ.get("OPENAI_API_KEY"):
        print(
            "Needs OpenAI auto-instrumentation + a key:\n"
            '    pip install "tracely-sdk[openai]" && export OPENAI_API_KEY=sk-...'
        )
        return
    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        print("agent:", support_agent(QUESTION))
    tracely.flush()
    print("sent — open Tracely → Traces to see the agent → thinking · generations · tools tree.")


if __name__ == "__main__":
    main()
