"""Mistral — automatic tracing of a real tool-calling agent (PRD 12).

Same support-agent loop as `auto_openai.py` (Mistral uses an OpenAI-compatible tool schema); every
`chat.complete` call + tool round-trip is captured as a GENERATION span, no span code.

    pip install "tracely-sdk[mistral]" mistralai
    export MISTRAL_API_KEY=...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_mistral.py
"""

from __future__ import annotations

import json
import os

import tracely_sdk as tracely
from _fake_db import OPENAI_TOOLS, QUESTION, SYSTEM, run_tool

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
        print('Mistral instrumentation not active — pip install "tracely-sdk[mistral]" mistralai')
        return
    if not os.environ.get("MISTRAL_API_KEY"):
        print("Set MISTRAL_API_KEY to make a real call.")
        return

    from mistralai import Mistral

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    messages: list = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]
    with tracely.trace(agent="support-agent", conversation=os.path.basename(__file__), user="ada@example.com", example=os.path.basename(__file__)):
        for _ in range(5):
            resp = client.chat.complete(
                model="mistral-large-latest", messages=messages, tools=OPENAI_TOOLS
            )
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {
                                "name": c.function.name,
                                "arguments": c.function.arguments,
                            },
                        }
                        for c in calls
                    ],
                }
            )
            if not calls:
                print("agent:", msg.content)
                break
            for call in calls:
                args = json.loads(call.function.arguments)
                result = run_tool(call.function.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "name": call.function.name,
                        "tool_call_id": call.id,
                        "content": json.dumps(result),
                    }
                )

    tracely.flush()
    print("sent — open Tracely → Traces: each generation + tool round-trip captured, no span code.")


if __name__ == "__main__":
    main()
