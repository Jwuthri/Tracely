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


def first_io(spans: list[dict], key: str) -> str:
    """Find the latest span with a non-empty `key` (input/output) and return its readable text."""
    for s in reversed(spans):
        if s.get(key):
            return content_text(s[key])
    return ""


_USER_ROLES = {"user", "human"}


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
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [m for m in value if isinstance(m, dict) and (m.get("role") or m.get("type"))]


def _last_user_text(value: Any) -> str:
    for m in reversed(_chat_messages(value)):
        if str(m.get("role") or m.get("type") or "").lower() in _USER_ROLES:
            text = content_text(m.get("content"))
            if text:
                return text
    return ""


def request_for(root: dict, spans: list[dict]) -> str:
    """The user's request for THIS message — the LAST user turn in it, not the first.

    A span's stored input is usually the whole message array the model was called with (system +
    every earlier turn + the new one), and `extract_text` returns the FIRST readable text in it —
    the system prompt, or turn 1. So a judge graded turn 6's answer against turn 1's question,
    which is exactly as wrong as it sounds. Symmetric to `answer_for`, which already takes the
    LAST answer; falls back to the old first-text behavior when nothing carries a role.
    """
    for value in (root.get("input"), *(s.get("input") for s in reversed(spans))):
        text = _last_user_text(value)
        if text:
            return text
    return content_text(root.get("input")) or first_io(spans, "input")


def answer_for(root: dict, spans: list[dict], TOOL: str, GENERATION: str, CHAIN: str) -> str:
    """The agent's final answer for judge grading.

    Order of preference: the root span's output → the LAST GENERATION span (skips CHAIN/AGENT
    framework routing signals like LangGraph's `__end__`) → any non-TOOL/non-CHAIN output → the
    fallback `first_io(spans, 'output')`.
    """
    if root.get("output"):
        return content_text(root["output"])
    for s in reversed(spans):
        if s.get("type") == GENERATION and s.get("output"):
            return content_text(s["output"])
    for s in reversed(spans):
        if s.get("output") and s.get("type") not in (TOOL, CHAIN):
            return content_text(s["output"])
    return first_io(spans, "output")
