"""Anthropic — an orchestrator/worker agent system on the raw Claude API, traced by Tracely.

Anthropic's recommended way to build agents is directly on the Messages API
(see "Building effective agents"): a plain tool-use loop, with multi-agent
behavior expressed as an orchestrator that delegates scoped tasks to workers.
This demo builds exactly that:

  concierge (claude-opus-5)                     ── tools: get_order, check_inventory,
      │                                                   shipping_quote, escalate_refund
      └─ delegates via `escalate_refund` ──▶ refunds-specialist (sub-agent)
                                                ── runs the "refund-playbook" skill
                                                ── tools: get_order, issue_refund

Because there is no framework here, this demo shows Tracely's *manual* span
vocabulary on top of the automatic Anthropic instrumentation:

  - `tracely.init(instrument=["anthropic"])`  → every `messages.create` call is a
    GENERATION span, zero code.
  - `tracely.observe(as_type="tool")`         → each tool call is a TOOL span; the
    rejected $189 refund raises, so that span is marked ERROR — Tracely's
    failure-detection signal — while the agent recovers gracefully.
  - GUARDRAIL / DELEGATE / AGENT / SKILL spans → the injection check, the
    handoff edge, the sub-agent run and the playbook it followed all render as
    first-class observation types in the trace tree (via `tracely.guardrail`,
    `tracely.agent(handoff_from=…)` and `@tracely.observe(as_type=…)`).

Run:  uv run demo_anthropic.py        (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import anthropic
import tracely_sdk as tracely
from dotenv import load_dotenv

import shared

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)  # repo-root .env

tracely.init(
    endpoint=os.environ.get("TRACELY_API", "http://localhost:8000"),
    api_key=os.environ.get("TRACELY_KEY", "tracely_dev_key"),
    service_name="support-desk-anthropic",
    env="prod",
    instrument=["anthropic"],
)

MODEL = "claude-opus-5"
CONCIERGE = "claude-concierge"
SPECIALIST = "claude-refunds-specialist"
# fresh conversation id per run, so every run shows up as its own clean thread
CONVERSATION = time.strftime("anthropic-support-demo-%m%d-%H%M%S")

CONCIERGE_SYSTEM = (
    "You are the front-line support concierge for Nimbus Outfitters. Use your tools to "
    "answer with real data; never invent order or stock details. You cannot issue refunds "
    "yourself — for any refund request, hand the case to the refunds specialist with "
    "`escalate_refund` and relay their answer. Be concise and friendly."
)
SPECIALIST_SYSTEM = (
    "You are the refunds specialist for Nimbus Outfitters. Follow the refund playbook "
    "below exactly. Reply with a short resolution message for the customer.\n\n"
    + shared.REFUND_POLICY
)

ESCALATE_SCHEMA = {
    "description": "Hand a refund case to the refunds specialist (a sub-agent with its own tools).",
    "parameters": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "amount_usd": {"type": "number"},
            "reason": {"type": "string", "description": "why the customer wants a refund"},
        },
        "required": ["order_id", "amount_usd", "reason"],
    },
}


def anthropic_tools(names: list[str]) -> list[dict]:
    """shared.TOOL_SCHEMAS (+ escalate_refund) in Anthropic's tool format."""
    schemas = {**shared.TOOL_SCHEMAS, "escalate_refund": ESCALATE_SCHEMA}
    return [
        {"name": n, "description": schemas[n]["description"], "input_schema": schemas[n]["parameters"]}
        for n in names
    ]


client = anthropic.Anthropic()


# ── the standard tool-use loop (shared by both agents) ────────────────────────
def run_loop(system: str, tools: list[dict], impls: dict, messages: list[dict]) -> str:
    """Call Claude until it stops requesting tools; return the final text."""
    while True:
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=system, tools=tools, messages=messages
        )
        if response.stop_reason == "refusal":
            return "I'm sorry, I can't help with that request."
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return "".join(b.text for b in response.content if b.type == "text")
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                out = impls[block.name](**block.input)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out) if not isinstance(out, str) else out}
                )
            except shared.RefundPolicyError as e:
                # the TOOL span is already marked ERROR by @observe — Tracely
                # flags it; the agent sees the rejection and recovers.
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": str(e), "is_error": True}
                )
        messages.append({"role": "user", "content": results})


# ── tools: decorate once with @observe → every call becomes a TOOL span ───────
def observed(name: str):
    return tracely.observe(getattr(shared, name), name=name, as_type="tool")


@tracely.observe(as_type="skill", name="refund-playbook")
def run_refund_playbook(task: str) -> str:
    """The specialist's playbook run — a named SKILL span, so "which playbook
    handled this?" is a filter and a per-skill failure cluster in Tracely."""
    return run_loop(
        SPECIALIST_SYSTEM,
        anthropic_tools(["get_order", "issue_refund"]),
        {"get_order": observed("get_order"), "issue_refund": observed("issue_refund")},
        [{"role": "user", "content": task}],
    )


@tracely.observe(as_type="delegate", name=f"delegate:{SPECIALIST}")
def escalate_refund(order_id: str, amount_usd: float, reason: str) -> str:
    """The concierge → specialist handoff: a DELEGATE span wrapping the sub-agent's
    run, with `handoff_from` drawing the caller → callee edge in the agent graph."""
    task = f"Customer requests a ${amount_usd:.2f} refund on {order_id}: {reason}"
    with tracely.agent(SPECIALIST, handoff_from=CONCIERGE) as a:
        answer = run_refund_playbook(task)
        tracely.set_io(a, input=task, output=answer)
    return answer


CONCIERGE_IMPLS = {
    "get_order": observed("get_order"),
    "check_inventory": observed("check_inventory"),
    "shipping_quote": observed("shipping_quote"),
    "escalate_refund": escalate_refund,  # not a TOOL span — it emits its own DELEGATE/AGENT/SKILL spans
}

HISTORY: list[dict] = []  # clean user/assistant turns, threaded into every new turn


@tracely.observe(as_type="agent", name=CONCIERGE)
def concierge_turn(question: str) -> str:
    """One customer turn = one trace, rooted at this AGENT span."""
    # deterministic input guardrail — a first-class GUARDRAIL span in the trace
    blocked = shared.is_injection(question)
    with tracely.guardrail("prompt-injection-check", agent=CONCIERGE) as g:
        tracely.set_io(g, input=question, output={"action": "block" if blocked else "allow"})
    if blocked:
        return (
            "I can't act on instructions that try to override my policies. "
            "I'm happy to help with your order through the normal process."
        )
    return run_loop(
        CONCIERGE_SYSTEM,
        anthropic_tools(["get_order", "check_inventory", "shipping_quote", "escalate_refund"]),
        CONCIERGE_IMPLS,
        [*HISTORY, {"role": "user", "content": question}],
    )


# Declared catalog → Tracely's Conversation Agents panel shows the real setup
# (system prompts, models, tool schemas), not just the spans that happened to fire.
CATALOG = [
    shared.catalog_agent(
        CONCIERGE,
        "Front-line concierge; answers order/stock/shipping questions, escalates refunds.",
        ["get_order", "check_inventory", "shipping_quote"],
        system_prompt=CONCIERGE_SYSTEM,
        model=MODEL,
        guardrails=[{"name": "prompt-injection-check", "on": "input", "action": "block"}],
    ),
    shared.catalog_agent(
        SPECIALIST,
        "Refunds specialist; runs the refund playbook, consulted by the concierge.",
        ["get_order", "issue_refund"],
        system_prompt=SPECIALIST_SYSTEM,
        model=MODEL,
        skills=["refund-playbook v2"],
    ),
]
CATALOG[0]["tools"]["escalate_refund"] = {"name": "escalate_refund", **ESCALATE_SCHEMA}


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run this demo.")
        return
    for i, question in enumerate(shared.TURNS):
        with tracely.trace(
            agent=CONCIERGE,
            conversation=CONVERSATION,
            turn=i,
            user=shared.CUSTOMER,
            agents=CATALOG if i == 0 else None,
        ):
            answer = concierge_turn(question)
        HISTORY.extend(
            [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        )
        print(f"[turn {i}] {answer}\n")
    tracely.flush()
    print(f"done — open Tracely and look for conversation `{CONVERSATION}`.")


if __name__ == "__main__":
    main()
