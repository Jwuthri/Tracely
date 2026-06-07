"""Anthropic (Claude) — automatic tracing of a real tool-calling agent (PRD 12, P0).

A support agent answers a multi-part question using Claude's native tool use (`tool_use` /
`tool_result`) against the fake DB, then summarizes. Every `messages.create` call + tool round-trip
is captured as a GENERATION span — no span code.

    pip install "tracely-sdk[anthropic]"
    export ANTHROPIC_API_KEY=sk-ant-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_anthropic.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import ANTHROPIC_TOOLS, QUESTION, SYSTEM, run_tool

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
    messages: list = [{"role": "user", "content": QUESTION}]
    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        for _ in range(5):
            resp = client.messages.create(
                model="claude-3-5-sonnet-latest",
                max_tokens=1024,
                system=SYSTEM,
                messages=messages,
                tools=ANTHROPIC_TOOLS,
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                print("agent:", "".join(b.text for b in resp.content if b.type == "text"))
                break
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    print(f"  tool {block.name}{block.input} -> {result}")
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
            messages.append({"role": "user", "content": results})

    tracely.flush()
    print("sent — open Tracely → Traces: each generation + tool round-trip captured, no span code.")


if __name__ == "__main__":
    main()
