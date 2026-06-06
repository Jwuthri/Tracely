"""Google Gemini — automatic tracing of a tool-calling agent (PRD 12).

Uses the `google-genai` SDK's **automatic function calling**: pass the fake-DB functions as tools and
Gemini calls them itself. `tracely.init()` activates the Gemini instrumentor, so the generation +
the function calls are captured — no span code.

    pip install "tracely-sdk[google]" google-genai
    export GEMINI_API_KEY=...        # or GOOGLE_API_KEY
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_gemini.py
"""

from __future__ import annotations

import os

import tracely_sdk as tracely
from _fake_db import QUESTION, SYSTEM, check_inventory, get_order_status

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

# "gemini" is an alias for the canonical "google" provider.
tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["gemini"]
)


def main() -> None:
    if "google" not in tracely._instrumented:
        print('Gemini instrumentation not active — pip install "tracely-sdk[google]" google-genai')
        return
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        print("Set GEMINI_API_KEY (or GOOGLE_API_KEY) to make a real call.")
        return

    from google import genai
    from google.genai import types

    client = genai.Client()
    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=QUESTION,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                tools=[get_order_status, check_inventory],  # automatic function calling
            ),
        )
        print("agent:", resp.text)

    tracely.flush()
    print("sent — open Tracely → Traces: the generation + Gemini's tool calls, no span code.")


if __name__ == "__main__":
    main()
