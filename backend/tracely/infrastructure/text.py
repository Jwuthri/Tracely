"""Readable text from stored message I/O.

Span input/output is structured JSON — a chat message ({role, content}), a content-block array
([{type:'text',text}, {type:'image_url'}…]), or a list of messages. When we need a plain-text
label/snippet (search results, cluster members) rather than the rich renderer, pull the first
human-readable text out instead of showing the raw `{"role":...,"content":[...]}` blob.
"""

from __future__ import annotations

import json
from typing import Any


def extract_text(v: Any) -> str:
    """First human-readable text inside a (possibly nested) message value."""
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        for item in v:
            t = extract_text(item)
            if t:
                return t
        return ""
    if isinstance(v, dict):
        if isinstance(v.get("text"), str):
            return v["text"]
        if isinstance(v.get("content"), str):
            return v["content"]
        if v.get("content") is not None:
            return extract_text(v["content"])
    return ""


def message_text(s: str | None) -> str:
    """A plain-text label/snippet from a stored input/output string. Parses structured JSON and
    returns its text; passes plain strings through; returns "" for empty."""
    if not s:
        return ""
    t = s.strip()
    if not (t.startswith("{") or t.startswith("[")):
        return s
    try:
        return extract_text(json.loads(t)) or s
    except (ValueError, TypeError):
        return s
