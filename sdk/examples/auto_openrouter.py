"""OpenRouter — automatic tracing, zero span code (PRD 12).

OpenRouter speaks the OpenAI wire protocol, so there's **no separate instrumentor**: point the OpenAI
SDK at OpenRouter's base URL and the OpenAI instrumentor traces it. The routed model id flows through
as `vendor/model` (e.g. `anthropic/claude-3.5-sonnet`) into `model_id`. Same support-agent
tool-calling loop as `auto_openai.py`.

    pip install "tracely-sdk[openai]"
    export OPENROUTER_API_KEY=sk-or-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_openrouter.py

Every big framework's OpenRouter handler is just that framework's LLM client with OpenRouter's
base_url, so the framework's instrumentor traces it the same way — no Tracely change needed:

    # LangChain  → instrument=["langchain"]
    ChatOpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY,
               model="anthropic/claude-3.5-sonnet")
    # LiteLLM    → instrument=["litellm"]
    litellm.completion(model="openrouter/anthropic/claude-3.5-sonnet", messages=[...])
    # LlamaIndex → instrument=["llama-index"]
    from llama_index.llms.openrouter import OpenRouter; OpenRouter(model="anthropic/claude-3.5-sonnet")
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM, run_tool

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

# OpenRouter is OpenAI-compatible → the OpenAI instrumentor captures it.
tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["openai"]
)

MODEL = "anthropic/claude-3.5-sonnet"  # any OpenRouter model — vendor/model


def main() -> None:
    if "openai" not in tracely._instrumented:
        print('OpenAI instrumentation not active — pip install "tracely-sdk[openai]"')
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Set OPENROUTER_API_KEY to make a real call.")
        return

    from openai import OpenAI

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        default_headers={"HTTP-Referer": "https://tracely.dev", "X-Title": "Tracely example"},
    )
    messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]
    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        for _ in range(5):
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, tools=OPENAI_TOOLS
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                print("agent:", msg.content)
                break
            for call in msg.tool_calls:
                result = run_tool(call.function.name, json.loads(call.function.arguments))
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
                )

    tracely.flush()
    print(f"sent — traced via the OpenAI instrumentor; model_id is the routed '{MODEL}'.")


if __name__ == "__main__":
    main()
