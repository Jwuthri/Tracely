"""AWS Bedrock — automatic tracing of a real tool-calling agent (PRD 12).

A support agent using Bedrock's `converse` tool use against the fake DB. `tracely.init()` activates
the Bedrock instrumentor; each `converse` call + tool round-trip is captured as a GENERATION span.
Bedrock is opt-in (`instrument=["bedrock"]`) — boto3 is too common to auto-detect.

    pip install "tracely-sdk[bedrock]" boto3
    export AWS_REGION=us-east-1   # + AWS credentials (env / profile / role)
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_bedrock.py
"""

from __future__ import annotations

import os

import tracely_sdk as tracely
from _fake_db import BEDROCK_TOOLS, QUESTION, SYSTEM, observed_tools

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

    @tracely.observe(as_type="agent")
    def support_agent(question: str) -> str:
        messages: list = [{"role": "user", "content": [{"text": question}]}]
        for _ in range(5):  # agentic loop: call tools until the model gives a final answer
            resp = client.converse(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
                system=[{"text": SYSTEM}],
                messages=messages,
                toolConfig={"tools": BEDROCK_TOOLS},
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
                        {
                            "toolResult": {
                                "toolUseId": tu["toolUseId"],
                                "content": [{"json": result}],
                            }
                        }
                    )
            messages.append({"role": "user", "content": results})
        return "(loop limit hit)"

    with tracely.trace(
        agent="support-agent",
        conversation=os.path.basename(__file__),
        user="ada@example.com",
        example=os.path.basename(__file__),
    ):
        print("agent:", support_agent(QUESTION))

    tracely.flush()
    print("sent — open Tracely → Traces: one AGENT run → converse generations + tool spans.")


if __name__ == "__main__":
    main()
