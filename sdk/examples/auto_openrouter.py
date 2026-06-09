"""OpenRouter — automatic tracing via LangChain `create_agent` (PRD 12).

OpenRouter routes one API to 100+ models. LangChain ships a first-party `ChatOpenRouter`
(`langchain-openrouter`) — drop it into `create_agent` as the model and the LangChain instrumentor
traces the whole tool-calling agent. The model is the OpenRouter `provider/model` id.

    pip install "tracely-sdk[langchain,openrouter]" "langchain>=1.0" langchain-openrouter
    export OPENROUTER_API_KEY=sk-or-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openrouter.py

Alternative (no langchain): point the OpenAI SDK at OpenRouter's base_url — it's OpenAI-compatible,
so the OpenAI instrumentor traces it (see the comment in auto_openai.py / the docs).
"""

from __future__ import annotations

import importlib.util
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

MODEL = "anthropic/claude-4.6-sonnet"  # OpenRouter "provider/model" format — route to any model


def main() -> None:
    if "langchain" not in tracely._instrumented:
        print('LangChain instrumentation not active — pip install "tracely-sdk[langchain]"')
        return
    if importlib.util.find_spec("langchain_openrouter") is None:
        print("pip install langchain-openrouter")
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Set OPENROUTER_API_KEY to make a real call.")
        return

    from langchain.agents import create_agent
    from langchain_core.tools import tool
    from langchain_openrouter import ChatOpenRouter

    @tool
    def get_order_status(order_id: str) -> dict:
        """Look up an order's delivery status and ETA by its order id."""
        return _fake_db.get_order_status(order_id)

    @tool
    def check_inventory(sku: str) -> dict:
        """Check current stock level and price for a product SKU."""
        return _fake_db.check_inventory(sku)

    # ChatOpenRouter is a LangChain ChatModel → pass it straight into create_agent as the model.
    agent = create_agent(
        ChatOpenRouter(model=MODEL), tools=[get_order_status, check_inventory], system_prompt=SYSTEM
    )
    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})
        print("agent:", result["messages"][-1].content)

    tracely.flush()
    print(f"sent — OpenRouter '{MODEL}' via create_agent, traced by the LangChain instrumentor.")


if __name__ == "__main__":
    main()
