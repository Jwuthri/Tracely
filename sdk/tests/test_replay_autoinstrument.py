"""Hermetic replay for the auto-instrument / drop-in path.

Code that uses the auto-instrumentors (`instrument="auto"`) or the drop-in client wrappers calls the
provider SDK directly — no Tracely seam. So `fixtures()` class-patches the provider's create-method:
inside the block it serves the recorded completion (reconstructed into a provider-shaped object) and
never hits the network; outside replay it calls straight through (inert).

These tests drive the generic machinery against a stand-in client class, so no real provider SDK is
needed. The openai wiring (`_patch_openai_replay`) is a thin table entry over the same `_patch_class_method`.
"""

from __future__ import annotations

import pytest

import tracely_sdk as tracely
from tracely_sdk import (
    _normalize_bundle,
    _patch_class_method,
    _reconstruct_anthropic,
    _reconstruct_openai_chat,
)


@pytest.fixture(scope="module", autouse=True)
def _init() -> None:
    tracely.init(env="prod", instrument=False)


class _Completions:
    """Stand-in for openai's `Completions` — keyword-only model/messages, returns a live sentinel."""

    def create(self, *, model: str, messages: list) -> dict:
        return {"live": True, "model": model}


def _patch() -> None:
    _patch_class_method(
        _Completions,
        "create",
        model_key="model",
        input_extractor=lambda kw: kw.get("messages"),
        reconstruct=_reconstruct_openai_chat,
    )


def test_calls_through_when_not_replaying() -> None:
    _patch()
    out = _Completions().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert out == {"live": True, "model": "gpt-4o"}  # inert outside fixtures()


def test_serves_recorded_completion_without_network() -> None:
    _patch()
    bundle = {
        "version": 2,
        "llm": [
            {
                "model": "gpt-4o",
                "input": [{"role": "user", "content": "hi"}],
                "output": {"role": "assistant", "content": "recorded answer"},
                "error": None,
            }
        ],
    }
    with tracely.fixtures(bundle):
        resp = _Completions().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "recorded answer"  # reconstructed, no live call


def test_recorded_error_raises_toolerror() -> None:
    _patch()
    bundle = {"version": 2, "llm": [{"model": "gpt-4o", "input": None, "output": None, "error": "rate limited"}]}
    with tracely.fixtures(bundle), pytest.raises(tracely.ToolError, match="rate limited"):
        _Completions().create(model="gpt-4o", messages=[])


def test_order_fallback_when_recorded_model_name_differs() -> None:
    # An auto-instrumentor span name may not equal the model id → fall back to the next recorded call.
    _patch()
    bundle = {"version": 2, "llm": [{"model": "ChatCompletion", "input": None, "output": {"content": "x"}, "error": None}]}
    with tracely.fixtures(bundle):
        resp = _Completions().create(model="gpt-4o", messages=[])
    assert resp.choices[0].message.content == "x"


def test_reconstructs_tool_calls() -> None:
    out = _reconstruct_openai_chat(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
        }
    )
    tc = out.choices[0].message.tool_calls[0]
    assert tc.id == "c1" and tc.function.name == "get_weather" and tc.function.arguments == "{}"


def test_reconstructs_from_plain_string_and_message_list() -> None:
    assert _reconstruct_openai_chat("just text").choices[0].message.content == "just text"
    nested = _reconstruct_openai_chat([{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}])
    assert nested.choices[0].message.content == "a"  # last dict wins


def test_llm_input_key_normalized_to_args() -> None:
    # The backend persists the LLM call input under "input"; _pop_fixture arg-matching reads "args".
    store = _normalize_bundle({"llm": [{"model": "m", "input": {"q": 1}, "output": "x"}]})
    assert store["llm"]["m"][0]["args"] == {"q": 1}


class _AsyncCompletions:
    """Stand-in for openai's AsyncCompletions — the async create branch of the patch."""

    async def create(self, *, model: str, messages: list) -> dict:
        return {"live": True, "model": model}


class _Messages:
    """Stand-in for anthropic's `Messages.create` (model/messages/system kwargs)."""

    def create(self, *, model: str, messages: list, system: str | None = None) -> dict:
        return {"live": True, "model": model}


def test_anthropic_reconstructs_native_content_blocks() -> None:
    # the drop-in records Anthropic's native blocks: a list of {type,text}/{type,tool_use}
    out = _reconstruct_anthropic(
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "let me check"},
                {"type": "tool_use", "id": "tu1", "name": "get_weather", "input": {"city": "SF"}},
            ],
        }
    )
    assert out.content[0].type == "text" and out.content[0].text == "let me check"
    assert out.content[1].type == "tool_use" and out.content[1].name == "get_weather"
    assert out.content[1].id == "tu1" and out.content[1].input == {"city": "SF"}


def test_anthropic_reconstructs_canonical_shape() -> None:
    # the auto-instrument path is backend-normalized to content-string + OpenAI-style tool_calls;
    # reconstruction maps it back to Anthropic content blocks (arguments string → input dict)
    out = _reconstruct_anthropic(
        {
            "content": "on it",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": '{"q": "x"}'}}],
        }
    )
    assert out.content[0].type == "text" and out.content[0].text == "on it"
    assert out.content[1].type == "tool_use" and out.content[1].name == "search"
    assert out.content[1].input == {"q": "x"}  # parsed from the JSON-string arguments


def test_anthropic_create_serves_fixture() -> None:
    _patch_class_method(
        _Messages, "create", model_key="model",
        input_extractor=lambda kw: kw.get("messages"), reconstruct=_reconstruct_anthropic,
    )
    bundle = {
        "version": 2,
        "llm": [{"model": "claude-3-5-sonnet", "input": None,
                 "output": {"content": [{"type": "text", "text": "recorded claude"}]}, "error": None}],
    }
    with tracely.fixtures(bundle):
        resp = _Messages().create(model="claude-3-5-sonnet", messages=[], system="be brief")
    assert resp.content[0].text == "recorded claude"


async def test_async_create_serves_fixture_and_falls_through() -> None:
    _patch_class_method(
        _AsyncCompletions,
        "create",
        model_key="model",
        input_extractor=lambda kw: kw.get("messages"),
        reconstruct=_reconstruct_openai_chat,
    )
    # falls through to the real coroutine when not replaying
    assert await _AsyncCompletions().create(model="gpt-4o", messages=[]) == {"live": True, "model": "gpt-4o"}
    bundle = {"version": 2, "llm": [{"model": "gpt-4o", "input": None, "output": {"content": "async ok"}, "error": None}]}
    with tracely.fixtures(bundle):
        resp = await _AsyncCompletions().create(model="gpt-4o", messages=[])
    assert resp.choices[0].message.content == "async ok"
