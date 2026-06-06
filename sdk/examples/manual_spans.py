"""Manual spans — the escape hatch as a FULL agent (PRD 12, L4).

When the auto path doesn't fit, hand-write spans. This is a complete support-agent run —
thinking → generation → tool calls against the fake DB (one tool ERRORS, the agent recovers) →
final answer. Runs with **no provider SDK or API key** (it instruments hypothetical calls).

    TRACELY_API=http://localhost:8000 uv run python sdk/examples/manual_spans.py

For the full manual cookbook (RAG, multi-agent handoffs, multimodal, …) see seed_conversations.py.
"""

from __future__ import annotations

import os

import _fake_db
import tracely_sdk as tracely
from _fake_db import QUESTION

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")

tracely.init(endpoint=API, api_key=KEY, service_name="support-agent", env="prod", instrument=False)


def main() -> None:
    with tracely.agent(
        "support-agent",
        version="v3",
        conversation="conv-1",
        turn=0,
        user="ada@example.com",
        trace_name="order + stock",
    ) as a:  # AGENT span = run root
        tracely.set_io(a, input=QUESTION)

        with tracely.thinking(agent="support-agent") as th:  # THINKING span
            tracely.set_io(
                th,
                output={
                    "role": "thinking",
                    "content": "Need the order status, then coat inventory, then summarize.",
                },
            )
            tracely.set_usage(th, thinking_tokens=40)

        with tracely.llm(  # GENERATION — the model requests both tools
            "gpt-4o",
            agent="support-agent",
            temperature=0.2,
            tool_calls=["get_order_status", "check_inventory"],
        ) as g:
            tracely.set_io(
                g,
                input=[{"role": "user", "content": QUESTION}],
                output={"role": "assistant", "content": None, "finish_reason": "tool_calls"},
            )
            tracely.set_usage(g, input_tokens=180, output_tokens=24)

        with tracely.tool("get_order_status", agent="support-agent") as t1:  # TOOL — succeeds
            tracely.set_io(
                t1, input={"order_id": "ORD-4471"}, output=_fake_db.get_order_status("ORD-4471")
            )

        with tracely.tool(
            "check_inventory", agent="support-agent"
        ) as t2:  # TOOL — errors + recovery
            tracely.set_io(t2, input={"sku": "SKU-COAT-01"})
            try:
                raise TimeoutError("inventory service timeout")
            except TimeoutError as e:
                tracely.error(
                    t2, f"inventory upstream timeout: {e}"
                )  # level=ERROR — the failure signal

        answer = (
            "Order ORD-4471 is out for delivery (today by 6pm). I couldn't reach the inventory "
            "service for the coat — please retry shortly."
        )
        with tracely.llm(
            "gpt-4o", agent="support-agent"
        ) as g2:  # GENERATION — final answer after recovery
            tracely.set_io(
                g2,
                input=[{"role": "user", "content": "summarize for the customer"}],
                output={"role": "assistant", "content": answer},
            )
            tracely.set_usage(g2, input_tokens=210, output_tokens=40)

        tracely.set_io(a, output=answer)

    tracely.flush()
    print(
        "sent — agent → thinking → llm → tools (one ERRORED) → llm. See the ERROR tool span in Tracely."
    )


if __name__ == "__main__":
    main()
