"""Rolling-summary data model + pure helpers.

A rolling summary is an ACCUMULATING, compressed record of a conversation up to a given step. It
is always stored at the STEP (span) level — one row per span — each holding the full summary of
every step from the start of the thread up to it (see the `rolling_summaries` table). This module
owns:

- the item schema (`ConversationSummaryItem` / `ConversationSummary`) the summarizer LLM emits,
- `step_components` — decomposing one span into its typed pieces (thinking / tool_call /
  tool_result / output_structured / output_content),
- `format_summary_as_history` — rendering accumulated items back into the `@HISTORY` string.

Pure: no I/O, no LLM. The service drives the accumulate loop; the agent does the summarizing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from tracely.domain.evaluation.text import content_text

# Local type constants (mirror otel vocabulary; avoid importing the evaluators package).
THINKING = "THINKING"
TOOL = "TOOL"

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"
ROLE_SYSTEM = "system"
ROLE_PREV_SUMMARY = "prev_summary"  # the compacted older-history item's role

# component / item types
T_THINKING = "thinking"
T_TOOL_CALL = "tool_call"
T_TOOL_RESULT = "tool_result"
T_OUTPUT_STRUCTURED = "output_structured"
T_OUTPUT_CONTENT = "output_content"
T_SUMMARY = "summary"  # a compacted block of older items (budget compaction)

_HISTORY_CLIP = 8000
_ITEM_CLIP = 2000


class ConversationSummaryItem(BaseModel):
    """One element of the accumulated summary. `content` is a ~10-20 word summary (or verbatim when
    the source was already short). Tool fields link a tool_call to its following tool_result and
    allow a cache-friendly LangChain message conversion."""

    role: str = Field(description="user | assistant | tool")
    type: str = Field(description="thinking | tool_call | tool_result | output_structured | output_content")
    content: str = ""
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str | None = None


class ConversationSummary(BaseModel):
    items: list[ConversationSummaryItem] = Field(default_factory=list)


@dataclass
class Component:
    """A typed piece of a step, pre-summary. The summarizer turns each into a summary item."""

    role: str
    type: str
    content: str
    tool_name: str | None = None
    tool_arguments: str | None = None
    meta: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token). Good enough for budget decisions — we never bill on it."""
    return max(1, len(text or "") // 4)


def components_token_total(components: list[Component]) -> int:
    return sum(estimate_tokens(c.content) for c in components)


def compacted_item(content: str) -> dict:
    """The compacted older-history block — one item with the `prev_summary` role (not a wrapper
    key). Sits at the front of the list ahead of the verbatim recent items."""
    return {"role": ROLE_PREV_SUMMARY, "type": T_SUMMARY, "content": content}


def as_summary_items(stored: object) -> list[dict]:
    """Normalize a stored summary to the canonical FLAT list of items. Accepts the list, a legacy
    `{prev_summary, items}` object (the compacted string becomes a leading prev_summary item), or
    None — so reads never break across shape changes."""
    if isinstance(stored, list):
        return list(stored)
    if isinstance(stored, dict):
        items = list(stored.get("items") or [])
        prev = stored.get("prev_summary")
        return ([compacted_item(prev)] + items) if prev else items
    return []


def summary_token_total(items: object) -> int:
    """Total estimated tokens across the summary's items — drives the 20k budget compaction."""
    return sum(estimate_tokens(it.get("content") or "") for it in as_summary_items(items))


def _clip(s: str, n: int = _ITEM_CLIP) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _as_structured(out: object) -> str | None:
    """The output rendered as pretty JSON when it's structured; None otherwise."""
    if isinstance(out, (dict, list)):
        return _clip(json.dumps(out, ensure_ascii=False), _ITEM_CLIP)
    if isinstance(out, str):
        t = out.strip()
        if t[:1] in ("[", "{"):
            try:
                return _clip(json.dumps(json.loads(t), ensure_ascii=False), _ITEM_CLIP)
            except ValueError:
                return None
    return None


def _tool_args(span: dict) -> str | None:
    tcs = span.get("tool_calls")
    if tcs:
        try:
            return _clip(json.dumps(tcs, ensure_ascii=False), 600)
        except (TypeError, ValueError):
            return None
    inp = content_text(span.get("input"))
    return _clip(inp, 600) or None


def user_input_component(span: dict) -> Component | None:
    """The user request carried on a turn's root span input, if any."""
    text = content_text(span.get("input"))
    return Component(ROLE_USER, T_OUTPUT_CONTENT, _clip(text)) if text else None


def step_components(span: dict) -> list[Component]:
    """Decompose one span (step) into its typed components. Empty components are dropped."""
    stype = (span.get("type") or "").upper()
    comps: list[Component] = []

    if stype == THINKING:
        txt = content_text(span.get("output")) or content_text(span.get("input"))
        if txt:
            comps.append(Component(ROLE_ASSISTANT, T_THINKING, _clip(txt)))
        return comps

    if stype == TOOL:
        name = str(span.get("name") or "tool")
        args = _tool_args(span)
        call_text = f"{name}({args})" if args else name
        comps.append(
            Component(ROLE_ASSISTANT, T_TOOL_CALL, call_text, tool_name=name, tool_arguments=args)
        )
        result = content_text(span.get("output"))
        if result:
            comps.append(Component(ROLE_TOOL, T_TOOL_RESULT, _clip(result), tool_name=name))
        return comps

    # generation / chain / agent / other: any requested tools, then the textual/structured output
    for t in span.get("tool_call_names") or []:
        if t:
            comps.append(Component(ROLE_ASSISTANT, T_TOOL_CALL, str(t), tool_name=str(t)))
    structured = _as_structured(span.get("output"))
    if structured:
        comps.append(Component(ROLE_ASSISTANT, T_OUTPUT_STRUCTURED, structured))
    else:
        txt = content_text(span.get("output"))
        if txt:
            comps.append(Component(ROLE_ASSISTANT, T_OUTPUT_CONTENT, _clip(txt)))
    return comps


def items_from_components(
    components: list[Component], summaries: list[str] | None = None
) -> list[ConversationSummaryItem]:
    """Build summary items from components. `summaries` (one per component, same order) replaces the
    content when the step was LLM-summarized; `None` keeps each component verbatim. Tool calls get a
    step-local id and the following tool_result inherits it (so a LangChain conversion can pair
    them). Pure + deterministic — ids are positional, not random."""
    items: list[ConversationSummaryItem] = []
    last_call_id: str | None = None
    for i, c in enumerate(components):
        content = c.content
        if summaries is not None and i < len(summaries) and summaries[i]:
            content = summaries[i]
        item = ConversationSummaryItem(
            role=c.role,
            type=c.type,
            content=_clip(content, _ITEM_CLIP),
            tool_name=c.tool_name,
            tool_arguments=c.tool_arguments,
        )
        if c.type == T_TOOL_CALL:
            last_call_id = f"call_{i}"
            item.tool_call_id = last_call_id
        elif c.type == T_TOOL_RESULT and last_call_id:
            item.tool_call_id = last_call_id
        items.append(item)
    return items


def _line(item: dict) -> str:
    role = item.get("role") or ROLE_ASSISTANT
    itype = item.get("type") or T_OUTPUT_CONTENT
    content = item.get("content") or ""
    if itype == T_SUMMARY:
        return f"[earlier conversation, summarized]\n{content}"
    if itype == T_OUTPUT_CONTENT and role in (ROLE_USER, ROLE_ASSISTANT):
        return f"[{role}]: {content}"
    return f"[{role}:{itype}] {content}"


def format_summary_as_history(items: object, max_chars: int = 0) -> str:
    """Render the summary's items into the `@HISTORY` string: a leading prev_summary block (if any)
    then [role]/[role:type] lines for the verbatim items. `max_chars > 0` clips; `<= 0` returns the
    full text (the 20k compaction already bounds size). Tolerates the legacy object shape."""
    lines = [_line(it) for it in as_summary_items(items) if (it.get("content") or "").strip()]
    text = "\n".join(lines)
    return _clip(text, max_chars) if max_chars and max_chars > 0 else text
