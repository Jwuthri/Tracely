"""Non-patching drop-in for Anthropic — a real tool-calling agent, no global patching (PRD 12, R13).

The Anthropic counterpart to `dropin_openai.py`: `init(False)` sets up export only;
`tracely_sdk.anthropic.Anthropic` (= `wrap_anthropic(anthropic.Anthropic())`) traces just this
client instance. Same Claude tool-use loop as `auto_anthropic.py`, nothing patched globally.

    pip install "tracely-sdk[anthropic]"      # or just: pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/dropin_anthropic.py
"""

from __future__ import annotations

import importlib.util
import json
import os

import tracely_sdk as tracely
from _fake_db import ANTHROPIC_TOOLS, QUESTION, SYSTEM, run_tool

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

# instrument=False — the drop-in traces one client instance, nothing patched globally.
tracely.init(endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=False)


def main() -> None:
    if importlib.util.find_spec("anthropic") is None:
        print("pip install anthropic")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to make a real call.")
        return

    from tracely_sdk.anthropic import (
        Anthropic,
    )  # pre-wrapped (= wrap_anthropic(anthropic.Anthropic()))

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
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
            messages.append({"role": "user", "content": results})

    tracely.flush()
    print("sent — Claude tool-calling agent traced via the drop-in; nothing patched globally.")


if __name__ == "__main__":
    main()
