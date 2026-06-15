"""Anthropic Claude Agent SDK — automatic tracing of a multi-turn conversation (PRD 12).

The Claude Agent SDK (`claude_agent_sdk`) runs Claude as a single autonomous agent with in-process
MCP tools. `tracely.init(instrument=["claude-agent-sdk"])` activates OpenInference's
`ClaudeAgentSDKInstrumentor`, which wraps `query()` / `ClaudeSDKClient.receive_response()` as AGENT
spans and tool calls as TOOL spans (via the SDK's PreToolUse/PostToolUse hooks).

One `ClaudeSDKClient` session handles the whole multi-turn conversation (so the agent remembers
earlier turns). This is the one example with a single agent — Claude is autonomous, so there's no
app-level handoff; the two-agent catalog is still declared via `agents=AGENTS`. The full two-agent
handoff is shown in `seed_multiturn.py`.

Requires the Claude Code CLI (`npm i -g @anthropic-ai/claude-code`) + an Anthropic key/subscription.
The SDK is async-only.

    pip install "tracely-sdk[claude-agent-sdk]" claude-agent-sdk
    export ANTHROPIC_API_KEY=sk-ant-...
    TRACELY_API=http://localhost:8000 uv run python sdk/examples/auto_claude_agent.py
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import AGENTS, TURNS

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=True)  # provider keys from the repo-root .env


API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(
    endpoint=API,
    api_key=KEY,
    service_name="support-agent",
    env="prod",
    instrument=["claude-agent-sdk"],
)


async def run() -> None:
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server, tool

    @tool("get_order_status", "Look up an order's delivery status and ETA by its order id", {"order_id": str})
    async def get_order_status(args: dict) -> dict:
        return {"content": [{"type": "text", "text": str(_fake_db.get_order_status(args["order_id"]))}]}

    @tool("check_inventory", "Check current stock level and price for a product SKU", {"sku": str})
    async def check_inventory(args: dict) -> dict:
        return {"content": [{"type": "text", "text": str(_fake_db.check_inventory(args["sku"]))}]}

    @tool("compare_prices", "Compare two SKUs' prices and report which is cheaper", {"sku_a": str, "sku_b": str})
    async def compare_prices(args: dict) -> dict:
        return {"content": [{"type": "text", "text": str(_fake_db.compare_prices(args["sku_a"], args["sku_b"]))}]}

    server = create_sdk_mcp_server(
        name="store", version="1.0.0", tools=[get_order_status, check_inventory, compare_prices]
    )
    options = ClaudeAgentOptions(
        mcp_servers={"store": server},
        allowed_tools=[
            "mcp__store__get_order_status",
            "mcp__store__check_inventory",
            "mcp__store__compare_prices",
        ],
    )
    conv = os.path.basename(__file__)
    # One client session handles the whole conversation (the agent remembers earlier turns); each
    # turn is its own trace under the same conversation, so the rolling summary accumulates.
    async with ClaudeSDKClient(options=options) as client:
        for i, (question, _slug) in enumerate(TURNS):
            with tracely.trace(
                agent="support-agent", conversation=conv, turn=i, user="ada@example.com",
                example=conv, agents=AGENTS if i == 0 else None,
            ):
                await client.query(question)
                async for message in client.receive_response():
                    print(message)


def main() -> None:
    if "claude-agent-sdk" not in tracely._instrumented:
        print('Claude Agent SDK not active — pip install "tracely-sdk[claude-agent-sdk]" claude-agent-sdk')
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY (and install the Claude Code CLI) to run.")
        return

    import anyio

    anyio.run(run)
    tracely.flush()
    print("sent — a multi-turn Claude Agent SDK conversation (AGENT) + tool spans.")


if __name__ == "__main__":
    main()
