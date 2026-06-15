"""Google ADK (Agent Development Kit) — automatic tracing of a two-agent conversation (PRD 12).

Google's ADK (`google.adk`) builds agents with plain-function tools. `tracely.init(instrument=
["google-adk"])` activates OpenInference's `GoogleADKInstrumentor`, which captures the agent run +
tool calls as spans. A Support agent answers order/inventory questions and a Billing agent handles
the pricing turn. IMPORTANT: the instrumentor must run BEFORE `google.adk` is imported — so `init()`
at module top precedes the `from google.adk...` import in `run()`.

    pip install "tracely-sdk[google-adk]" google-adk
    export GOOGLE_API_KEY=...        # or GEMINI_API_KEY
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_google_adk.py
"""

from __future__ import annotations

import asyncio
import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, BILLING_SYSTEM, SYSTEM, TURNS

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

# Activate the ADK instrumentor BEFORE google.adk is imported (it patches at import time).
tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["google-adk"]
)


def get_order_status(order_id: str) -> dict:
    """Look up an order's delivery status and ETA by its order id."""
    return _fake_db.get_order_status(order_id)


def check_inventory(sku: str) -> dict:
    """Check current stock level and price for a product SKU."""
    return _fake_db.check_inventory(sku)


def compare_prices(sku_a: str, sku_b: str) -> dict:
    """Compare the prices of two SKUs and report which is cheaper."""
    return _fake_db.compare_prices(sku_a, sku_b)


async def run() -> None:
    from google.adk.agents import Agent
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    conv = os.path.basename(__file__)
    support = Agent(
        name="support_agent", model="gemini-3.1-flash-lite", description="Customer-support agent",
        instruction=SYSTEM, tools=[get_order_status, check_inventory],
    )
    billing = Agent(
        name="billing_agent", model="gemini-3.1-flash-lite", description="Billing agent",
        instruction=BILLING_SYSTEM, tools=[compare_prices],
    )
    runners = {
        "support-agent": InMemoryRunner(agent=support, app_name="store"),
        "billing-agent": InMemoryRunner(agent=billing, app_name="store"),
    }
    for r in runners.values():  # one session per agent, keyed by the conversation
        await r.session_service.create_session(app_name="store", user_id="ada", session_id=conv)

    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            async for event in runners[slug].run_async(
                user_id="ada", session_id=conv,
                new_message=types.Content(role="user", parts=[types.Part(text=question)]),
            ):
                if event.is_final_response():
                    print(f"[{slug}] turn {i}:", event.content.parts[0].text)


def main() -> None:
    if "google-adk" not in tracely._instrumented:
        print('Google ADK not active — pip install "tracely-sdk[google-adk]" google-adk')
        return
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        print("Set GOOGLE_API_KEY (or GEMINI_API_KEY) to run.")
        return

    asyncio.run(run())
    tracely.flush()
    print("sent — a multi-turn, two-agent conversation: Google ADK agent runs + tool spans.")


if __name__ == "__main__":
    main()
