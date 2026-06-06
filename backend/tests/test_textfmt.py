"""message_text — readable text from structured message I/O (used by search + cluster members)."""

from __future__ import annotations

from tracely.textfmt import extract_text, message_text


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
