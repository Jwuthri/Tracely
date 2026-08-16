"""Hermetic replay beyond OpenAI/Anthropic: Gemini, Mistral, LiteLLM — plus the loud warning
when a replayed run leaves recorded calls unused.

Why this matters: a provider Tracely cannot patch does not fail in CI, it goes to the NETWORK.
The gate then grades a live call while reporting a hermetic replay — a quietly meaningless
verdict. So each provider's entry point is covered, and anything still unpatched is caught by
the unconsumed-fixtures warning.

Mistral and LiteLLM are exercised through stand-ins (the SDKs are optional deps and usually
absent); `google-genai` runs against the real class when installed.
"""

from __future__ import annotations

import logging
import types

import pytest

import tracely_sdk as tracely
from tracely_sdk import (
    _patch_class_method,
    _patch_module_function,
    _reconstruct_google,
    _reconstruct_openai_chat,
    _unconsumed,
)


@pytest.fixture(scope="module", autouse=True)
def _init() -> None:
    tracely.init(env="prod", instrument=False)


def _bundle(model: str, output: object) -> dict:
    return {
        "version": 2,
        "llm": [{"model": model, "input": [{"role": "user", "content": "hi"}], "output": output, "error": None}],
    }


# ── Gemini ────────────────────────────────────────────────────────────────────


def test_google_response_reads_like_the_real_one() -> None:
    """`resp.text`, `resp.function_calls` and walking `candidates[0].content.parts` are the three
    ways agent code reads a GenerateContentResponse — all three must work on the replayed object."""
    resp = _reconstruct_google(
        {
            "role": "assistant",
            "content": "recorded reply",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "lookup", "arguments": '{"q": "x"}'}}
            ],
        }
    )
    assert resp.text == "recorded reply"
    assert resp.function_calls[0].name == "lookup"
    assert resp.function_calls[0].args == {"q": "x"}  # JSON args decoded, as the real SDK gives them
    parts = resp.candidates[0].content.parts
    assert parts[0].text == "recorded reply"
    assert parts[1].function_call.name == "lookup"


def test_real_google_client_is_intercepted() -> None:
    genai = pytest.importorskip("google.genai")
    client = genai.Client(api_key="fake-no-network")  # a live call with this key would fail
    with tracely.fixtures(_bundle("gemini-2.5-flash", {"role": "assistant", "content": "from the fixture"})):
        resp = client.models.generate_content(model="gemini-2.5-flash", contents="hi")
    assert resp.text == "from the fixture"


# ── Mistral (stand-in: mistralai is an optional dep) ──────────────────────────


class _Chat:
    def complete(self, *, model: str, messages: list) -> dict:
        return {"live": True}


def test_mistral_style_client_serves_the_recording() -> None:
    _patch_class_method(
        _Chat, "complete", model_key="model",
        input_extractor=lambda kw: kw.get("messages"), reconstruct=_reconstruct_openai_chat,
    )
    with tracely.fixtures(_bundle("mistral-large", {"role": "assistant", "content": "recorded"})):
        resp = _Chat().complete(model="mistral-large", messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "recorded"
    assert _Chat().complete(model="mistral-large", messages=[]) == {"live": True}  # inert outside


# ── LiteLLM (module-level function, not a bound method) ──────────────────────


def test_module_level_entry_point_is_patched() -> None:
    mod = types.ModuleType("_fake_litellm")
    mod.completion = lambda **kw: {"live": True}  # type: ignore[attr-defined]
    _patch_module_function(
        mod, "completion", model_key="model",
        input_extractor=lambda kw: kw.get("messages"), reconstruct=_reconstruct_openai_chat,
    )
    with tracely.fixtures(_bundle("gpt-4o", {"role": "assistant", "content": "recorded"})):
        resp = mod.completion(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert resp.choices[0].message.content == "recorded"
    assert mod.completion(model="gpt-4o", messages=[]) == {"live": True}


def test_module_patch_is_idempotent() -> None:
    mod = types.ModuleType("_fake_litellm2")
    mod.completion = lambda **kw: {"live": True}  # type: ignore[attr-defined]
    for _ in range(3):
        _patch_module_function(
            mod, "completion", model_key="model",
            input_extractor=lambda kw: kw.get("messages"), reconstruct=_reconstruct_openai_chat,
        )
    with tracely.fixtures(_bundle("gpt-4o", {"role": "assistant", "content": "once"})):
        assert mod.completion(model="gpt-4o", messages=[]).choices[0].message.content == "once"


# ── the general safety net ────────────────────────────────────────────────────


def test_unused_recordings_are_reported(caplog: pytest.LogCaptureFixture) -> None:
    """The catch-all for a provider nobody patched: it went live, so its recording is still
    sitting there when the block ends."""
    with caplog.at_level(logging.WARNING, logger="tracely"):
        with tracely.fixtures(_bundle("gpt-4o", {"role": "assistant", "content": "never asked for"})):
            pass
    assert "left 1 recorded call(s) unused" in caplog.text
    assert "llm:gpt-4o ×1" in caplog.text


def test_no_warning_when_everything_was_replayed(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="tracely"):
        with tracely.fixtures(_bundle("gpt-4o", {"role": "assistant", "content": "used"})):
            tracely.call_llm("gpt-4o", lambda: pytest.fail("must not run live"))
    assert "unused" not in caplog.text


def test_unconsumed_lists_what_is_left() -> None:
    assert _unconsumed({"llm": {"m": [{}, {}]}, "tools": {"t": []}}) == ["llm:m ×2"]
    assert _unconsumed(None) == []
