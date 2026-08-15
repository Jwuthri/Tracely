"""Conversation replay: turn a thread's spans into a time-ordered SCRIPT the UI can act out.

Pure — no I/O. The caller supplies the spans (`async_reader.thread_spans_full`) and a
`agent_id -> display name` map; this module derives WHO acted, WHEN, and UNDER WHOM.

The nesting is the point: a span's actor is the nearest AGENT/SUBAGENT ancestor, so an
`llm`/`tool` event is attributed to the agent that actually ran it, and an agent span nested
under another agent is a SUB-agent (rendered as a helper pulled in for one job, not staff).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# observation type -> replay event kind. Anything else rides as "step".
_KIND = {
    "AGENT": "turn",
    "SUBAGENT": "spawn",
    "GENERATION": "llm",
    "EMBEDDING": "llm",
    "TOOL": "tool",
    "RETRIEVER": "tool",
    "GUARDRAIL": "guard",
}
_ACTOR_TYPES = {"AGENT", "SUBAGENT"}


def _ms(a: datetime | None, b: datetime | None) -> int:
    """Milliseconds from `a` to `b`, clamped at 0 (clock skew across services is real)."""
    if a is None or b is None:
        return 0
    return max(0, int((b - a).total_seconds() * 1000))


def _preview(value: Any, limit: int = 120) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = " ".join(text.split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def build_replay(spans: list[dict], names: dict[str, str] | None = None) -> dict:
    """`{duration_ms, actors[], events[]}` — the conversation as a playable script.

    `actors` are ordered by first appearance (stable seating). Each carries `parent` (the actor
    that spawned it, empty for top-level) and `depth`. `events` are ordered by start time with
    `t_ms` relative to the conversation's first span, so the UI plays one clock.
    """
    names = names or {}
    rows = [s for s in spans if s.get("start_time")]
    if not rows:
        return {"duration_ms": 0, "actors": [], "events": []}
    rows.sort(key=lambda s: (s["start_time"], s.get("span_id") or ""))
    t0 = rows[0]["start_time"]

    # Span ids are unique per TRACE, not per thread — a conversation's turns routinely reuse
    # them (any SDK numbering spans from 1 does). Keying by span_id alone made turn 2's parents
    # resolve against turn 1's spans, which silently merged two agents into one.
    def ref(span: dict, sid: Any) -> tuple[str, str]:
        return (str(span.get("trace_id") or ""), str(sid or ""))

    by_id = {ref(s, s.get("span_id")): s for s in rows if s.get("span_id")}

    # ── resolve each span's owning actor by walking up to the nearest AGENT/SUBAGENT ──
    actor_of: dict[str, str] = {}  # span_id -> actor key
    parent_of: dict[str, str] = {}  # actor key -> parent actor key

    def actor_key(span: dict) -> str:
        # agent_id is the stable identity across turns; span_id only when a trace names no agent.
        return str(span.get("agent_id") or "") or f"{span.get('trace_id')}:{span.get('span_id')}"

    for span in rows:
        sid = str(span.get("span_id") or "")
        key_self = ref(span, sid)
        stype = str(span.get("type") or "").upper()
        # nearest ancestor that is itself an actor span
        owner = ""
        cursor = by_id.get(ref(span, span.get("parent_span_id")))
        hops = 0
        while cursor is not None and hops < 64:  # hops: cycle guard on malformed parent chains
            if str(cursor.get("type") or "").upper() in _ACTOR_TYPES:
                owner = actor_key(cursor)
                break
            cursor = by_id.get(ref(cursor, cursor.get("parent_span_id")))
            hops += 1
        if stype in _ACTOR_TYPES:
            key = actor_key(span)
            actor_of[key_self] = key
            # An actor nested under another actor is that actor's sub-agent. First parent wins:
            # a sub-agent reused across turns keeps its original owner.
            if owner and owner != key and key not in parent_of:
                parent_of[key] = owner
        else:
            # A non-actor span with no actor ancestor still names its agent (flat SDK traces).
            actor_of[key_self] = owner or str(span.get("agent_id") or "") or "agent"

    # ── actors, ordered by first appearance ──
    order: list[str] = []
    seen: dict[str, dict] = {}
    for span in rows:
        key = actor_of[ref(span, span.get("span_id"))]
        end = span.get("end_time") or span.get("start_time")
        if key not in seen:
            order.append(key)
            seen[key] = {
                "id": key,
                "name": names.get(key) or key,
                "parent": "",
                "depth": 0,
                "first_ms": _ms(t0, span["start_time"]),
                "last_ms": _ms(t0, end),
                "events": 0,
                "errors": 0,
            }
        seen[key]["last_ms"] = max(seen[key]["last_ms"], _ms(t0, end))

    for key, actor in seen.items():
        parent = parent_of.get(key, "")
        actor["parent"] = parent if parent in seen else ""
        depth, cursor, hops = 0, actor["parent"], 0
        while cursor and hops < 16:
            depth += 1
            cursor = seen.get(cursor, {}).get("parent", "")
            hops += 1
        actor["depth"] = depth
        actor["kind"] = "subagent" if depth else "agent"

    # ── events ──
    events: list[dict] = []
    for span in rows:
        sid = str(span.get("span_id") or "")
        stype = str(span.get("type") or "").upper()
        kind = _KIND.get(stype, "step")
        key = actor_of[ref(span, sid)]
        error = str(span.get("level") or "").upper() == "ERROR"
        seen[key]["events"] += 1
        if error:
            seen[key]["errors"] += 1
        events.append(
            {
                "t_ms": _ms(t0, span["start_time"]),
                "dur_ms": _ms(span["start_time"], span.get("end_time")),
                "actor": key,
                "kind": kind,
                "name": str(span.get("name") or kind),
                "status": "error" if error else "ok",
                "model": str(span.get("model_id") or ""),
                "detail": _preview(span.get("status_message") or span.get("output")),
                "span_id": sid,
                "trace_id": str(span.get("trace_id") or ""),
                "turn_id": str(span.get("turn_id") or ""),
            }
        )

    duration = max((e["t_ms"] + e["dur_ms"]) for e in events) if events else 0
    return {
        "duration_ms": duration,
        "actors": [seen[k] for k in order],
        "events": events,
    }
