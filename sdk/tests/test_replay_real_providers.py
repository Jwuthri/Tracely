"""End-to-end check that the auto-instrument replay bridge actually intercepts the REAL provider
client classes (not the stand-ins from test_replay_autoinstrument.py) and that the reconstructed
response objects satisfy real provider-SDK access patterns.

Belt-and-suspenders for the unverified part of the work: the class-patch is correct against the
SDKs' actual module layout, and the duck-typed objects pass for real responses where it counts —
without ever hitting the network.
"""

from __future__ import annotations

import pytest

import tracely_sdk as tracely

openai = pytest.importorskip("openai")
anthropic = pytest.importorskip("anthropic")


@pytest.fixture(scope="module", autouse=True)
def _init() -> None:
    tracely.init(env="prod", instrument=False)


# ── OpenAI ────────────────────────────────────────────────────────────────────


def test_real_openai_client_is_intercepted_and_returns_usable_object() -> None:
    """`OpenAI().chat.completions.create(...)` under fixtures() never touches the network and the
    returned object reads exactly like a real ChatCompletion at the dominant access points."""
    client = openai.OpenAI(api_key="sk-fake-no-network")  # fake key — if we hit the network this errors
    bundle = {
        "version": 2,
        "llm": [
            {
                "model": "gpt-4o-mini",
                "input": [{"role": "user", "content": "hi"}],
                "output": {
                    "role": "assistant",
                    "content": "recorded reply",
                    "tool_calls": [
                        {
                            "id": "call_42",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
                        }
                    ],
                },
                "error": None,
            }
        ],
    }
    with tracely.fixtures(bundle):
        resp = client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
        )
    # exactly the OpenAI access pattern an auto-instrumented agent uses
    assert resp.choices[0].message.content == "recorded reply"
    tc = resp.choices[0].message.tool_calls[0]
    assert tc.id == "call_42"
    assert tc.function.name == "get_weather"
    assert tc.function.arguments == '{"city": "SF"}'


async def test_real_async_openai_client_is_intercepted() -> None:
    client = openai.AsyncOpenAI(api_key="sk-fake-no-network")
    bundle = {
        "version": 2,
        "llm": [
            {
                "model": "gpt-4o-mini",
                "input": None,
                "output": {"role": "assistant", "content": "async recorded"},
                "error": None,
            }
        ],
    }
    with tracely.fixtures(bundle):
        resp = await client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
        )
    assert resp.choices[0].message.content == "async recorded"


# ── Anthropic ─────────────────────────────────────────────────────────────────


def test_real_anthropic_client_is_intercepted_and_returns_usable_object() -> None:
    """`Anthropic().messages.create(...)` under fixtures() — same belt-and-suspenders for the
    Anthropic shape (`resp.content[]` blocks, not `choices`)."""
    client = anthropic.Anthropic(api_key="sk-fake-no-network")
    bundle = {
        "version": 2,
        "llm": [
            {
                "model": "claude-3-5-sonnet-latest",
                "input": None,
                "output": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "let me check"},
                        {
                            "type": "tool_use",
                            "id": "tu_7",
                            "name": "get_weather",
                            "input": {"city": "SF"},
                        },
                    ],
                },
                "error": None,
            }
        ],
    }
    with tracely.fixtures(bundle):
        resp = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=128,
            messages=[{"role": "user", "content": "weather?"}],
        )
    # exactly the Anthropic access pattern (iterate blocks, check .type, read .text / .name / .input)
    blocks = list(resp.content)
    assert blocks[0].type == "text" and blocks[0].text == "let me check"
    assert blocks[1].type == "tool_use"
    assert blocks[1].id == "tu_7"
    assert blocks[1].name == "get_weather"
    assert blocks[1].input == {"city": "SF"}


def test_anthropic_canonical_shape_replays_against_real_client() -> None:
    """Recorded by the auto-instrument path (backend-normalized: content-string + OpenAI-style
    tool_calls). The bridge reconstructs Anthropic-shape blocks so an Anthropic-using agent's
    iteration over `resp.content` works regardless of which path captured the fixture."""
    client = anthropic.Anthropic(api_key="sk-fake-no-network")
    bundle = {
        "version": 2,
        "llm": [
            {
                "model": "claude-3-5-sonnet-latest",
                "input": None,
                "output": {
                    "content": "on it",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q": "x"}'},
                        }
                    ],
                },
                "error": None,
            }
        ],
    }
    with tracely.fixtures(bundle):
        resp = client.messages.create(
            model="claude-3-5-sonnet-latest", max_tokens=128, messages=[]
        )
    blocks = list(resp.content)
    assert blocks[0].type == "text" and blocks[0].text == "on it"
    assert blocks[1].type == "tool_use" and blocks[1].name == "search"
    assert blocks[1].input == {"q": "x"}  # JSON string arguments → dict input


# ── inert outside replay ──────────────────────────────────────────────────────


def test_real_clients_are_inert_outside_fixtures() -> None:
    """Outside a fixtures() block the patch is a strict no-op: the real method runs. We verify by
    triggering it with an obviously-fake key — if our patch were swallowing the call, no error
    would happen; if it's inert, the real client raises an auth error."""
    client = openai.OpenAI(api_key="sk-fake-no-network", max_retries=0)
    with pytest.raises(openai.OpenAIError):  # AuthenticationError or APIConnectionError — both fine
        client.chat.completions.create(
            model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
        )
