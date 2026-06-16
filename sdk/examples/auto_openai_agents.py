"""OpenAI Agents SDK — automatic tracing of a two-agent conversation (PRD 12).

The OpenAI Agents SDK (`agents`) builds tool-using agents. `tracely.init(instrument=["openai-agents"])`
activates OpenInference's `OpenAIAgentsInstrumentor`, which captures each agent run + tool call as
spans. A Support Agent answers order/inventory questions and a Billing Agent handles the pricing turn.

    pip install "tracely-sdk[openai-agents]" openai-agents
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openai_agents.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, BILLING_SYSTEM, SYSTEM, TURNS, Conversation

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


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
        print('OpenAI Agents SDK not active — pip install "tracely-sdk[openai-agents]" openai-agents')
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

    @function_tool
    def compare_prices(sku_a: str, sku_b: str) -> dict:
        """Compare the prices of two SKUs and report which is cheaper."""
        return _fake_db.compare_prices(sku_a, sku_b)

    handlers = {
        "support-agent": Agent(name="support-agent", instructions=SYSTEM,
                               tools=[get_order_status, check_inventory]),
        "billing-agent": Agent(name="billing-agent", instructions=BILLING_SYSTEM,
                               tools=[compare_prices]),
    }
    conv = os.path.basename(__file__)
    history = Conversation()  # carries prior turns forward so each turn sees the conversation
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            # Thread the conversation: prior turns + this question as the run's input items.
            result = Runner.run_sync(handlers[slug], [*history.prior(), {"role": "user", "content": question}])
            answer = result.final_output
            history.record(question, answer)
            print(f"[{slug}] turn {i}:", answer)

    tracely.flush()
    print("sent — a multi-turn, two-agent conversation: Agents SDK runs + tool spans.")


if __name__ == "__main__":
    main()
