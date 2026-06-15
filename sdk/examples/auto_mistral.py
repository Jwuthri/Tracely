"""Mistral — automatic tracing of a two-agent conversation (PRD 12).

Same Support→Billing two-agent flow as `auto_openai.py` (Mistral uses an OpenAI-compatible tool
schema); every `chat.complete` call + tool round-trip is captured as a GENERATION span, no span code.

    pip install "tracely-sdk[mistral]" mistralai
    export MISTRAL_API_KEY=...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_mistral.py
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
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["mistral"]
)


def main() -> None:
    if "mistral" not in tracely._instrumented:
        # The OpenInference Mistral instrumentor targets a different mistralai major than the one
        # installed here, so the auto path is unavailable. (For a no-patch alternative that works
        # with this mistralai, wrap a client with `tracely_sdk.mistral.Mistral` — same as the other
        # drop-ins.) Skip cleanly rather than emit a half-traced run.
        print('Mistral instrumentation not active — pip install "tracely-sdk[mistral]" mistralai')
        return
    if not os.environ.get("MISTRAL_API_KEY"):
        print("Set MISTRAL_API_KEY to make a real call.")
        return

    from mistralai import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")

    def run(question: str, system: str, tool_names: list[str]) -> str:
        """A normal tool-calling loop. Each agent below is just this loop with its own tools."""
        messages: list = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        for _ in range(5):
            resp = client.chat.complete(
                model="mistral-large-latest", messages=messages, tools=openai_tools(tool_names)
            )
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in calls
                    ],
                }
            )
            if not calls:
                return msg.content or ""
            for call in calls:  # dispatch as usual — the decorator makes each a TOOL span
                result = tools[call.function.name](**json.loads(call.function.arguments))
                messages.append(
                    {"role": "tool", "name": call.function.name, "tool_call_id": call.id,
                     "content": json.dumps(result)}
                )
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
    print("sent — a multi-turn, two-agent conversation; generations + tool spans, no span code.")


if __name__ == "__main__":
    main()
