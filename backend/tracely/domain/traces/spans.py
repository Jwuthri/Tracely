"""Pure helpers on a list of ClickHouse span dicts.

Single canonical home for "what's the root span?" / "what's the input digest?" / "what facts
matter for failure?". Before Phase 2 these lived as `_root` / `_input_digest` in
`tracely.regression` and `_facts` in `tracely.fi` — three modules each re-deriving the same
thing. Importing from here keeps the rules consistent.

Everything in this module operates on the same span dict shape (ClickHouse `events` row
materialized via SELECT — see `infrastructure/clickhouse/events_schema.py:EVENT_COLUMNS`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


def root_span(spans: list[dict]) -> dict:
    """The trace's root: the first span with no parent (or `is_app_root`). Falls back to spans[0]
    so callers never have to None-check on a non-empty list."""
    return next(
        (s for s in spans if s.get("parent_span_id", "") == "" or s.get("is_app_root")),
        spans[0],
    )


def input_digest(spans: list[dict]) -> str:
    """sha256 over (agent_id, name, input) of the root span — the dedup key for regression cases
    and the gate's candidate-trace matcher. JSON-encoded with sort_keys for stable hashing."""
    r = root_span(spans)
    payload = {
        "agent_id": r.get("agent_id", ""),
        "name": r.get("name", ""),
        "input": r.get("input") or "",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def system_prompt(spans: list[dict]) -> str:
    """The system prompt these spans ran under — the first `role == "system"` message in any span's
    `input`. Providers differ wildly in what config they emit, but the system prompt is always in
    the messages, so this recovers it for agents that declared nothing (`otel/messages.py` has
    already normalized `system`/`developer`/`SystemMessage` to `role: "system"` at ingest).

    Returns "" when no span carries one — plenty of traces never send a system message."""
    for s in spans:
        raw = s.get("input")
        if not raw or '"system"' not in str(raw):
            continue  # cheap reject before paying for the JSON parse
        try:
            msgs = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        for m in msgs if isinstance(msgs, list) else []:
            if not isinstance(m, dict) or m.get("role") != "system":
                continue
            text = _content_text(m.get("content"))
            if text:
                return text
    return ""


def _content_text(content: object) -> str:
    """A normalized message body -> plain text. Content is a string or a list of blocks; join the
    text blocks and ignore images/tool parts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b["text"] for b in content
            if isinstance(b, dict) and isinstance(b.get("text"), str)
        ]
        return "\n".join(parts).strip()
    return ""


@dataclass(frozen=True, slots=True)
class FailureFacts:
    """The failure-relevant slice of a trace, extracted once.

    `user_input` / `agent_answer` are pulled from the run's I/O (root preferred, then last
    non-TOOL output). `tools_requested` vs `tools_executed` exposes the silent-failure gap.
    `error_messages` lines are pre-formatted as `"<span_name>: <status_message>"`.
    """

    user_input: str
    agent_answer: str
    tools_requested: list[str]
    tools_executed: list[str]
    error_messages: list[str]
    missing_tools: list[str]


def failure_facts(spans: list[dict]) -> FailureFacts:
    """Compute the FailureFacts for a trace. Pure: no I/O, no settings."""
    root = root_span(spans)
    inp = next((s.get("input") for s in spans if s.get("input")), "") or ""
    # the agent's answer: prefer the root/non-tool output; a tool's raw payload is not the answer
    out = (
        root.get("output")
        or next(
            (s.get("output") for s in reversed(spans) if s.get("output") and s.get("type") != "TOOL"),
            "",
        )
        or next((s.get("output") for s in reversed(spans) if s.get("output")), "")
        or ""
    )
    requested: set[str] = set()
    executed: set[str] = set()
    errors: list[str] = []
    for s in spans:
        for t in s.get("tool_call_names") or []:
            if t:
                requested.add(t)
        if s.get("type") == "TOOL" and s.get("name"):
            executed.add(s.get("name"))
        if s.get("level") == "ERROR":
            msg = (s.get("status_message") or "").strip()
            errors.append(f"{s.get('name')}: {msg}" if msg else str(s.get("name")))
    missing = sorted(requested - executed)
    return FailureFacts(
        user_input=inp,
        agent_answer=out,
        tools_requested=sorted(requested),
        tools_executed=sorted(executed),
        error_messages=errors,
        missing_tools=missing,
    )
