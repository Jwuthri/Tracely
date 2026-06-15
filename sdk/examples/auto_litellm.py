"""LiteLLM — automatic tracing of a two-agent conversation across 100+ providers (PRD 12, R12).

`init(instrument=["litellm"])` wires `litellm.callbacks=["otel"]`, so every `litellm.completion()`
(to any provider) — including the tool round-trips — exports through Tracely as a GENERATION span.
LiteLLM normalizes everything to the OpenAI shape, so the loop matches `auto_openai.py`: a Support
Agent hands the pricing turn to a Billing Agent, each an ordinary `@observe(as_type="agent")` fn.

    pip install "tracely-sdk[litellm]"
    export OPENAI_API_KEY=sk-...        # or any provider key LiteLLM routes to (change the model)
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_litellm.py
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
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["litellm"]
)


def main() -> None:
    if "litellm" not in tracely._instrumented:
        print('LiteLLM not active — pip install "tracely-sdk[litellm]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY (or change the model to another provider LiteLLM routes to).")
        return

    import litellm

    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")

    def run(question: str, system: str, tool_names: list[str]) -> str:
        """A normal tool-calling loop. Each agent below is just this loop with its own tools."""
        messages: list = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        for _ in range(5):
            resp = litellm.completion(
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
    print("sent — a multi-turn, two-agent conversation traced via one LiteLLM callback.")


if __name__ == "__main__":
    main()
