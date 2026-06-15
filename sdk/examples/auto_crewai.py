"""CrewAI — automatic tracing of a two-agent conversation (PRD 12).

A Support agent (order/inventory tools) and a Billing agent (price comparison), each a CrewAI
`Agent`. `tracely.init()` activates the CrewAI instrumentor, so the crew, agent, task, tool calls,
and underlying LLM calls all trace end-to-end, nested. Support takes the first turns and the Billing
agent handles the pricing turn.

    pip install "tracely-sdk[crewai]" crewai
    export OPENAI_API_KEY=sk-...        # CrewAI defaults to OpenAI
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_crewai.py
"""

from __future__ import annotations

import os

# CrewAI ships its own telemetry that emits flat "Crew Created"/"Task Created"/"Tool Usage" spans
# (each its own root → a separate trace). Disable it via CrewAI's own knobs so Tracely owns tracing —
# NOT via OTEL_SDK_DISABLED, which would also silence our exporter (keep that explicitly enabled).
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "false")

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, TURNS

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
    # CrewAI's instrumentor traces lifecycle (crew/agent/task/tool); it routes models via LiteLLM
    # which in turn calls the OpenAI SDK — the OpenAI instrumentor adds the underlying GENERATION
    # spans with token counts.
    instrument=["crewai", "openai"],
)


def main() -> None:
    if "crewai" not in tracely._instrumented:
        print('CrewAI instrumentation not active — pip install "tracely-sdk[crewai]" crewai')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    from crewai import Agent, Crew, Task
    from crewai.tools import tool

    @tool("get_order_status")
    @tracely.observe(as_type="tool")
    def get_order_status(order_id: str) -> str:
        """Look up an order's delivery status and ETA by its order id."""
        return str(_fake_db.get_order_status(order_id))

    @tool("check_inventory")
    @tracely.observe(as_type="tool")
    def check_inventory(sku: str) -> str:
        """Check current stock level and price for a product SKU."""
        return str(_fake_db.check_inventory(sku))

    @tool("compare_prices")
    @tracely.observe(as_type="tool")
    def compare_prices(sku_a: str, sku_b: str) -> str:
        """Compare the prices of two SKUs and report which is cheaper."""
        return str(_fake_db.compare_prices(sku_a, sku_b))

    support = Agent(
        role="Customer-support agent",
        goal="Answer the customer's order and inventory questions using the lookup tools",
        backstory="You resolve order + stock questions accurately and concisely.",
        tools=[get_order_status, check_inventory],
    )
    billing = Agent(
        role="Billing agent",
        goal="Answer pricing-comparison questions",
        backstory="You compare prices and tell the customer which item is cheaper.",
        tools=[compare_prices],
    )

    def run(question: str, agent: Agent) -> str:
        task = Task(description=question, expected_output="A concise, helpful answer.", agent=agent)
        return str(Crew(agents=[agent], tasks=[task]).kickoff())

    # Wrap each kickoff in an AGENT root so the crew's GENERATION + TOOL spans nest into ONE trace
    # (without it, each model/tool call CrewAI makes becomes its own root → a separate trace).
    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        return run(question, support)

    @tracely.observe(as_type="agent")
    def billing_agent(question: str) -> str:
        return run(question, billing)

    handlers = {"support-agent": support_agent, "billing-agent": billing_agent}
    conv = os.path.basename(__file__)
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            print(f"[{slug}] turn {i}:", handlers[slug](question))

    tracely.flush()
    print("sent — a multi-turn, two-agent conversation: crew → agent → task → tool/LLM tree.")


if __name__ == "__main__":
    main()
