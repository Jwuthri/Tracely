"""Emit ONE rich conversation for the replay stage: several agents, a nested sub-agent,
tool calls and a failure — the shape the replay view exists to show.

    uv run python scripts/demo_conversation.py            # prints the thread id
    TRACELY_KEY=<key> uv run python scripts/demo_conversation.py
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.request

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, InstrumentationScope, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span

API = os.environ.get("TRACELY_API", "http://localhost:8000")
KEY = os.environ.get("TRACELY_KEY", "tracely_dev_key")
MS = 1_000_000


def kv(k: str, v) -> KeyValue:
    if isinstance(v, int):
        return KeyValue(key=k, value=AnyValue(int_value=v))
    return KeyValue(key=k, value=AnyValue(string_value=str(v)))


class Turn:
    """Builds one trace (one turn) of the conversation."""

    def __init__(self, thread: str, t0: int):
        self.thread, self.t0, self.spans, self.n = thread, t0, [], 0

    def _id(self) -> bytes:
        self.n += 1
        return self.n.to_bytes(8, "big")

    def span(self, *, name, otype, agent, at, dur, parent=b"", model="", fail=False, io=None):
        sid = self._id()
        attrs = [
            kv("tracely.observation.type", otype),
            kv("tracely.agent.id", agent),
            kv("session.id", self.thread),
        ]
        if model:
            attrs += [kv("gen_ai.request.model", model),
                      kv("gen_ai.usage.input_tokens", random.randrange(120, 700)),
                      kv("gen_ai.usage.output_tokens", random.randrange(30, 220))]
        if io:
            attrs += [kv("input.value", json.dumps(io[0])), kv("output.value", json.dumps(io[1]))]
        s = Span(
            trace_id=self.trace_id, span_id=sid, parent_span_id=parent, name=name,
            kind=Span.SPAN_KIND_INTERNAL,
            start_time_unix_nano=self.t0 + at * MS,
            end_time_unix_nano=self.t0 + (at + dur) * MS,
            attributes=attrs,
        )
        if fail:
            s.status.code = 2
            s.status.message = "upstream 503 — retry budget exhausted"
        self.spans.append(s)
        return sid

    def send(self, trace_id: bytes) -> None:
        req = ExportTraceServiceRequest(resource_spans=[ResourceSpans(
            resource=Resource(attributes=[kv("service.name", "demo-conversation")]),
            scope_spans=[ScopeSpans(scope=InstrumentationScope(name="demo"), spans=self.spans)],
        )])
        r = urllib.request.Request(
            f"{API}/v1/traces", data=req.SerializeToString(),
            headers={"Content-Type": "application/x-protobuf", "Authorization": f"Bearer {KEY}"},
        )
        urllib.request.urlopen(r, timeout=15).read()


def turn1(thread: str, t0: int) -> None:
    """Support agent triages, calls a tool, then pulls in a research SUB-agent."""
    t = Turn(thread, t0)
    t.trace_id = random.randbytes(16)
    root = t.span(name="support-agent.run", otype="AGENT", agent="support-agent", at=0, dur=4200,
                  io=({"user": "My order #4471 arrived broken — what are my options?"},
                      {"answer": "Replacement dispatched, refund also available."}))
    t.span(name="chat gpt-4o", otype="GENERATION", agent="support-agent", at=40, dur=520,
           parent=root, model="gpt-4o")
    t.span(name="lookup_order", otype="TOOL", agent="support-agent", at=600, dur=310, parent=root,
           io=({"order_id": "4471"}, {"status": "delivered", "item": "Aero 14 Air"}))
    # the sub-agent: an AGENT span NESTED under support-agent's span
    sub = t.span(name="research-agent.run", otype="AGENT", agent="research-agent", at=1000,
                 dur=2200, parent=root)
    t.span(name="chat claude-3-5-sonnet", otype="GENERATION", agent="research-agent", at=1040,
           dur=610, parent=sub, model="claude-3-5-sonnet")
    t.span(name="search_warranty_policy", otype="TOOL", agent="research-agent", at=1700, dur=540,
           parent=sub, io=({"sku": "aero-14-air"}, {"warranty_months": 24}))
    t.span(name="check_stock", otype="TOOL", agent="research-agent", at=2300, dur=430, parent=sub,
           fail=True)
    t.span(name="chat claude-3-5-sonnet", otype="GENERATION", agent="research-agent", at=2780,
           dur=390, parent=sub, model="claude-3-5-sonnet")
    t.span(name="create_replacement_order", otype="TOOL", agent="support-agent", at=3300, dur=480,
           parent=root, io=({"order_id": "4471"}, {"replacement_id": "4471-R"}))
    t.span(name="chat gpt-4o", otype="GENERATION", agent="support-agent", at=3850, dur=330,
           parent=root, model="gpt-4o")
    t.send(t.trace_id)


def turn2(thread: str, t0: int) -> None:
    """Second turn: hands off to billing, which spawns its own helper."""
    t = Turn(thread, t0)
    t.trace_id = random.randbytes(16)
    root = t.span(name="billing-agent.run", otype="AGENT", agent="billing-agent", at=0, dur=2600,
                  io=({"user": "Actually just refund me instead."},
                      {"answer": "Refund of $1,299 issued to the original card."}))
    t.span(name="chat gpt-5.4-mini", otype="GENERATION", agent="billing-agent", at=30, dur=380,
           parent=root, model="gpt-5.4-mini")
    t.span(name="fetch_invoice", otype="TOOL", agent="billing-agent", at=450, dur=260, parent=root)
    audit = t.span(name="audit-agent.run", otype="AGENT", agent="audit-agent", at=800, dur=900,
                   parent=root)
    t.span(name="verify_refund_policy", otype="TOOL", agent="audit-agent", at=850, dur=420,
           parent=audit)
    t.span(name="chat gpt-4o", otype="GENERATION", agent="audit-agent", at=1300, dur=340,
           parent=audit, model="gpt-4o")
    t.span(name="issue_refund", otype="TOOL", agent="billing-agent", at=1800, dur=520, parent=root,
           io=({"amount": 1299}, {"refund_id": "rf_88213"}))
    t.span(name="chat gpt-5.4-mini", otype="GENERATION", agent="billing-agent", at=2350, dur=210,
           parent=root, model="gpt-5.4-mini")
    t.send(t.trace_id)


def main() -> None:
    thread = f"conv-{random.randrange(10**6):06d}"
    now = time.time_ns()
    turn1(thread, now - 60_000 * MS)
    turn2(thread, now - 20_000 * MS)
    print(thread)


if __name__ == "__main__":
    main()
