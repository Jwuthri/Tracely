"""Non-patching drop-in — a real two-agent conversation, no global patching (PRD 12, R13).

`init(False)` sets up export only; `tracely_sdk.openai.OpenAI` (= `wrap_openai(openai.OpenAI())`)
traces just this client instance. Same Support→Billing two-agent loop as `auto_openai.py`, but
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
    conv = os.path.basename(__file__)
    for i, (question, slug) in enumerate(TURNS):
        with tracely.trace(
            agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
            agents=AGENTS if i == 0 else None,
        ):
            print(f"[{slug}] turn {i}:", handlers[slug](question))

    tracely.flush()
    print("sent — a multi-turn, two-agent conversation traced via the drop-in; nothing patched globally.")


if __name__ == "__main__":
    main()
