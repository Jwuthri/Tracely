"""LangChain — automatic tracing of a tool-calling agent (PRD 12, R11).

A `create_tool_calling_agent` + `AgentExecutor` that answers the question using the fake-DB tools.
`tracely.init()` registers the LangChain callback handler, so the agent, each LLM step, and each tool
call trace end-to-end, nested. The LangChain instrumentor owns the LLM spans (under `"auto"` the
provider instrumentors are skipped to avoid duplicates); here we name `["langchain"]` explicitly.

    pip install "tracely-sdk[langchain]" langchain langchain-openai
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

    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI

    @tool
    def get_order_status(order_id: str) -> dict:
        """Look up an order's delivery status and ETA by its order id."""
        return _fake_db.get_order_status(order_id)

    @tool
    def check_inventory(sku: str) -> dict:
        """Check current stock level and price for a product SKU."""
        return _fake_db.check_inventory(sku)

    tools = [get_order_status, check_inventory]
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM), ("human", "{input}"), ("placeholder", "{agent_scratchpad}")]
    )
    agent = create_tool_calling_agent(ChatOpenAI(model="gpt-4o-mini"), tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools)

    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        out = executor.invoke({"input": QUESTION})
        print("agent:", out["output"])

    tracely.flush()
    print("sent — open Tracely → Traces to see the AgentExecutor → LLM + tool spans tree.")


if __name__ == "__main__":
    main()
