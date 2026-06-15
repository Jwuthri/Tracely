"""LlamaIndex — automatic tracing of a two-agent conversation (PRD 12).

Two `ReActAgent`s over the fake-DB tools (`FunctionTool`s): a Support agent (order/inventory) and a
Billing agent (price comparison). `tracely.init()` activates the LlamaIndex instrumentor, so each
agent's reasoning steps, tool calls, and LLM calls trace end-to-end, nested.

    pip install "tracely-sdk[llama-index]" llama-index llama-index-llms-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_llama_index.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, BILLING_TOOLS, SUPPORT_TOOLS, TURNS

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["llama-index"]
)


def main() -> None:
    if "llama-index" not in tracely._instrumented:
        print('LlamaIndex instrumentation not active — pip install "tracely-sdk[llama-index]"')
        return
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to make a real call.")
        return

    import asyncio

    from llama_index.core.agent import ReActAgent
    from llama_index.core.tools import FunctionTool
    from llama_index.llms.openai import OpenAI as LlamaOpenAI

    fns = {
        "get_order_status": _fake_db.get_order_status,
        "check_inventory": _fake_db.check_inventory,
        "compare_prices": _fake_db.compare_prices,
    }

    def build(tool_names: list[str]) -> ReActAgent:
        tools = [FunctionTool.from_defaults(fn=fns[n]) for n in tool_names]
        # LlamaIndex 0.12+ replaced ReActAgent.from_tools/.chat with a Workflow whose runs are awaitable.
        # `streaming=False` so each LLM call returns usage tokens (streamed OpenAI calls omit them).
        return ReActAgent(tools=tools, llm=LlamaOpenAI(model="gpt-5.4-mini"), verbose=False, streaming=False)

    handlers = {"support-agent": build(SUPPORT_TOOLS), "billing-agent": build(BILLING_TOOLS)}

    async def run() -> None:
        conv = os.path.basename(__file__)
        for i, (question, slug) in enumerate(TURNS):
            with tracely.trace(
                agent=slug, conversation=conv, turn=i, user="ada@example.com", example=conv,
                agents=AGENTS if i == 0 else None,
            ):
                resp = await handlers[slug].run(user_msg=question)
                print(f"[{slug}] turn {i}:", resp)

    asyncio.run(run())
    tracely.flush()
    print("sent — a multi-turn, two-agent conversation: each ReAct agent → tool + LLM spans tree.")


if __name__ == "__main__":
    main()
