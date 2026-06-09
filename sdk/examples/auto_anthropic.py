"""Anthropic (Claude) — automatic tracing of a real tool-calling agent (PRD 12, P0).

A support agent answers a multi-part question using Claude's native tool use (`tool_use` /
`tool_result`) against the fake DB, then summarizes. Each `messages.create` call is captured
automatically as a GENERATION span by the Anthropic instrumentor — **no span code on the LLM
calls**. One `@observe(as_type="agent")` on the loop gives the run a single AGENT root so the
generations + tool spans land in one trace tree (instead of each messages.create() becoming its own
trace); the tool fns are decorated with `@observe(as_type="tool")` so each tool round-trip is a TOOL
span, and `tracely.trace(...)` attaches the run's agent/conversation/user metadata onto every span.

    pip install "tracely-sdk[anthropic]"
    export ANTHROPIC_API_KEY=sk-ant-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_anthropic.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import ANTHROPIC_TOOLS, QUESTION, SYSTEM, observed_tools

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

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        messages: list = [{"role": "user", "content": question}]
        for _ in range(5):  # agentic loop: call tools until Claude gives a final answer
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=SYSTEM,
                messages=messages,
                tools=ANTHROPIC_TOOLS,
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text")
            results = []
            for block in resp.content:  # dispatch as usual — the decorator makes each a TOOL span
                if block.type == "tool_use":
                    result = tools[block.name](**block.input)
                    print(f"  tool {block.name}{block.input} -> {result}")
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
            messages.append({"role": "user", "content": results})
        return "(loop limit hit)"

    with tracely.trace(
        agent="support-agent",
        conversation=os.path.basename(__file__),
        user="ada@example.com",
        example=os.path.basename(__file__),
    ):
        print("agent:", support_agent(QUESTION))

    tracely.flush()
    print("sent — open Tracely → Traces: one AGENT run → generations + tool spans, no span code.")


if __name__ == "__main__":
    main()
