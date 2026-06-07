"""OpenAI Agents SDK — automatic tracing (PRD 12).

The OpenAI Agents SDK (`agents`) builds tool-using agents. `tracely.init(instrument=["openai-agents"])`
activates OpenInference's `OpenAIAgentsInstrumentor`, which captures each agent run + tool call as
spans, exported to Tracely (and stamped with the `tracely.trace(...)` context).

    pip install "tracely-sdk[openai-agents]" openai-agents
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openai_agents.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import QUESTION, SYSTEM

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API,
    api_key=KEY,
    service_name="support-agent",
    env="prod",
    instrument=["openai-agents"],
)


def main() -> None:
    if "openai-agents" not in tracely._instrumented:
        print(
            'OpenAI Agents SDK not active — pip install "tracely-sdk[openai-agents]" openai-agents'
        )
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    from agents import Agent, Runner, function_tool

    @function_tool
    def get_order_status(order_id: str) -> dict:
        """Look up an order's delivery status and ETA by its order id."""
        return _fake_db.get_order_status(order_id)

    @function_tool
    def check_inventory(sku: str) -> dict:
        """Check current stock level and price for a product SKU."""
        return _fake_db.check_inventory(sku)

    agent = Agent(
        name="support-agent", instructions=SYSTEM, tools=[get_order_status, check_inventory]
    )

    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        result = Runner.run_sync(agent, QUESTION)
        print("agent:", result.final_output)

    tracely.flush()
    print("sent — open Tracely → Traces to see the Agents SDK run + tool spans.")


if __name__ == "__main__":
    main()
