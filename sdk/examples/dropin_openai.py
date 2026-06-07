"""Non-patching drop-in — a real tool-calling agent, no global patching (PRD 12, R13).

`init(False)` sets up export only; `tracely_sdk.openai.OpenAI` (= `wrap_openai(openai.OpenAI())`)
traces just this client instance. Same support-agent tool-calling loop as `auto_openai.py`, but
nothing is monkey-patched globally.

    pip install "tracely-sdk[openai]"      # or just: pip install openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/dropin_openai.py
"""

from __future__ import annotations

import importlib.util
import json
import os

import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM, run_tool

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

# instrument=False — the whole point of the drop-in is to NOT patch anything globally.
tracely.init(endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=False)


def main() -> None:
    if importlib.util.find_spec("openai") is None:
        print("pip install openai")
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    from tracely_sdk.openai import OpenAI  # a pre-wrapped client (= wrap_openai(openai.OpenAI()))

    client = OpenAI()

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
        for _ in range(5):
            resp = client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, tools=OPENAI_TOOLS
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return msg.content or ""
            for call in msg.tool_calls:
                result = run_tool(call.function.name, json.loads(call.function.arguments))
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )
        return "(loop limit hit)"

    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        print("agent:", support_agent(QUESTION))

    tracely.flush()
    print("sent — tool-calling agent traced via the drop-in; nothing patched globally.")


if __name__ == "__main__":
    main()
