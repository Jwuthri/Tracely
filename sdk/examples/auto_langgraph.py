"""LangGraph — automatic tracing of custom graphs you build yourself (PRD 12, R11).

For the high-level prebuilt agent, use `create_agent` (see auto_langchain.py). LangGraph proper is
for *custom* control flow: here a hand-built ReAct loop — a model node + a `ToolNode` + conditional
routing — compiled once per agent. A Support graph answers order/inventory questions and a Billing
graph handles the pricing turn. LangGraph runs on LangChain's callbacks, so the same instrumentor
traces it: graph → nodes → GENERATION/TOOL spans, nested under `tracely.trace(...)`.

    pip install "tracely-sdk[langchain]" langgraph langchain-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_langgraph.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, BILLING_SYSTEM, BILLING_TOOLS, SUPPORT_TOOLS, SYSTEM, TURNS

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
        print('LangGraph needs the LangChain instrumentor — pip install "tracely-sdk[langchain]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    from langchain_core.messages import SystemMessage
    from langchain_core.tools import tool
    from langchain_openai import ChatOpenAI
    from langgraph.graph import START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode, tools_condition

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

    def build(tool_names: list[str], system: str):
        """Compile a ReAct graph (model ⇄ tools) for one agent's tool set."""
        tools = [catalog[n] for n in tool_names]
        model = ChatOpenAI(model="gpt-5.4-mini").bind_tools(tools)

        def call_model(state: MessagesState) -> dict:
            return {"messages": [model.invoke([SystemMessage(system), *state["messages"]])]}

        graph = StateGraph(MessagesState)
        graph.add_node("model", call_model)
        graph.add_node("tools", ToolNode(tools))
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", tools_condition)  # -> "tools" or END
        graph.add_edge("tools", "model")
        return graph.compile()

    handlers = {
        "support-agent": build(SUPPORT_TOOLS, SYSTEM),
        "billing-agent": build(BILLING_TOOLS, BILLING_SYSTEM),
    }
    conv = os.path.basename(__file__)
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            out = handlers[slug].invoke({"messages": [{"role": "user", "content": question}]})
            print(f"[{slug}] turn {i}:", out["messages"][-1].content)

    tracely.flush()
    print("sent — a multi-turn, two-agent conversation: each StateGraph → model/tools nodes → GENERATION/TOOL.")


if __name__ == "__main__":
    main()
