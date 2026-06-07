"""LlamaIndex — automatic tracing of a ReAct tool-calling agent (PRD 12).

A `ReActAgent` over the fake-DB tools (`FunctionTool`s). `tracely.init()` activates the LlamaIndex
instrumentor, so the agent's reasoning steps, tool calls, and LLM calls trace end-to-end, nested.

    pip install "tracely-sdk[llama-index]" llama-index llama-index-llms-openai
    export OPENAI_API_KEY=sk-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_llama_index.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import QUESTION

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

    tools = [
        FunctionTool.from_defaults(fn=_fake_db.get_order_status),
        FunctionTool.from_defaults(fn=_fake_db.check_inventory),
    ]
    # LlamaIndex 0.12+ replaced ReActAgent.from_tools / .chat with a Workflow whose runs are awaitable.
    # `streaming=False` so each LLM call returns usage tokens (streamed OpenAI calls omit them).
    agent = ReActAgent(tools=tools, llm=LlamaOpenAI(model="gpt-4o-mini"), verbose=False, streaming=False)

    async def run() -> None:
        with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
            resp = await agent.run(user_msg=QUESTION)
            print("agent:", resp)

    asyncio.run(run())
    tracely.flush()
    print("sent — open Tracely → Traces to see the ReAct agent → tool + LLM spans tree.")


if __name__ == "__main__":
    main()
