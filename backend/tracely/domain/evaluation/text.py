"""Text extraction used by evaluators (LLM-judge in particular) — pulls the readable answer
out of a span's structured I/O so the judge grades the actual reply, not its JSON wrapper.

Reuses `tracely.infrastructure.text.extract_text` (the text walker that powers
`message_text` for the routers / UI) so there's exactly one definition of "what's the human
text inside this value?" in the codebase.
"""

from __future__ import annotations

import json
from typing import Any

from tracely.infrastructure.text import extract_text


def content_text(value: Any) -> str:
    """Handles plain strings AND structured content (JSON content-block arrays / chat messages)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        return extract_text(value)
    s = value.strip()
    if s[:1] in ("[", "{"):
        try:
            return extract_text(json.loads(s)) or value
        except (ValueError, TypeError):
            return value
    return value


def last_io(spans: list[dict], key: str) -> str:
    """The LATEST span with a non-empty `key` (input/output), as readable text.

    Named for what it does. It was `first_io`, which read as "the first input in the trace" — the
    opposite of the body — and that mismatch is how it ended up standing in for the user's request.
    It is a last-resort fallback only; `request_for` / `answer_for` are the real accessors.
    """
    for s in reversed(spans):
        if s.get(key):
            return content_text(s[key])
    return ""


_USER_ROLES = {"user", "human"}
# Everything that is plainly NOT the person talking to the agent. The second pass uses this, so a
# framework that calls the human `customer` or `contact` still resolves — the rule that survives an
# unknown vocabulary is "the last message that isn't the agent's", not a list of user synonyms.
_NON_USER_ROLES = {"assistant", "ai", "system", "tool", "function", "developer", "model"}


def _chat_messages(value: Any) -> list[dict]:
    """`value` as a list of chat messages, or [] when it isn't one."""
    if isinstance(value, str):
        s = value.strip()
        if s[:1] not in ("[", "{"):
            return []
        try:
            value = json.loads(s)
        except (ValueError, TypeError):
            return []
    # `{"messages": [...]}` — how LangChain/LangGraph state and several SDKs hand over a history.
    if isinstance(value, dict) and isinstance(value.get("messages"), list):
        value = value["messages"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [m for m in value if isinstance(m, dict) and (m.get("role") or m.get("type"))]


def _last_user_text(value: Any) -> str:
    """The last thing the human said in this message list.

    Two passes: first a role we know, then anything that isn't the agent's own side. The roles in
    the wild are not always `user` (`customer`, `contact`, a framework prefix…), and falling
    through to "first readable text" is what put turn 1's greeting on every turn of a transcript.
    """
    msgs = _chat_messages(value)
    for known_only in (True, False):
        for m in reversed(msgs):
            role = str(m.get("role") or m.get("type") or "").lower()
            if (role in _USER_ROLES) if known_only else (role not in _NON_USER_ROLES):
                text = content_text(m.get("content", m))
                if text:
                    return text
    return ""


def readable_io(value: Any, per_message: int = 400) -> str:
    """A span's I/O rendered for a judge to read.

    A generation's input is the message array it was called with, and `content_text` returns only
    the FIRST text in it — the system prompt. So a step-level judge was shown the agent's rubric
    under "Step input" and never the request it answered. A real array renders as `role: text`
    lines; anything else (a tool's JSON, a plain string, one message) is unchanged.
    """
    msgs = _chat_messages(value)
    if len(msgs) <= 1:
        return content_text(value)
    lines = []
    for m in msgs:
        role = str(m.get("role") or m.get("type") or "?").lower()
        text = content_text(m.get("content", m))
        if text:
            lines.append(f"{role}: {text[:per_message]}")
    return "\n".join(lines) or content_text(value)


def request_for(root: dict, spans: list[dict]) -> str:
    """The user's request for THIS message — the LAST thing the human said, not the first.

    Read from the FULLEST record of the conversation anywhere in the trace, which is the whole
    point. Two traps, and taking the first source that answered fell into both:

    - `extract_text` returns the first readable text in a message array — the system prompt, or
      turn 1. So a judge graded turn 6's answer against turn 1's question.
    - the root often carries a single message (the session's opening line, stamped on every turn
      by the instrumentation) while the real history sits on the generation underneath. Stopping
      at the root meant every turn of a 6-turn conversation read as "heyy".

    So: score every candidate by how much conversation it holds, take the richest, and read its
    last user turn. Ties go to the earlier candidate, which is the root — the entry point beats a
    sub-agent's derived prompt. Symmetric to `answer_for`, which already takes the LAST answer.
    """
    best: list[dict] = []
    for value in (root.get("input"), *(s.get("input") for s in spans)):
        msgs = _chat_messages(value)
        if len(msgs) > len(best):
            best = msgs
    text = _last_user_text(best)
    if text:
        return text
    return content_text(root.get("input")) or last_io(spans, "input")


def _text_only(value: Any) -> str:
    """Readable text WITHOUT `content_text`'s raw-JSON fallback — for deciding whether a candidate
    actually said something. An assistant message that is only a tool call
    (`{"role":"assistant","content":"","tool_calls":[…]}`) extracts to "", so the caller can fall
    through to the action itself instead of grading the JSON wrapper as "the answer"."""
    if value is None:
        return ""
    if isinstance(value, str):
        s = value.strip()
        if s[:1] not in ("[", "{"):
            return value
        try:
            return extract_text(json.loads(s))
        except (ValueError, TypeError):
            return value  # unparseable → it's prose
    return extract_text(value)


def answer_for(root: dict, spans: list[dict], TOOL: str, GENERATION: str, CHAIN: str) -> str:
    """The agent's final answer for judge grading.

    Order of preference: the LAST GENERATION span → the root span's output → any non-TOOL/non-CHAIN
    output — the first one with READABLE TEXT wins; an empty or tool-call-only candidate falls
    through instead of ending the search.

    The root used to come first, which put this out of step with the SQL the whole UI reads through
    (`sessions_overview` / `session_turns` both take the latest GENERATION first). Two consequences,
    both real: a trace could DISPLAY one answer and be GRADED on another, and a framework root whose
    output is a routing signal — LangGraph's `__end__` — was graded as the agent's reply. Same order
    in both places now, so what you read in the table is what the judge read.

    **Not every answer is text.** Some agents end a turn by ACTING — rendering a rich card (a tool
    that displays content), or handing the conversation to a human. Their final generation is a
    bare tool call, which used to be graded as the raw `tool_calls` JSON — and judges read that as
    "the agent never answered the customer" and failed turns that were answered fine. When no
    candidate has readable text, the LAST tool span's output IS the answer, labeled so the judge
    grades whether the action addressed the user rather than punishing the missing prose.
    """
    candidates = [
        next((s["output"] for s in reversed(spans)
              if s.get("type") == GENERATION and s.get("output")), None),
        root.get("output"),
        next((s["output"] for s in reversed(spans)
              if s.get("output") and s.get("type") not in (TOOL, CHAIN)), None),
    ]
    for value in candidates:
        text = _text_only(value)
        if text:
            return text
    for s in reversed(spans):
        if s.get("type") == TOOL and s.get("output"):
            name = s.get("name") or "tool"
            return (
                f"[no text reply — the agent answered with the `{name}` action; "
                f"its output below is what the user received]\n{content_text(s['output'])}"
            )
    return last_io(spans, "output")
