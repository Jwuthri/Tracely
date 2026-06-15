"""Automatic tracing — full `@observe` agents: thinking → tools → answer (PRD 12, P1).

`@observe` turns functions into spans (args→input, return→output, latency, errors), auto-nested via
OTel context. The OpenAI calls inside are captured by the auto-instrumentor. One enclosing
`tracely.trace(...)` flows the run's agent/conversation onto every span. A Support Agent handles the
first turns and hands the pricing turn to a Billing Agent.

Produces a real agent tree per turn:
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
from _fake_db import AGENTS, BILLING_SYSTEM, BILLING_TOOLS, SUPPORT_TOOLS, SYSTEM, TURNS, openai_tools

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["openai"]
)


@tracely.observe(as_type="thinking")
def plan(question: str) -> str:
    """A reasoning step — emitted as a THINKING span (here a fixed plan; in real agents, a model call)."""
    return "Plan: look up what the customer asked about with the tools, then summarize concisely."


@tracely.observe(as_type="tool")
def get_order_status(order_id: str) -> dict:
    return _fake_db.get_order_status(order_id)


@tracely.observe(as_type="tool")
def check_inventory(sku: str) -> dict:
    return _fake_db.check_inventory(sku)


@tracely.observe(as_type="tool")
def compare_prices(sku_a: str, sku_b: str) -> dict:
    return _fake_db.compare_prices(sku_a, sku_b)


_TOOLS = {
    "get_order_status": get_order_status,
    "check_inventory": check_inventory,
    "compare_prices": compare_prices,
}


def main() -> None:
    if "openai" not in tracely._instrumented or not os.environ.get("OPENAI_API_KEY"):
        print(
            "Needs OpenAI auto-instrumentation + a key:\n"
            '    pip install "tracely-sdk[openai]" && export OPENAI_API_KEY=sk-...'
        )
        return

    from openai import OpenAI

    client = OpenAI()

    def run(question: str, system: str, tool_names: list[str]) -> str:
        """A normal think→tool-loop→answer agent. Each agent below is this loop with its own tools."""
        plan(question)  # THINKING span
        messages: list = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        for _ in range(5):
            resp = client.chat.completions.create(
                model="gpt-5.4-mini", messages=messages, tools=openai_tools(tool_names)
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return msg.content or ""
            for call in msg.tool_calls:  # each runs an @observe-decorated TOOL span
                result = _TOOLS[call.function.name](**json.loads(call.function.arguments))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
        return ""

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        return run(question, SYSTEM, SUPPORT_TOOLS)

    @tracely.observe(as_type="agent")
    def billing_agent(question: str) -> str:
        return run(question, BILLING_SYSTEM, BILLING_TOOLS)

    handlers = {"support-agent": support_agent, "billing-agent": billing_agent}
    conv = os.path.basename(__file__)
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            print(f"[{slug}] turn {i}:", handlers[slug](question))
    tracely.flush()
    print("sent — a multi-turn, two-agent run: agent → thinking · generations · tools, no span code on LLM calls.")


if __name__ == "__main__":
    main()
