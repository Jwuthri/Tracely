"""LangGraph — automatic tracing of a custom graph you build yourself (PRD 12, R11).

For the high-level prebuilt agent, use `create_agent` (see auto_langchain.py — `create_react_agent`
is deprecated). LangGraph proper is for *custom* control flow: here a hand-built ReAct loop — a model
node + a `ToolNode` + conditional routing (`tools_condition`). LangGraph runs on LangChain's
callbacks, so the same instrumentor traces it: the graph → each node → GENERATION/TOOL spans, nested
under `tracely.trace(...)`.

    pip install "tracely-sdk[langchain]" langgraph langchain-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_langgraph.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import QUESTION, SYSTEM

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

    # LangGraph's ToolNode opens an OpenInference TOOL span via its callback handler — the
    # instrumentor only captures the first positional arg as `input.value`, and the callback
    # context isn't exposed to user code (so we can't stamp tracely.* attributes on it). Live
    # with the partial capture here; for full tool I/O fidelity, see auto_openai_agents.py.
    @tool
    def get_order_status(order_id: str) -> dict:
        """Look up an order's delivery status and ETA by its order id."""
        return _fake_db.get_order_status(order_id)

    @tool
    def check_inventory(sku: str) -> dict:
        """Check current stock level and price for a product SKU."""
        return _fake_db.check_inventory(sku)

    tools = [get_order_status, check_inventory]
    model = ChatOpenAI(model="gpt-5.4-mini").bind_tools(tools)

    def call_model(state: MessagesState) -> dict:
        return {"messages": [model.invoke([SystemMessage(SYSTEM), *state["messages"]])]}

    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", tools_condition)  # -> "tools" or END
    graph.add_edge("tools", "model")
    app = graph.compile()

    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        out = app.invoke({"messages": [{"role": "user", "content": QUESTION}]})
        print("agent:", out["messages"][-1].content)

    tracely.flush()
    print(
        "sent — open Tracely → Traces to see the StateGraph → model/tools nodes → GENERATION/TOOL."
    )


if __name__ == "__main__":
    main()
