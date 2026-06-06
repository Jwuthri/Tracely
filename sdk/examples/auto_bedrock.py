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
from _fake_db import BEDROCK_TOOLS, QUESTION, SYSTEM, run_tool

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
    messages: list = [{"role": "user", "content": [{"text": QUESTION}]}]
    with tracely.trace(agent="support-agent", conversation="conv-1", user="ada@example.com"):
        for _ in range(5):
            resp = client.converse(
                modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
                system=[{"text": SYSTEM}],
                messages=messages,
                toolConfig={"tools": BEDROCK_TOOLS},
            )
            out_msg = resp["output"]["message"]
            messages.append(out_msg)
            if resp.get("stopReason") != "tool_use":
                print("agent:", "".join(c.get("text", "") for c in out_msg["content"]))
                break
            results = []
            for block in out_msg["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = run_tool(tu["name"], tu["input"])
                    results.append(
                        {
                            "toolResult": {
                                "toolUseId": tu["toolUseId"],
                                "content": [{"json": result}],
                            }
                        }
                    )
            messages.append({"role": "user", "content": results})

    tracely.flush()
    print("sent — open Tracely → Traces: each converse call + tool round-trip, no span code.")


if __name__ == "__main__":
    main()
