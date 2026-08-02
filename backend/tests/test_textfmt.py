"""message_text — readable text from structured message I/O (used by search + cluster members)."""

from __future__ import annotations

import json

from tracely.domain.evaluation.text import readable_io, request_for
from tracely.infrastructure.text import extract_text, message_text


def test_chat_message_object():
    assert message_text('{"role": "user", "content": [{"type": "text", "text": "hello there"}]}') == "hello there"


def test_content_block_array():
    raw = '[{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": "x"}}]'
    assert message_text(raw) == "hi"


def test_assistant_object_with_string_content():
    assert message_text('{"role": "assistant", "content": "the answer"}') == "the answer"


def test_plain_string_passes_through():
    assert message_text("just a plain user message") == "just a plain user message"


def test_empty_and_none():
    assert message_text("") == ""
    assert message_text(None) == ""


def test_attachment_only_falls_back_to_raw():
    # no text block to extract -> keep the raw value rather than blanking the label
    raw = '[{"type": "image_url", "image_url": {"url": "http://x/y.png"}}]'
    assert message_text(raw) == raw


def test_invalid_json_passes_through():
    assert message_text("{not valid json") == "{not valid json"


def test_extract_text_walks_nested_content():
    assert extract_text({"content": [{"type": "text", "text": "deep"}]}) == "deep"


# ── which message is THE request (domain/evaluation/text.request_for) ──────────
# The judge grades a message against the user's request. A span's input is usually the whole
# history the model was called with, so "first readable text in it" put turn 1's greeting on every
# turn — of the prompt AND of the conversation transcript.


def _hist(*msgs, key="role"):
    return json.dumps([{key: r, "content": c} for r, c in msgs])


def test_request_is_the_last_user_message_not_the_first():
    root = {"input": _hist(
        ("system", "You are Realize."),
        ("user", "hellohello"),
        ("assistant", "Please provide your CPF."),
        ("user", "02/08/2026"),
    )}
    assert request_for(root, [root]) == "02/08/2026"


def test_the_history_can_hide_under_a_messages_key():
    """LangChain/LangGraph state hands the history over as `{"messages": [...]}`; unwrapped, the
    whole JSON blob was rendered as the user's request."""
    root = {"input": json.dumps({"messages": [
        {"role": "user", "content": "hellohello"},
        {"role": "assistant", "content": "CPF?"},
        {"role": "user", "content": "12345678900"},
    ]})}
    assert request_for(root, [root]) == "12345678900"


def test_an_unknown_role_name_still_resolves():
    """The roles in the wild are not always `user` — a collections bot calls them `customer`.
    Anything that isn't the agent's own side counts, else we fell back to the first text."""
    root = {"input": _hist(
        ("customer", "hellohello"),
        ("bot", "Please provide your CPF."),
        ("customer", "12345678900"),
    )}
    assert request_for(root, [root]) == "12345678900"


def test_the_request_falls_back_to_the_spans_when_the_root_has_none():
    """Framework roots (AGENT/CHAIN) often carry no input of their own; the history is on the
    generation underneath."""
    root = {"input": None}
    spans = [root, {"input": _hist(("user", "first"), ("assistant", "a"), ("user", "latest"))}]
    assert request_for(root, spans) == "latest"


def test_a_single_user_message_is_unchanged():
    root = {"input": '{"role": "user", "content": [{"type": "text", "text": "where is my order?"}]}'}
    assert request_for(root, [root]) == "where is my order?"
    assert request_for({"input": "plain string"}, []) == "plain string"


def test_a_step_input_renders_the_whole_exchange_not_just_the_system_prompt():
    """A generation's input is the message array it was called with. Rendered as "first readable
    text" the step judge saw the agent's rubric under Step input and never the request."""
    body = readable_io(_hist(
        ("system", "You are Realize."),
        ("user", "hellohello"),
        ("assistant", "CPF?"),
        ("user", "12345678900"),
    ))
    assert body.splitlines() == [
        "system: You are Realize.",
        "user: hellohello",
        "assistant: CPF?",
        "user: 12345678900",
    ]


def test_readable_io_leaves_tool_json_and_single_messages_alone():
    assert readable_io('{"open_count": 1}') == '{"open_count": 1}'
    assert readable_io('{"role": "assistant", "content": "done"}') == "done"
