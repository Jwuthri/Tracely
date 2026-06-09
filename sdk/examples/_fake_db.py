"""A tiny fake e-commerce 'database' + tools, shared by the example agents.

No real I/O — deterministic in-memory data so the examples are reproducible and free. The tool
functions are plain Python; each example wires them into its provider/harness's native tool-calling
format (the schemas below cover the common shapes). Import what you need:

    from _fake_db import QUESTION, OPENAI_TOOLS, observed_tools    # OpenAI / Mistral / LiteLLM
    from _fake_db import ANTHROPIC_TOOLS, BEDROCK_TOOLS            # Anthropic / Bedrock
    from _fake_db import get_order_status, check_inventory         # raw fns (Gemini / @observe)
"""

from __future__ import annotations

from typing import Any

# ── the "database" ───────────────────────────────────────────────────────────
ORDERS: dict[str, dict[str, Any]] = {
    "ORD-4471": {
        "status": "out_for_delivery",
        "eta": "today by 6pm",
        "items": ["SKU-COAT-01"],
        "customer": "ada@example.com",
    },
    "ORD-5588": {
        "status": "processing",
        "eta": "ships in ~2 days",
        "items": ["SKU-MUG-09"],
        "customer": "grace@example.com",
    },
}
INVENTORY: dict[str, dict[str, Any]] = {
    "SKU-COAT-01": {"name": "Alpine Winter Coat", "in_stock": 3, "price_usd": 129.0},
    "SKU-MUG-09": {"name": "Ceramic Mug", "in_stock": 0, "price_usd": 14.5},
}


# ── tools (plain Python — pass directly to frameworks that wrap them) ─────────
# Kept RAW (no @observe) so framework examples that auto-trace tool dispatch (LangChain `@tool`,
# LlamaIndex FunctionTool, CrewAI, OpenAI Agents SDK, Google ADK, Claude Agent SDK) don't get a
# duplicate inner TOOL span on top of the framework's own. Provider-SDK examples that dispatch
# tools themselves (OpenAI/Anthropic/Mistral/Bedrock/LiteLLM + drop-ins) build their dispatch map
# from `observed_tools()` below — the same fns decorated once with @observe(as_type="tool") — so
# each tool call becomes a real TOOL span under the agent root with no change at the call site.
def get_order_status(order_id: str) -> dict:
    """Look up an order's delivery status and ETA by its order id (e.g. ORD-4471)."""
    return ORDERS.get(order_id, {"error": f"no order {order_id}"})


def check_inventory(sku: str) -> dict:
    """Check current stock level and price for a product SKU (e.g. SKU-COAT-01)."""
    # tolerate both "SKU-COAT-01" and "COAT-01" — models often strip the prefix
    if sku in INVENTORY:
        return INVENTORY[sku]
    if f"SKU-{sku}" in INVENTORY:
        return INVENTORY[f"SKU-{sku}"]
    return {"error": f"no SKU {sku}"}


TOOL_IMPLS = {"get_order_status": get_order_status, "check_inventory": check_inventory}


_DESCRIPTIONS = {
    "get_order_status": "Look up an order's delivery status and ETA by its order id.",
    "check_inventory": "Check current stock level and price for a product SKU.",
}
_PARAMETERS: dict[str, dict] = {
    "get_order_status": {
        "type": "object",
        "properties": {"order_id": {"type": "string", "description": "e.g. ORD-4471"}},
        "required": ["order_id"],
    },
    "check_inventory": {
        "type": "object",
        "properties": {"sku": {"type": "string", "description": "e.g. SKU-COAT-01"}},
        "required": ["sku"],
    },
}

# ── per-format tool schemas (built from the shared definitions above) ──────────
# OpenAI / Mistral / LiteLLM
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {"name": n, "description": _DESCRIPTIONS[n], "parameters": _PARAMETERS[n]},
    }
    for n in TOOL_IMPLS
]
# Anthropic
ANTHROPIC_TOOLS = [
    {"name": n, "description": _DESCRIPTIONS[n], "input_schema": _PARAMETERS[n]} for n in TOOL_IMPLS
]
# AWS Bedrock (converse)
BEDROCK_TOOLS = [
    {
        "toolSpec": {
            "name": n,
            "description": _DESCRIPTIONS[n],
            "inputSchema": {"json": _PARAMETERS[n]},
        }
    }
    for n in TOOL_IMPLS
]

SYSTEM = "You are a customer-support agent. Use the tools to look up real data before answering; be concise."
QUESTION = "Where is my order ORD-4471, and is the Alpine Winter Coat (SKU-COAT-01) back in stock?"


def run_tool(name: str, args: dict) -> dict:
    """Dispatch a model-requested tool call to the raw fake-DB impls (no span)."""
    fn = TOOL_IMPLS.get(name)
    return fn(**args) if fn else {"error": f"unknown tool {name}"}


def observed_tools() -> dict:
    """The fake-DB tools, each wrapped with `@tracely.observe(as_type="tool")` — so a hand-rolled
    tool-calling loop auto-emits a TOOL span per call (input=args, output=result), nested under the
    agent run.

    This is the whole point: the ONLY change a user makes to trace their own tool calls is decorating
    their tool functions once — the dispatch stays exactly as they wrote it. Provider-SDK examples
    (OpenAI/Anthropic/Mistral/Bedrock/LiteLLM/Gemini + the drop-ins) build their dispatch map from
    this. Framework examples (LangChain/LlamaIndex/CrewAI/Agents SDKs) keep the raw `TOOL_IMPLS` so
    they don't double-trace on top of the framework's own tool spans."""
    import tracely_sdk as tracely

    return {name: tracely.observe(fn, name=name, as_type="tool") for name, fn in TOOL_IMPLS.items()}
