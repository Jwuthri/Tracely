"""Google Gemini — automatic tracing of a real tool-calling agent (PRD 12).

A support agent answers a multi-part question with Gemini's function calling against the fake DB,
then summarizes. `tracely.init()` activates the Gemini instrumentor, so each `generate_content`
call is captured automatically as a GENERATION span — **no span code on the LLM calls**. One
`@observe(as_type="agent")` on the loop gives the run a single AGENT root so the generations + tool
spans land in one trace tree; we disable the SDK's *automatic* function calling and dispatch the
tools ourselves — the tool fns are decorated with `@observe(as_type="tool")`, so each tool round-trip
is a TOOL span (generation → tools → generation), matching the framework examples.

    pip install "tracely-sdk[google]" google-genai
    export GEMINI_API_KEY=...        # or GOOGLE_API_KEY
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_gemini.py
"""

from __future__ import annotations

import os

import tracely_sdk as tracely
from _fake_db import QUESTION, SYSTEM, check_inventory, get_order_status, observed_tools

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


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
    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        tools=[get_order_status, check_inventory],  # the SDK builds tool schemas from the fns
        # disable the SDK's auto-calling so WE dispatch the tools — each becomes a TOOL span
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        contents: list = [types.Content(role="user", parts=[types.Part(text=question)])]
        for _ in range(5):  # agentic loop: call tools until Gemini gives a final answer
            resp = client.models.generate_content(
                model="gemini-3.1-flash-lite", contents=contents, config=config
            )
            calls = resp.function_calls or []
            if not calls:
                return resp.text or ""
            contents.append(resp.candidates[0].content)  # the model's function-call turn
            parts = []
            for fc in calls:  # dispatch as usual — the decorator makes each a TOOL span
                result = tools[fc.name](**dict(fc.args))
                parts.append(
                    types.Part.from_function_response(name=fc.name, response={"result": result})
                )
            contents.append(types.Content(role="user", parts=parts))
        return "(loop limit hit)"

    with tracely.trace(
        agent="support-agent",
        conversation=os.path.basename(__file__),
        user="ada@example.com",
        example=os.path.basename(__file__),
    ):
        print("agent:", support_agent(QUESTION))

    tracely.flush()
    print("sent — open Tracely → Traces: one AGENT run → generations + tool spans, no span code.")


if __name__ == "__main__":
    main()
