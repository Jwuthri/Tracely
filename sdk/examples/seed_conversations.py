"""Seed rich, detailed demo conversations for the Threads / trace-table view.

Covers every shape the table renders:
  • multi-turn conversations (conversation_id groups turns; each turn is its own trace)
  • multi-agent runs (a router agent delegating to specialist sub-agents in one turn)
  • THINKING steps (first-class reasoning spans with reasoning-token usage)
  • tools with real JSON arguments + JSON results
  • generations that emit structured (output-schema) JSON
  • multimodal user messages (text + image + file content blocks)
  • a realistic pass/fail mix that exercises the auto-evaluators:
      - tool error      -> run.outcome FAIL + tool.success FAIL
      - hallucination   -> llm-judge quality FAIL (answer contradicts tool result)
      - missing tool    -> tool_consistency FAIL (requested but not executed)

    TRACELY_API=http://localhost:8088 uv run python sdk/examples/seed_conversations.py
"""

from __future__ import annotations

import os
import time
import uuid

import tracely_sdk as tracely

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")
tracely.init(endpoint=API, api_key=KEY, service_name="support-agent", env="prod")


# ── small helpers over the SDK ───────────────────────────────────────────────
def think(agent: str, text: str, tokens: int = 90, *, model: str = "gpt-4o"):
    with tracely.thinking(agent=agent, model=model) as t:
        tracely.set_io(t, output=text)
        tracely.set_usage(t, thinking_tokens=tokens)
        time.sleep(0.08)


def gen(agent: str, messages, output, in_tok: int, out_tok: int, *, model: str = "gpt-4o",
        think_tok: int | None = None, tool_calls=None, temperature: float = 0.7, top_p: float = 1.0,
        max_tokens: int = 1024, metadata: dict | None = None):
    # LLM sampling params (temperature/top_p/max_tokens) are recorded as gen_ai.request.* and shown
    # in the generation's Metadata; `metadata` adds arbitrary tags (e.g. prompt version).
    meta = {"prompt_version": "v3", "decoding": "sampling", **(metadata or {})}
    with tracely.llm(model, agent=agent, temperature=temperature, top_p=top_p, max_tokens=max_tokens,
                     seed=7, metadata=meta) as g:
        # An LLM generation's input is a bare message array (Array<{role, content}>) so the
        # frontend ChatPill triggers. Output is the structured completion object (role / content /
        # finish_reason), like the chat-completions API returns — not a bare string. A dict output
        # (e.g. an output-schema result) is emitted as-is.
        out_obj = output if not isinstance(output, str) else {"role": "assistant", "content": output, "finish_reason": "stop"}
        tracely.set_io(g, input=messages, output=out_obj)
        tracely.set_usage(g, input_tokens=in_tok, output_tokens=out_tok, thinking_tokens=think_tok)
        if tool_calls:
            g.set_attribute("tracely.tool_calls", list(tool_calls))
        # Simulate realistic LLM latency so the span has a meaningful duration.
        latency = max(0.15, in_tok * 0.0004 + out_tok * 0.0012)
        time.sleep(latency)


def use_tool(name: str, agent: str, args, result=None, *, error: str | None = None):
    with tracely.tool(name, agent=agent) as t:
        tracely.set_io(t, input=args)
        if error:
            tracely.error(t, error)
        else:
            tracely.set_io(t, output=result)
        time.sleep(0.12)  # simulate round-trip to the tool


def sys_user(system: str, user) -> list:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def as_content(text: str | None = None, *, images: list[str] | None = None, files: list[tuple] | None = None) -> list:
    """Canonical message-level content: a list of typed blocks (text / image / file) — so a
    message is ALWAYS a self-describing object, never a bare string (we can't know up front
    whether it's text, an image, a file, or a mix). `images` are url/path strings; `files` are
    (filename, url_or_path, mime_type) tuples."""
    blocks: list = []
    if text:
        blocks.append({"type": "text", "text": text})
    for url in images or []:
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    for f in files or []:
        name, url = f[0], f[1]
        mime = f[2] if len(f) > 2 else "application/octet-stream"
        blocks.append({"type": "input_file", "filename": name, "url": url, "mime_type": mime})
    return blocks


def turn_io(span, user, assistant) -> None:
    """Set a turn's (message-level) user input + assistant output as structured MESSAGE OBJECTS —
    `{"role": ..., "content": [content blocks]}` — never bare strings. Content is always a typed
    block list (text/image/file), so a message is self-describing regardless of modality."""
    u = user if isinstance(user, list) else as_content(user)
    a = assistant if isinstance(assistant, list) else as_content(assistant)
    tracely.set_io(
        span,
        input={"role": "user", "content": u},
        output={"role": "assistant", "content": a},
    )


SHOP = "shopping-assistant"
SUPPORT = "support-agent"

seeded: list[str] = []


# ── 1) Laptop recommendation — 3 turns · thinking · structured output · real tool args (PASS) ──
def seed_laptop():
    conv = "conv-" + uuid.uuid4().hex[:8]

    # turn 0
    with tracely.agent(SHOP, version="v3", conversation=conv, turn=0) as a:
        u0 = "I need a laptop for college. Budget is $800-1000, and battery life matters."
        ans0 = ("For your budget I'd go with the **Aero 14 Air** ($949) — 18-hour battery, 1.29 kg, "
                "16 GB / 512 GB. The Nimbus 13 Lite ($829) is a lighter, cheaper runner-up.")
        turn_io(a, u0, ans0)
        gen(SHOP, sys_user("Classify the shopper's intent into the schema.", u0),
            {"intent": "product_recommendation", "category": "laptop",
             "budget_usd": {"min": 800, "max": 1000}, "priorities": ["battery_life", "portability"]},
            96, 44, model="gpt-4o-mini")
        think(SHOP, "Budget $800-1000, prioritise battery + weight. Query the catalog sorted by rating, "
                    "then compare battery_hours before recommending.", 120)
        use_tool("search_catalog", SHOP,
                 {"category": "laptop", "price_min": 800, "price_max": 1000, "sort": "rating_desc"},
                 {"count": 3, "results": [
                     {"sku": "LP-14-AIR", "name": "Aero 14 Air", "price": 949, "rating": 4.6},
                     {"sku": "LP-15-PRO", "name": "Vertex 15 Pro", "price": 999, "rating": 4.4},
                     {"sku": "LP-13-LITE", "name": "Nimbus 13 Lite", "price": 829, "rating": 4.5}]})
        use_tool("get_product", SHOP, {"sku": "LP-14-AIR"},
                 {"sku": "LP-14-AIR", "battery_hours": 18, "weight_kg": 1.29, "ram_gb": 16,
                  "storage_gb": 512, "display": '14" 2.5K'})
        gen(SHOP, sys_user("You are a concise shopping assistant. Recommend from the catalog.", u0),
            ans0, 540, 96)

    time.sleep(1.4)  # user reading + typing between turns

    # turn 1
    with tracely.agent(SHOP, version="v3", conversation=conv, turn=1) as a:
        u1 = "How's the battery on the Aero compared to the Vertex?"
        ans1 = "The Aero 14 Air lasts ~18 h vs ~11 h on the Vertex 15 Pro — clear win for the Aero."
        turn_io(a, u1, ans1)
        # Fetch BOTH products this turn so every figure in the answer is grounded in this turn's
        # tool results (the per-turn judge can't see turn 0's lookups).
        use_tool("get_product", SHOP, {"sku": "LP-14-AIR"},
                 {"sku": "LP-14-AIR", "battery_hours": 18, "weight_kg": 1.29, "ram_gb": 16, "storage_gb": 512})
        use_tool("get_product", SHOP, {"sku": "LP-15-PRO"},
                 {"sku": "LP-15-PRO", "battery_hours": 11, "weight_kg": 1.7, "ram_gb": 16, "storage_gb": 1024})
        # Full transcript (history) as the generation input -> step Input renders the whole conversation.
        gen(SHOP, [{"role": "system", "content": "You are a concise shopping assistant."},
                   {"role": "user", "content": u0}, {"role": "assistant", "content": ans0},
                   {"role": "user", "content": u1}], ans1, 380, 60)

    time.sleep(1.1)  # user reading + typing between turns

    # turn 2
    with tracely.agent(SHOP, version="v3", conversation=conv, turn=2) as a:
        u2 = "Great — add the Aero to my cart."
        ans2 = "Done! The Aero 14 Air is in your cart (CART-5582) — subtotal $949.00."
        turn_io(a, u2, ans2)
        use_tool("add_to_cart", SHOP, {"sku": "LP-14-AIR", "qty": 1},
                 {"cart_id": "CART-5582", "items": 1, "subtotal_usd": 949.0})
        gen(SHOP, sys_user("Confirm the cart action.", u2), ans2, 210, 38)

    seeded.append(f"{conv}  laptop recommendation (3 turns)")
    return conv


# ── 2) Order issue — 2 turns · MULTI-AGENT router→specialists (turn 0 FAILS: billing timeout) ──
def seed_order_issue():
    conv = "conv-" + uuid.uuid4().hex[:8]

    # turn 0 — router delegates to shipping-agent (ok) then billing-agent (tool error)
    with tracely.agent("router", version="v2", role="orchestrator", conversation=conv, turn=0) as root:
        u0 = "Where is my order ORD-4471, and why was I charged twice?"
        ans0 = ("Your order ORD-4471 is in transit (ETA Jun 8). I couldn't reach billing to verify the "
                "duplicate charge just now — I've flagged it and we'll follow up shortly.")
        turn_io(root, u0, ans0)
        think("router", "Two intents: (1) shipment status, (2) possible double charge. Delegate shipping "
                        "to shipping-agent and billing to billing-agent, then merge.", 110)

        with tracely.agent("shipping-agent", role="specialist", conversation=conv):
            use_tool("track_shipment", "shipping-agent", {"order_id": "ORD-4471"},
                     {"status": "in_transit", "carrier": "UPS", "eta": "2026-06-08", "last_scan": "Memphis, TN"})
            gen("shipping-agent", sys_user("Summarise the shipment for the customer.", u0),
                "Order ORD-4471 is in transit with UPS, ETA Jun 8 (last scan Memphis, TN).", 220, 48)

        with tracely.agent("billing-agent", role="specialist", conversation=conv):
            use_tool("get_charges", "billing-agent", {"order_id": "ORD-4471"},
                     error="billing upstream timeout (504) after 3 retries")

        gen("router", sys_user("Merge the specialists' findings into one answer.", u0), ans0, 610, 90, think_tok=70)

    time.sleep(1.8)  # user reading + composing follow-up

    # turn 1 — refund succeeds (PASS)
    with tracely.agent("billing-agent", version="v2", role="specialist", conversation=conv, turn=1) as a:
        u1 = "Please just refund the duplicate $49.99 charge."
        ans1 = "Refund of $49.99 started (RF-7741) — it'll post to your card in 3-5 business days."
        turn_io(a, u1, ans1)
        use_tool("issue_refund", "billing-agent", {"order_id": "ORD-4471", "amount_usd": 49.99, "reason": "duplicate_charge"},
                 {"refund_id": "RF-7741", "status": "pending", "eta_days": "3-5"})
        gen("billing-agent", sys_user("Confirm the refund.", u1), ans1, 260, 52)

    seeded.append(f"{conv}  order issue · multi-agent (2 turns, turn 0 fails)")
    return conv


# ── 3) Multimodal return — 1 turn · user sends text + image + file (PASS) ──
def seed_multimodal():
    conv = "conv-" + uuid.uuid4().hex[:8]
    with tracely.agent(SUPPORT, version="v4", conversation=conv, turn=0) as a:
        user_msg = as_content(
            "My order arrived with a cracked screen — photo and receipt attached. I'd like a replacement.",
            images=["https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=240"],
            files=[("receipt-ORD-4471.pdf", "https://files.tracely.dev/uploads/receipt-ORD-4471.pdf", "application/pdf")],
        )
        ans = ("So sorry about the cracked screen! I've opened a free replacement (RMA-2208) and emailed a "
               "prepaid return label. Your replacement ships as soon as the carrier scans the return.")
        turn_io(a, user_msg, ans)
        think(SUPPORT, "User reports damage with photo + receipt. Verify the order exists, then open a "
                       "damage return and generate a prepaid label.", 95)
        use_tool("lookup_order", SUPPORT, {"order_id": "ORD-4471"},
                 {"order_id": "ORD-4471", "item": "Aero 14 Air", "delivered": True, "delivered_at": "2026-06-02"})
        use_tool("start_return", SUPPORT, {"order_id": "ORD-4471", "reason": "damaged_on_arrival", "resolution": "replacement"},
                 {"rma": "RMA-2208", "label_url": "https://ship.example.com/labels/RMA-2208.pdf", "fee_usd": 0})
        # The generation sees the same multimodal user message (text + image + file) — so the
        # step's Input renders a conversation whose user bubble carries the attachment chips.
        gen(SUPPORT, [{"role": "system", "content": "You are a returns specialist. Be empathetic and resolve damage claims."},
                      {"role": "user", "content": user_msg}], ans, 480, 102, think_tok=60)
    seeded.append(f"{conv}  multimodal return (text+image+file)")
    return conv


# ── 4) Hallucination — 1 turn · answer contradicts the tool result (judge FAIL) ──
def seed_hallucination():
    conv = "conv-" + uuid.uuid4().hex[:8]
    with tracely.agent(SHOP, version="v3", conversation=conv, turn=0) as a:
        u = "Is the Aero 14 Air in stock? I need it this week."
        ans = "Good news — the Aero 14 Air is in stock and ships today! 🎉"  # contradicts the tool
        turn_io(a, u, ans)
        use_tool("check_inventory", SHOP, {"sku": "LP-14-AIR"},
                 {"sku": "LP-14-AIR", "in_stock": False, "available": 0, "restock_eta": "2026-07-01"})
        gen(SHOP, sys_user("Answer the stock question from the tool result.", u), ans, 240, 40)
    seeded.append(f"{conv}  hallucination (judge fail)")
    return conv


# ── 5) Missing tool — 1 turn · model says it called a tool it never executed (consistency FAIL) ──
def seed_missing_tool():
    conv = "conv-" + uuid.uuid4().hex[:8]
    with tracely.agent(SUPPORT, version="v4", conversation=conv, turn=0) as a:
        u = "What's my current account balance?"
        ans = "Your current account balance is $12.40."
        turn_io(a, u, ans)
        think(SUPPORT, "Need the live balance — should call get_account_balance before answering.", 40)
        # The generation claims a tool call, but no get_account_balance TOOL span is emitted.
        gen(SUPPORT, sys_user("Look up and report the account balance.", u), ans, 180, 30,
            tool_calls=["get_account_balance"])
    seeded.append(f"{conv}  missing tool (consistency fail)")
    return conv


# ── 6) Quick FAQ — 1 turn · trivial (PASS) ──
def seed_faq():
    conv = "conv-" + uuid.uuid4().hex[:8]
    with tracely.agent(SUPPORT, version="v4", conversation=conv, turn=0) as a:
        u = "What are your support hours?"
        ans = "We're here 24/7 via chat, and 8 am-8 pm ET by phone."
        turn_io(a, u, ans)
        gen(SUPPORT, sys_user("Answer the FAQ.", u), ans, 90, 28)
    seeded.append(f"{conv}  quick FAQ")
    return conv


# ── 7) Warranty claim — 1 turn · user attaches an IMAGE (url) + a DOCUMENT (url) (PASS) ──
# The user message carries an image block (url/path) and a file block (url/path to the doc) —
# the message-level Content cell renders the text plus an image thumbnail + a file chip.
def seed_attachments():
    conv = "conv-" + uuid.uuid4().hex[:8]
    img_url = "https://picsum.photos/seed/tracely-damage/320/200"          # image attachment (url/path)
    doc_url = "https://files.tracely.dev/uploads/warranty-claim-ORD-4471.pdf"  # document attachment (url/path)
    with tracely.agent(SUPPORT, version="v4", conversation=conv, turn=0) as a:
        user_msg = as_content(
            "Here's the photo of the damaged item and the signed warranty claim form — please process a replacement.",
            images=[img_url],
            files=[("warranty-claim-ORD-4471.pdf", doc_url, "application/pdf")],
        )
        ans = ("Thanks for the photo and the warranty form! I've logged both to claim WC-3391 and approved a "
               "free replacement — it ships within 2 business days. You'll get tracking by email.")
        turn_io(a, user_msg, ans)
        think(SUPPORT, "User attached an image + a PDF. Run vision on the image, parse the form, verify warranty, "
                       "then open + approve a warranty claim.", 95)
        use_tool("vision_inspect", SUPPORT, {"image_url": img_url},
                 {"defect": "cracked_screen", "confidence": 0.97, "region": "top-left"})
        use_tool("parse_document", SUPPORT, {"file_url": doc_url},
                 {"order_id": "ORD-4471", "purchase_date": "2026-05-20", "warranty_valid": True, "signed": True})
        use_tool("create_warranty_claim", SUPPORT,
                 {"order_id": "ORD-4471", "defect": "cracked_screen", "resolution": "replacement",
                  "evidence": {"image": img_url, "document": doc_url}},
                 {"claim_id": "WC-3391", "status": "approved", "ship_eta_days": 2})
        # The generation sees the same multimodal user message (text + image + file).
        gen(SUPPORT, [{"role": "system", "content": "You are a warranty specialist. Verify evidence, then resolve."},
                      {"role": "user", "content": user_msg}], ans, 560, 96, think_tok=60)
    seeded.append(f"{conv}  warranty claim (image + document attachments)")
    return conv


if __name__ == "__main__":
    seed_laptop()
    seed_order_issue()
    seed_multimodal()
    seed_hallucination()
    seed_missing_tool()
    seed_faq()
    seed_attachments()
    tracely.flush()
    print(f"seeded {len(seeded)} conversations:")
    for line in seeded:
        print("  •", line)
