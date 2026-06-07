"""LangChain — automatic tracing of a tool-calling agent via `create_agent` (PRD 12, R11).

LangChain 1.0+ replaced `create_react_agent` / `create_tool_calling_agent`+`AgentExecutor` with
`from langchain.agents import create_agent`. It builds a tool-calling agent (a compiled LangGraph)
that loops until it answers. `tracely.init()` registers the LangChain callback handler, so the
agent + each LLM step + each tool call trace end-to-end. The LangChain instrumentor owns the LLM
spans (under `instrument="auto"` the provider instrumentors are skipped to avoid duplicates).

    pip install "tracely-sdk[langchain]" "langchain>=1.0" langchain-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_langchain.py
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

    # model can be a "provider:model" string (init_chat_model) or a ChatModel instance.
    agent = create_agent(
        "openai:gpt-4o-mini", tools=[get_order_status, check_inventory], system_prompt=SYSTEM
    )

    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
        print("agent:", result["messages"][-1].content)

    tracely.flush()
    print("sent — open Tracely → Traces to see the create_agent loop: LLM + tool spans, nested.")


if __name__ == "__main__":
    main()
