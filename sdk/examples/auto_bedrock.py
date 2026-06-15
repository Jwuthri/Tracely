"""AWS Bedrock — automatic tracing of a two-agent conversation (PRD 12).

A Support Agent using Bedrock's `converse` tool use against the fake DB, handing the pricing turn to
a Billing Agent. `tracely.init()` activates the Bedrock instrumentor; each `converse` call + tool
round-trip is captured as a GENERATION span. Bedrock is opt-in (`instrument=["bedrock"]`) — boto3 is
too common to auto-detect.

    pip install "tracely-sdk[bedrock]" boto3
    export AWS_REGION=us-east-1   # + AWS credentials (env / profile / role)
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_bedrock.py
"""

from __future__ import annotations

import os

import tracely_sdk as tracely
from _fake_db import (
    AGENTS,
    BILLING_SYSTEM,
    BILLING_TOOLS,
    SUPPORT_TOOLS,
    SYSTEM,
    TURNS,
    bedrock_tools,
    observed_tools,
)

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=["bedrock"]
)


def main() -> None:
    if "bedrock" not in tracely._instrumented:
        print('Bedrock instrumentation not active — pip install "tracely-sdk[bedrock]" boto3')
        return
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if not region:
        print("Set AWS_REGION (+ AWS credentials) to make a real call.")
        return

    import boto3

    client = boto3.client("bedrock-runtime", region_name=region)
    tools = observed_tools()  # your tool fns, decorated once with @observe(as_type="tool")

    def run(question: str, system: str, tool_names: list[str]) -> str:
        """A normal converse tool-use loop. Each agent below is this loop with its own tools."""
        messages: list = [{"role": "user", "content": [{"text": question}]}]
        for _ in range(5):
            resp = client.converse(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
                system=[{"text": system}], messages=messages,
                toolConfig={"tools": bedrock_tools(tool_names)},
            )
            out_msg = resp["output"]["message"]
            messages.append(out_msg)
            if resp.get("stopReason") != "tool_use":
                return "".join(c.get("text", "") for c in out_msg["content"])
            results = []
            for block in out_msg["content"]:  # dispatch as usual — the decorator adds a TOOL span
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = tools[tu["name"]](**tu["input"])
                    results.append(
                        {"toolResult": {"toolUseId": tu["toolUseId"], "content": [{"json": result}]}}
                    )
            messages.append({"role": "user", "content": results})
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
    print("sent — a multi-turn, two-agent conversation → converse generations + tool spans.")


if __name__ == "__main__":
    main()
