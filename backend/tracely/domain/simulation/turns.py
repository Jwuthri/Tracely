"""A scenario's turns, and the optional expectations attached to each.

A turn is a user message plus — optionally — what the agent is supposed to do with it:

    {"message": "where is my refund?", "expect": "offers a refund", "tools": ["issue_refund"]}

Both expectation fields are optional and empty by default. With neither, the turn is graded only
by the project's own evaluators, exactly as production traffic is; that floor is what keeps the
feature usable on day one instead of a form nobody fills in. Filling them in buys precision a
generic judge cannot have — a refund conversation sails past "was this helpful?" while never
issuing the refund, which is the class of bug the gate exists to catch.

`normalize_turns` accepts the plain-string shape too, so scenarios authored before expectations
existed keep working with no data migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Turn:
    message: str
    expect: str = ""
    tools: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_expectations(self) -> bool:
        return bool(self.expect or self.tools)


def normalize_turns(raw: Any) -> list[Turn]:
    """`["hi"]` or `[{"message": "hi", "expect": …, "tools": [...]}]` → `[Turn]`.

    Tolerant on purpose: this parses user-authored JSON off a JSON column, so a malformed entry
    is skipped rather than raising and taking a whole gate run down with it.
    """
    if not isinstance(raw, list):
        return []
    turns: list[Turn] = []
    for item in raw:
        if isinstance(item, str):
            if item.strip():
                turns.append(Turn(message=item.strip()))
            continue
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        tools = item.get("tools")
        turns.append(
            Turn(
                message=message,
                expect=str(item.get("expect") or "").strip(),
                tools=tuple(str(t).strip() for t in tools if str(t).strip())
                if isinstance(tools, list)
                else (),
            )
        )
    return turns


def serialize_turns(turns: list[Turn]) -> list[dict]:
    """Turns back to the JSON-column shape. Always the dict form — one stored shape going
    forward, with `normalize_turns` handling the legacy strings on read."""
    return [{"message": t.message, "expect": t.expect, "tools": list(t.tools)} for t in turns]
