"""Emit ONE cinematic conversation for the Fleet office view, using the real SDK spans it
renders: agents + a sub-agent, DELEGATE handovers (walk + speech bubble), a SKILL (library),
THINKING (thought cloud), action tools (computer), a knowledge tool (library) and one failure.

    uv run python scripts/demo_fleet.py            # prints the thread id
"""

from __future__ import annotations

import os
import random
import time

import tracely_sdk as tracely
from tracely_sdk import set_io, set_usage

AGENTS = [
    {
        "name": "concierge",
        "description": "Front-of-house orchestrator: understands the guest, routes work to the "
        "right specialist, owns the final reply.",
        "tools": [{"name": "send_reply"}],
    },
    {
        "name": "billing",
        "description": "Refunds, invoices and card operations. Never guesses an amount.",
        "tools": [{"name": "fetch_invoice"}, {"name": "issue_refund"}],
    },
    {
        "name": "researcher",
        "description": "Digs through the knowledge base and warranty policies.",
        "tools": [{"name": "lookup_kb"}],
    },
]


def llm(agent: str, ms: int, prompt: str, answer: str, model: str = "gpt-5.4-mini") -> None:
    with tracely.llm(model, agent=agent) as g:
        set_io(
            g,
            input=[{"role": "user", "content": prompt}],
            output=[{"role": "assistant", "content": answer}],
        )
        set_usage(
            g,
            input_tokens=random.randrange(200, 900),
            output_tokens=random.randrange(40, 200),
        )
        time.sleep(ms / 1000)


def main() -> None:
    thread = f"fleet-{random.randrange(10**6):06d}"
    tracely.init(
        endpoint=os.environ.get("TRACELY_API", "http://localhost:8000"),
        api_key=os.environ.get("TRACELY_KEY", "tracely_dev_key"),
        service_name="demo-fleet",
        instrument=False,
    )

    # ── turn 1: guest asks; concierge thinks, reads a skill, delegates to the researcher ──
    with tracely.trace(agent="concierge", conversation=thread, turn=0, agents=AGENTS):
        with tracely.agent("concierge", conversation=thread) as root:
            set_io(
                root,
                input="My order #4471 arrived broken. What are my options?",
                output="A replacement is on the way — refund also possible.",
            )
            with tracely.thinking(agent="concierge") as th:
                set_io(th, output="Broken item → warranty question first, then remediation.")
                time.sleep(0.4)
            with tracely.skill("damaged-goods-playbook", agent="concierge", version="v3") as sk:
                set_io(
                    sk,
                    input="broken on arrival",
                    output="steps: verify warranty → offer swap/refund",
                )
                time.sleep(0.55)
            llm("concierge", 500, "route this", "Researcher should check the warranty.")
            with tracely.delegate(
                "researcher", agent="concierge", task="Check warranty for order #4471 (Aero 14 Air)"
            ) as d:
                set_io(d, input="Check warranty for order #4471 (Aero 14 Air)")
                with tracely.agent("researcher", conversation=thread, handoff_from="concierge"):
                    llm("researcher", 420, "warranty?", "Looking it up.", model="claude-3-5-sonnet")
                    with tracely.retriever("lookup_kb", agent="researcher") as t:
                        set_io(
                            t,
                            input={"q": "Aero 14 Air warranty"},
                            output="24 months, covers transit damage",
                        )
                        time.sleep(0.5)
                    llm("researcher", 380, "summarize", "Covered: 24-month warranty incl. transit.")
            llm("concierge", 450, "reply", "Good news — fully covered. Replacement or refund?")

    time.sleep(1.2)

    # ── turn 2: guest picks refund; concierge delegates to billing, whose card tool fails once ──
    with tracely.trace(agent="concierge", conversation=thread, turn=1, agents=AGENTS):
        with tracely.agent("concierge", conversation=thread) as root:
            set_io(root, input="Refund please.", output="Refund of $1,299 issued.")
            with tracely.thinking(agent="concierge") as th:
                set_io(th, output="Refund path → billing owns this.")
                time.sleep(0.3)
            with tracely.delegate(
                "billing", agent="concierge", task="Refund order #4471 in full to the original card"
            ) as d:
                set_io(d, input="Refund order #4471 in full to the original card")
                with tracely.agent("billing", conversation=thread, handoff_from="concierge"):
                    with tracely.tool("fetch_invoice", agent="billing") as t:
                        set_io(t, input={"order": "4471"}, output={"total": 1299})
                        time.sleep(0.35)
                    with tracely.tool("issue_refund", agent="billing") as t:
                        set_io(t, input={"amount": 1299})
                        tracely.error(t, "card processor 503 — retrying")
                        time.sleep(0.45)
                    llm("billing", 300, "retry?", "Processor hiccup — retrying once.")
                    with tracely.tool("issue_refund", agent="billing") as t:
                        set_io(t, input={"amount": 1299}, output={"refund_id": "rf_88213"})
                        time.sleep(0.4)
            llm("concierge", 400, "reply", "Done — $1,299 back on your card within 3 days.")

    tracely.flush()
    print(thread)


if __name__ == "__main__":
    main()
