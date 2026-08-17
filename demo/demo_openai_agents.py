"""OpenAI Agents SDK — triage + handoffs + guardrails + sessions, traced by Tracely.

The Agents SDK's native multi-agent primitives, used the way its docs recommend:

  triage ──handoff──▶ support        (tools: get_order, check_inventory, shipping_quote)
     │   ──handoff──▶ billing        (tools: issue_refund, consult_refund_policy)
     │                    └── uses policy-expert *as a tool* (agent.as_tool)
     └── input guardrail: trips on prompt injection (turn 4) and aborts the run

Also demonstrated: local context (a `CustomerContext` dataclass injected into
tools via `RunContextWrapper` — `get_order` verifies the order belongs to the
signed-in customer) and multi-turn memory via `SQLiteSession`.

Tracely integration is two lines: `tracely.init(instrument=["openai-agents"])`
activates the OpenInference instrumentor (every agent run, handoff, generation
and tool call becomes a span), and `tracely.trace(...)` stamps agent /
conversation / turn / user onto all of them. The declared agent catalog makes
the Conversation Agents panel show the full setup, including the guardrail —
which is otherwise invisible when it doesn't fire.

The $189 refund on turn 2 raises inside the `issue_refund` tool; the SDK's
default failure handling feeds the error back to the model, which recovers and
escalates — all visible in the trace.

Run:  uv run demo_openai_agents.py     (needs OPENAI_API_KEY)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

import tracely_sdk as tracely
from dotenv import load_dotenv

import shared

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)  # repo-root .env

tracely.init(
    endpoint=os.environ.get("TRACELY_API", "http://localhost:8000"),
    api_key=os.environ.get("TRACELY_KEY", "tracely_dev_key"),
    service_name="support-desk-openai-agents",
    env="prod",
    instrument=["openai-agents"],
)

from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    SQLiteSession,
    TResponseInputItem,
    function_tool,
    handoff,
    input_guardrail,
)
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

# fresh conversation id per run, so every run shows up as its own clean thread
CONVERSATION = time.strftime("openai-agents-support-demo-%m%d-%H%M%S")


# ── local context: injected into tools, never sent to the model ───────────────
@dataclass
class CustomerContext:
    email: str


# ── tools (docstrings become the tool schemas) ────────────────────────────────
@function_tool
def get_order(ctx: RunContextWrapper[CustomerContext], order_id: str) -> dict:
    """Look up an order's status, items and total by order id.

    Args:
        order_id: The order id, e.g. ORD-1042.
    """
    order = shared.get_order(order_id)
    if "customer" in order and order["customer"] != ctx.context.email:
        return {"error": "that order belongs to a different customer"}
    return order


@function_tool
def check_inventory(sku: str) -> dict:
    """Check stock level and price for a product SKU.

    Args:
        sku: The product SKU, e.g. SKU-PACK-02.
    """
    return shared.check_inventory(sku)


@function_tool
def shipping_quote(sku: str, country: str) -> dict:
    """Quote shipping cost and delivery time for a SKU to a country.

    Args:
        sku: The product SKU.
        country: Destination country.
    """
    return shared.shipping_quote(sku, country)


@function_tool
def issue_refund(order_id: str, amount_usd: float) -> dict:
    """Issue a refund. The payments system rejects amounts above the auto-approval limit.

    Args:
        order_id: The order to refund.
        amount_usd: Refund amount in USD.
    """
    # Over the limit this raises; the SDK's default failure handler returns the
    # error to the model, which then follows the playbook and escalates.
    return shared.issue_refund(order_id, amount_usd)


# ── input guardrail: deterministic prompt-injection tripwire ──────────────────
@input_guardrail
async def injection_guardrail(
    ctx: RunContextWrapper[CustomerContext], agent: Agent, input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    text = input if isinstance(input, str) else " ".join(str(item) for item in input)
    hit = shared.is_injection(text)
    return GuardrailFunctionOutput(output_info={"injection": hit}, tripwire_triggered=hit)


# ── the agents ────────────────────────────────────────────────────────────────
# model= is omitted → the SDK's cost-efficient default model.
policy_expert = Agent(
    name="policy-expert",
    instructions=(
        "You answer questions about Nimbus Outfitters' refund policy, using only this "
        "playbook:\n\n" + shared.REFUND_POLICY
    ),
)

support_agent = Agent[CustomerContext](
    name="support",
    handoff_description="Order status, inventory and shipping questions.",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX}\nYou are the Nimbus Outfitters support agent. "
        "Use your tools to answer with real data; never invent details. Be concise."
    ),
    tools=[get_order, check_inventory, shipping_quote],
)

billing_agent = Agent[CustomerContext](
    name="billing",
    handoff_description="Refunds and billing issues.",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX}\nYou are the Nimbus Outfitters billing agent. "
        "Consult the refund policy first, then use issue_refund. If the payments system "
        "rejects a refund, apologize and escalate to a human manager (~1 business day)."
    ),
    tools=[
        get_order,
        issue_refund,
        # a whole agent exposed as a single tool — the sub-agent-as-tool pattern
        policy_expert.as_tool(
            tool_name="consult_refund_policy",
            tool_description="Ask the policy expert a question about the refund policy.",
        ),
    ],
)

triage_agent = Agent[CustomerContext](
    name="triage",
    instructions=(
        f"{RECOMMENDED_PROMPT_PREFIX}\nYou are the Nimbus Outfitters triage agent. Route "
        "order/stock/shipping questions to support and refund/billing questions to billing."
    ),
    handoffs=[
        support_agent,
        handoff(billing_agent, tool_description_override="Refund or billing request."),
    ],
    input_guardrails=[injection_guardrail],
)

CATALOG = [
    shared.catalog_agent(
        "triage", "Routes each customer turn to the right specialist.", [],
        system_prompt=triage_agent.instructions,
        handoffs=["support", "billing"],
        guardrails=[{"name": "injection_guardrail", "on": "input", "action": "block"}],
    ),
    shared.catalog_agent(
        "support", "Order status, inventory and shipping.",
        ["get_order", "check_inventory", "shipping_quote"],
        system_prompt=support_agent.instructions,
    ),
    shared.catalog_agent(
        "billing", "Refunds and billing; consults the policy expert.", ["get_order", "issue_refund"],
        system_prompt=billing_agent.instructions,
    ),
    shared.catalog_agent(
        "policy-expert", "Answers refund-policy questions; used by billing as a tool.", [],
        system_prompt=policy_expert.instructions,
    ),
]


# The name and per-turn entry point the FastAPI server (server.py) drives.
AGENT = "oa-triage"
_sessions: dict[str, SQLiteSession] = {}  # one SQLiteSession per conversation, kept across turns


async def reply(message: str, history: list[dict] | None = None, conversation_id: str = "mara") -> str:
    """One turn for server.py — a cached SQLiteSession threads history server-side (history arg
    unused). The injection guardrail on turn 4 trips the same way it does in the script."""
    key = conversation_id or "mara"
    session = _sessions.get(key) or _sessions.setdefault(key, SQLiteSession(key))
    context = CustomerContext(email=shared.CUSTOMER)
    try:
        result = await Runner.run(triage_agent, message, session=session, context=context)
        return str(result.final_output)
    except InputGuardrailTripwireTriggered:
        return (
            "Blocked by the input guardrail: that message tries to override my "
            "policies. Happy to help through the normal process."
        )


async def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run this demo.")
        return
    session = SQLiteSession("mara")  # in-memory; the SDK threads history across turns
    context = CustomerContext(email=shared.CUSTOMER)
    for i, question in enumerate(shared.TURNS):
        with tracely.trace(
            agent="oa-triage",
            conversation=CONVERSATION,
            turn=i,
            user=shared.CUSTOMER,
            agents=CATALOG if i == 0 else None,
        ):
            try:
                result = await Runner.run(triage_agent, question, session=session, context=context)
                answer = str(result.final_output)
            except InputGuardrailTripwireTriggered:
                answer = (
                    "Blocked by the input guardrail: that message tries to override my "
                    "policies. Happy to help through the normal process."
                )
        print(f"[turn {i}] {answer}\n")
    tracely.flush()
    print(f"done — open Tracely and look for conversation `{CONVERSATION}`.")


if __name__ == "__main__":
    asyncio.run(main())
