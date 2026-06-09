"""CrewAI — automatic tracing of a crew that uses tools (PRD 12).

A support agent in a crew, equipped with the fake-DB tools, completes a task. `tracely.init()`
activates the CrewAI instrumentor, so the crew, the agent, the task, the tool calls, and the
underlying LLM calls all trace end-to-end, nested.

    pip install "tracely-sdk[crewai]" crewai
    export OPENAI_API_KEY=sk-...        # CrewAI defaults to OpenAI
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_crewai.py
"""

from __future__ import annotations

import os

# CrewAI ships its own tracer that competes with our TracerProvider; turn it off so Tracely owns
# tracing (and the LiteLLM instrumentor's GENERATION spans flow through).
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
os.environ.setdefault("OTEL_SDK_DISABLED", "false")

import _fake_db
import tracely_sdk as tracely
from _fake_db import QUESTION

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

    support = Agent(
        role="Customer-support agent",
        goal="Answer the customer's question using the lookup tools",
        backstory="You resolve order + stock questions accurately and concisely.",
        tools=[get_order_status, check_inventory],
    )
    task = Task(description=QUESTION, expected_output="A concise, helpful answer.", agent=support)
    crew = Crew(agents=[support], tasks=[task])

    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        print("agent:", crew.kickoff())

    tracely.flush()
    print("sent — open Tracely → Traces to see the crew → agent → task → tool/LLM tree.")


if __name__ == "__main__":
    main()
