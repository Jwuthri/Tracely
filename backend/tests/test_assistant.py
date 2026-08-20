"""The dashboard chat widget: what reaches the model, whose key pays, and what is stored.

The persistence half runs against a real SQLite database rather than a mocked repository — the
ownership rule (`user_id IS NULL` vs `= :uid`) is exactly the kind of thing a mock would agree
with while the SQL quietly matched nothing.
"""

from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tracely.infrastructure.db import models
from tracely.infrastructure.llm import provider
from tracely.services import assistant_service as svc


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A real database behind the service, so the repository's own SQL is what runs."""
    engine = create_engine(f"sqlite:///{tmp_path}/assistant.db")
    models.AssistantChat.__table__.create(engine)
    monkeypatch.setattr(svc, "SyncSessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    return engine


def _stream(*events):
    """An async generator over `events` — what a stubbed `stream_agent` hands back."""

    async def gen():
        for e in events:
            yield e

    return gen()


@pytest.fixture
def model(monkeypatch):
    """A stubbed agent that records what it was asked. Returns the recording dict."""
    seen: dict = {}
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        svc.provider,
        "stream_agent",
        lambda prompt, **kw: seen.update(prompt=prompt, **kw)
        or _stream({"type": "final", "text": "  hello  ", "usage": {}}),
    )
    return seen


async def turn(*args, **kw) -> dict:
    """Drive one turn to completion and return its terminal frame — the shape the widget acts on.

    Kept here rather than in the service: the streaming API is the one that ships, so the tests
    consume it the way the router does instead of testing a convenience wrapper nothing calls.
    """
    frames = [f async for f in svc.answer_stream(*args, **kw)]
    return frames[-1]


# ---------------------------------------------------------------- the prompt


def test_transcript_keeps_the_tail_oldest_first_and_names_the_page():
    msgs = [{"role": "user", "content": f"q{i}"} for i in range(svc.MAX_TURNS + 5)]
    msgs.append({"role": "assistant", "content": "an answer"})
    out = svc._transcript("p1", msgs, "/traces/abc")

    assert "/traces/abc" in out
    assert "q0" not in out  # the head is dropped, not the tail
    assert out.index(f"User: q{svc.MAX_TURNS + 4}") < out.index("Assistant: an answer")
    assert out.count("User:") + out.count("Assistant:") == svc.MAX_TURNS


def test_transcript_truncates_one_pasted_wall_of_text():
    out = svc._transcript("p1", [{"role": "user", "content": "x" * 50_000}], "")
    assert len(out) < svc.MAX_CHARS + 100


def test_only_the_newest_turn_re_reads_its_files(monkeypatch):
    """Re-inlining every attachment on every turn multiplies the bill by the chat's length."""
    monkeypatch.setattr(svc.s3, "get_blob", lambda key: b"the file body")
    old = {"role": "user", "content": "look", "attachments": [{"id": "a" * 32, "name": "old.txt"}]}
    new = {"role": "user", "content": "now this", "attachments": [{"id": "b" * 32, "name": "new.txt"}]}
    out = svc._transcript("p1", [old, {"role": "assistant", "content": "ok"}, new], "")

    assert out.count("the file body") == 1  # the newest one only
    assert "--- new.txt ---" in out
    assert "earlier attachments: old.txt" in out  # named, so the model knows it existed


def test_an_unreadable_attachment_is_still_announced():
    out = svc._transcript(
        "p1", [{"role": "user", "content": "read this", "attachments":
                [{"id": "c" * 32, "name": "report.pdf", "mime": "application/pdf", "size": 12}]}], ""
    )
    assert "report.pdf" in out and "not readable as text" in out


@pytest.mark.parametrize(
    "att,expected",
    [
        ({"name": "a.txt", "mime": "text/plain"}, True),
        ({"name": "trace.json", "mime": "application/json"}, True),
        # the browser guesses octet-stream for most of what a developer actually drags in
        ({"name": "run.log", "mime": "application/octet-stream"}, True),
        ({"name": "shot.png", "mime": "image/png"}, False),
        ({"name": "report.pdf", "mime": "application/pdf"}, False),
    ],
)
def test_what_counts_as_readable_text(att, expected):
    assert svc._is_text(att) is expected


def test_an_image_rides_along_as_a_content_block(monkeypatch):
    monkeypatch.setattr(svc.s3, "get_blob", lambda key: b"\x89PNG fake")
    blocks = svc._image_blocks("p1", [{"id": "d" * 32, "mime": "image/png", "name": "s.png"}])
    assert blocks[0]["type"] == "image_url"
    assert blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_an_image_too_big_to_be_worth_sending_is_skipped(monkeypatch):
    monkeypatch.setattr(svc.s3, "get_blob", lambda key: b"x" * (svc.MAX_IMAGE_BYTES + 1))
    assert svc._image_blocks("p1", [{"id": "e" * 32, "mime": "image/png"}]) == []


def test_title_is_the_opening_question_cut_at_a_word():
    assert svc.title_for("  why did   my gate fail? ") == "why did my gate fail?"
    long = svc.title_for("word " * 40)
    assert len(long) <= 60 and long.endswith("…") and not long.endswith(" …")
    assert svc.title_for("") == "New conversation"


# ---------------------------------------------------------------- whose key


async def test_no_llm_key_is_a_state_not_a_crash(db, monkeypatch):
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: False)
    assert await turn("p1", "u1", chat_id=None, message="hi") == {"type": "disabled"}


async def test_reply_is_the_model_text_on_the_configured_model(db, model):
    out = await turn("p1", "u1", chat_id=None, message="what is a gate?")

    assert out["reply"] == "hello"
    assert "what is a gate?" in model["prompt"]
    assert "Tracely" in model["system_prompt"]
    assert model["model"] == svc.settings.assistant_model
    assert model["reasoning_effort"] == svc.settings.assistant_reasoning_effort


async def test_the_agent_gets_the_callers_own_credentials(db, model):
    """We pay for the tokens; the TOOLS still run as the person chatting. Handing them the server
    key — or nothing — would either widen their reach or silently blind the agent."""
    await turn("p1", "u1", chat_id=None, message="hi", headers={"authorization": "Bearer theirs"})

    names = {t.name for t in model["tools"]}
    assert {"get_trace", "create_evaluator", "promote_cluster"} <= names
    # every tool closes over the caller's header, not ours
    assert svc.assistant_tools.build_tools.__module__ == "tracely.services.assistant_tools"


async def test_the_assistant_never_spends_the_customers_key(db, monkeypatch):
    """The widget explains OUR product; it must not bill — or depend on — a workspace's key."""
    monkeypatch.setattr(
        svc.provider,
        "use_project_key",
        lambda _p: pytest.fail("the assistant must not use the customer's key"),
    )
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        svc.provider, "stream_agent",
        lambda prompt, **kw: _stream({"type": "final", "text": "ok", "usage": {}}),
    )
    monkeypatch.setattr(provider.settings, "openrouter_api_key", "sk-ours")
    # a workspace with no key of its own still gets an answer, on the server key
    monkeypatch.setattr(provider, "_encrypted_key_for", lambda _p: None)
    out = await turn("p1", "u1", chat_id=None, message="hi")
    assert out["reply"] == "ok"


def test_server_scope_survives_the_hosted_bring_your_own_key_gate(monkeypatch):
    """REQUIRE_PROJECT_LLM_KEY makes an *unscoped* call fail closed — that guard catches paths
    that forgot `use_project_key`, and must not catch the one call we mean to pay for."""
    monkeypatch.setattr(provider.settings, "require_project_llm_key", True)
    monkeypatch.setattr(provider.settings, "openrouter_api_key", "sk-ours")

    assert provider.llm_enabled() is False  # unscoped: nothing server-wide applies
    with provider.use_server_key():
        assert provider.llm_enabled() is True
        assert provider.effective_openrouter_key() == "sk-ours"
    assert provider.llm_enabled() is False  # and the scope is restored on exit


# ---------------------------------------------------------------- what is stored


async def test_a_conversation_accumulates_across_turns(db, model):
    first = await turn("p1", "u1", chat_id=None, message="one")
    second = await turn("p1", "u1", chat_id=first["chat_id"], message="two")

    assert second["chat_id"] == first["chat_id"]  # same conversation, not a new one per turn
    assert second["title"] == "one"  # named by its opening question, and it stays named that
    with svc.SyncSessionLocal() as s:
        stored = svc.repo.assistant_chat_get(s, "p1", "u1", first["chat_id"]).messages
    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    assert "one" in model["prompt"] and "two" in model["prompt"]  # the model saw the whole thread


async def test_a_failed_turn_is_not_stored(db, monkeypatch):
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)

    async def explodes():
        raise RuntimeError("402")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(svc.provider, "stream_agent", lambda *a, **k: explodes())
    with pytest.raises(RuntimeError):
        await turn("p1", "u1", chat_id=None, message="hi")
    with svc.SyncSessionLocal() as s:
        assert svc.repo.assistant_chat_list(s, "p1", "u1") == []


async def test_a_turn_that_worked_but_said_nothing_is_a_failure(db, monkeypatch):
    """An agent that ran tools and then produced no text has done the work and told the user
    nothing. Storing that leaves a blank bubble in history for ever."""
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        svc.provider, "stream_agent",
        lambda *a, **k: _stream(
            {"type": "tool", "name": "list_traces", "args": {}},
            {"type": "final", "text": "   ", "usage": {}},
        ),
    )
    with pytest.raises(RuntimeError):
        await turn("p1", "u1", chat_id=None, message="hi")
    with svc.SyncSessionLocal() as s:
        assert svc.repo.assistant_chat_list(s, "p1", "u1") == []


async def test_tool_activity_reaches_the_caller_but_not_the_stored_transcript(db, monkeypatch):
    """The widget needs the tool frames live; history should stay the conversation the human had."""
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        svc.provider, "stream_agent",
        lambda *a, **k: _stream(
            {"type": "tool", "name": "get_trace", "args": {"trace_id": "t1"}},
            {"type": "tool_done", "name": "get_trace", "ok": True},
            {"type": "delta", "text": "it "},
            {"type": "delta", "text": "failed"},
            {"type": "final", "text": "it failed", "usage": {}},
        ),
    )
    frames = [f async for f in svc.answer_stream("p1", "u1", chat_id=None, message="why?")]

    assert [f["type"] for f in frames] == ["tool", "tool_done", "delta", "delta", "done"]
    with svc.SyncSessionLocal() as s:
        stored = svc.repo.assistant_chat_get(s, "p1", "u1", frames[-1]["chat_id"]).messages
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[-1]["content"] == "it failed"  # the answer, not the tool traffic behind it


async def test_one_persons_chat_is_not_anothers(db, model):
    mine = await turn("p1", "u1", chat_id=None, message="mine")

    # a guessed id belonging to someone else must not read OR overwrite their conversation
    theirs = await turn("p1", "u2", chat_id=mine["chat_id"], message="theirs")
    assert theirs["chat_id"] != mine["chat_id"]

    with svc.SyncSessionLocal() as s:
        assert [c.id for c in svc.repo.assistant_chat_list(s, "p1", "u1")] == [mine["chat_id"]]
        assert [c.id for c in svc.repo.assistant_chat_list(s, "p1", "u2")] == [theirs["chat_id"]]


async def test_the_endpoint_streams_frames_and_terminates(client, make_workspace, monkeypatch):
    """The wire format the widget decodes: `data: <json>` lines, `[DONE]` last. A turn that dies
    mid-stream is an `error` FRAME, not a 502 — the status was already 200 by then."""
    from tracely.api.routers import assistant as router

    monkeypatch.setattr(
        router.assistant_service, "answer_stream",
        lambda *a, **k: _stream(
            {"type": "tool", "name": "list_traces", "args": {}},
            {"type": "done", "chat_id": "c1", "title": "t", "reply": "hi"},
        ),
    )
    await make_workspace("sse", "sse_key", "sse@x.test")
    r = await client.post(
        "/api/assistant/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer sse_key"},
    )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [ln[6:] for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert '"type": "tool"' in frames[0]
    assert '"reply": "hi"' in frames[1]
    assert frames[-1] == "[DONE]"


async def test_a_dying_turn_is_a_frame_not_a_500(client, make_workspace, monkeypatch):
    from tracely.api.routers import assistant as router

    async def explodes(*a, **k):
        raise RuntimeError("no credit")
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(router.assistant_service, "answer_stream", explodes)
    await make_workspace("sse-err", "sse_err_key", "sseerr@x.test")
    r = await client.post(
        "/api/assistant/chat",
        json={"message": "hi"},
        headers={"Authorization": "Bearer sse_err_key"},
    )

    assert r.status_code == 200
    assert '"type": "error"' in r.text and "no credit" in r.text
    assert r.text.rstrip().endswith("[DONE]")


async def test_signed_out_callers_share_the_projects_chats(db, model):
    """An ingest key (and dev mode) has no human identity — `user_id IS NULL`, which SQL will
    never match with `= NULL`, so this is the case a mocked repository would fake passing."""
    made = await turn("p1", None, chat_id=None, message="hi")
    with svc.SyncSessionLocal() as s:
        assert [c.id for c in svc.repo.assistant_chat_list(s, "p1", None)] == [made["chat_id"]]
        assert svc.repo.assistant_chat_get(s, "p1", None, made["chat_id"]) is not None
