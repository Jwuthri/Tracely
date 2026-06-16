"""LangChain — automatic tracing of a two-agent conversation via `create_agent` (PRD 12, R11).

LangChain 1.0+ builds a tool-calling agent (a compiled LangGraph) with `create_agent`. Here a Support
Agent answers order/inventory questions and hands the pricing turn to a Billing Agent — two ordinary
`create_agent` agents, routed per turn. `tracely.init()` registers the LangChain callback handler, so
each agent + LLM step + tool call traces end-to-end; `agents=AGENTS` declares the two-agent catalog.

    pip install "tracely-sdk[langchain]" "langchain>=1.0" langchain-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_langchain.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, BILLING_SYSTEM, BILLING_TOOLS, SUPPORT_TOOLS, SYSTEM, TURNS, Conversation

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["langchain"]
)


def main() -> None:
    if "langchain" not in tracely._instrumented:
        print('LangChain instrumentation not active — pip install "tracely-sdk[langchain]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    from langchain.agents import create_agent
    from langchain_core.tools import tool

    @tool
    def get_order_status(order_id: str) -> dict:
        """Look up an order's delivery status and ETA by its order id."""
        return _fake_db.get_order_status(order_id)

    @tool
    def check_inventory(sku: str) -> dict:
        """Check current stock level and price for a product SKU."""
        return _fake_db.check_inventory(sku)

    @tool
    def compare_prices(sku_a: str, sku_b: str) -> dict:
        """Compare the prices of two SKUs and report which is cheaper."""
        return _fake_db.compare_prices(sku_a, sku_b)

    catalog = {"get_order_status": get_order_status, "check_inventory": check_inventory,
               "compare_prices": compare_prices}

    def build(tool_names: list[str], system: str, name: str):  # model can be a "provider:model" string or a ChatModel
        # `name` names the agent's compiled graph, so the trace's root span reads as the agent
        # (e.g. "support-agent") instead of the generic "LangGraph".
        return create_agent("openai:gpt-5.4-mini", tools=[catalog[n] for n in tool_names], system_prompt=system, name=name)

    handlers = {
        "support-agent": build(SUPPORT_TOOLS, SYSTEM, "support-agent"),
        "billing-agent": build(BILLING_TOOLS, BILLING_SYSTEM, "billing-agent"),
    }
    conv = os.path.basename(__file__)
    history = Conversation()  # carries prior turns forward so each turn sees the conversation
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            # Thread the conversation: prior turns + this question (the agent prepends its system prompt).
            result = handlers[slug].invoke({"messages": [*history.prior(), {"role": "user", "content": question}]})
            answer = result["messages"][-1].content
            history.record(question, answer)
            print(f"[{slug}] turn {i}:", answer)

    tracely.flush()
    print("sent — a multi-turn, two-agent conversation: each create_agent loop → LLM + tool spans, nested.")


if __name__ == "__main__":
    main()
