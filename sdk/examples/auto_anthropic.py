"""Anthropic (Claude) — automatic tracing of a two-agent conversation (PRD 12, P0).

A Support Agent answers order/inventory questions with Claude's native tool use (`tool_use` /
`tool_result`), then hands the pricing turn to a Billing Agent. Each `messages.create` call is
captured automatically as a GENERATION span by the Anthropic instrumentor — **no span code on the
LLM calls**; the tool fns are decorated with `@observe(as_type="tool")` so each round-trip is a TOOL
span, and each agent is an ordinary `@observe(as_type="agent")` function.

    pip install "tracely-sdk[anthropic]"
    export ANTHROPIC_API_KEY=sk-ant-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_anthropic.py
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
    Conversation,
    anthropic_tools,
    observed_tools,
)

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["anthropic"]
)


def main() -> None:
    if "anthropic" not in tracely._instrumented:
        print('Anthropic instrumentation not active — pip install "tracely-sdk[anthropic]"')
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to make a real call (the span shape is identical either way).")
        return

    from anthropic import Anthropic

    client = Anthropic()
    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")

    def run(question: str, system: str, tool_names: list[str]) -> str:
        """A normal Claude tool-use loop. Each agent below is just this loop with its own tools."""
        # Thread the conversation: prior turns + this question (system is a separate Claude param).
        messages: list = [*history.prior(), {"role": "user", "content": question}]
        for _ in range(5):
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=1024, system=system,
                messages=messages, tools=anthropic_tools(tool_names),
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text")
            results = []
            for block in resp.content:  # dispatch as usual — the decorator makes each a TOOL span
                if block.type == "tool_use":
                    result = tools[block.name](**block.input)
                    results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}
                    )
            messages.append({"role": "user", "content": results})
        return "(loop limit hit)"

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        return run(question, SYSTEM, SUPPORT_TOOLS)

    @tracely.observe(as_type="agent")
    def billing_agent(question: str) -> str:
        return run(question, BILLING_SYSTEM, BILLING_TOOLS)

    handlers = {"support-agent": support_agent, "billing-agent": billing_agent}
    conv = os.path.basename(__file__)
    history = Conversation()  # carries prior turns forward so each turn sees the conversation
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            answer = handlers[slug](question)
            history.record(question, answer)
            print(f"[{slug}] turn {i}:", answer)

    tracely.flush()
    print("sent — a multi-turn, two-agent conversation → generations + tool spans, no span code.")


if __name__ == "__main__":
    main()
