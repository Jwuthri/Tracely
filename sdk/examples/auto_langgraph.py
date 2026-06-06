"""LangGraph — automatic tracing of a ReAct tool-calling agent (PRD 12, R11).

`create_react_agent` builds the canonical agent/tools graph; it loops (call model → call tools →
call model) until it answers. LangGraph is built on LangChain's callbacks, so the same instrumentor
traces it: the graph is a CHAIN, nodes are child CHAINs (node name → `step_name`/`step_id`), tool
calls are TOOL spans, and the LLM calls are GENERATION spans — all nested under `tracely.trace(...)`.

    pip install "tracely-sdk[langchain]" langgraph langchain-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_langgraph.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import QUESTION, SYSTEM

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["langchain"]
)


def main() -> None:
    if "langchain" not in tracely._instrumented:
        print('LangGraph needs the LangChain instrumentor — pip install "tracely-sdk[langchain]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    @tool
    def get_order_status(order_id: str) -> dict:
        """Look up an order's delivery status and ETA by its order id."""
        return _fake_db.get_order_status(order_id)

    @tool
    def check_inventory(sku: str) -> dict:
        """Check current stock level and price for a product SKU."""
        return _fake_db.check_inventory(sku)

    agent = create_react_agent(
        ChatOpenAI(model="gpt-4o-mini"), [get_order_status, check_inventory], prompt=SYSTEM
    )

    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        out = agent.invoke({"messages": [("user", QUESTION)]})
        print("agent:", out["messages"][-1].content)

    tracely.flush()
    print("sent — open Tracely → Traces to see the ReAct graph → node → GENERATION/TOOL tree.")


if __name__ == "__main__":
    main()
