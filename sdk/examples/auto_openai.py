"""OpenAI — automatic tracing of a real two-agent conversation (PRD 12, P0).

A Support Agent answers order/inventory questions by calling fake-DB tools in an agentic loop, then
hands the final pricing-comparison turn to a Billing Agent. Every model call is captured
automatically as a GENERATION span by the OpenAI instrumentor — **no span code on the LLM calls**.
Each agent is an ordinary function with one `@observe(as_type="agent")`, so its generations + tool
spans land in one trace tree; `tracely.trace(...)` attaches the run's agent/conversation/user
metadata onto every span inside, and `agents=AGENTS` (sent once) declares the two-agent catalog.

    pip install "tracely-sdk[openai]"
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openai.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import (
    AGENTS,
    BILLING_SYSTEM,
    BILLING_TOOLS,
    SUPPORT_TOOLS,
    SYSTEM,
    TURNS,
    observed_tools,
    openai_tools,
)

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["openai"]
)


def main() -> None:
    if "openai" not in tracely._instrumented:
        print('OpenAI instrumentation not active — pip install "tracely-sdk[openai]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call (the span shape is identical either way).")
        return

    from openai import OpenAI

    client = OpenAI()
    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")

    def run(question: str, system: str, tool_names: list[str]) -> str:
        """A normal tool-calling loop. Each agent below is just this loop with its own tools."""
        messages: list = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        for _ in range(5):
            resp = client.chat.completions.create(
                model="gpt-5.4-mini", messages=messages, tools=openai_tools(tool_names)
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return msg.content or ""
            for call in msg.tool_calls:  # dispatch as usual — the decorator makes each a TOOL span
                result = tools[call.function.name](**json.loads(call.function.arguments))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
        return "(loop limit hit)"

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        return run(question, SYSTEM, SUPPORT_TOOLS)

    @tracely.observe(as_type="agent")
    def billing_agent(question: str) -> str:
        return run(question, BILLING_SYSTEM, BILLING_TOOLS)

    handlers = {"support-agent": support_agent, "billing-agent": billing_agent}

    # One conversation, several turns (so the rolling summary accumulates); Support takes the first
    # turns and hands the pricing turn to Billing. The catalog is declared once on the first turn.
    conv = os.path.basename(__file__)
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            print(f"[{slug}] turn {i}:", handlers[slug](question))

    tracely.flush()
    print(
        f"sent — open Tracely → Traces: a {len(TURNS)}-turn conversation across two agents; the rolling "
        "summary accumulates across turns and both agents show in the Agents panel."
    )


if __name__ == "__main__":
    main()
