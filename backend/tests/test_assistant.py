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


@pytest.fixture
def model(monkeypatch):
    """A stubbed model that records what it was asked. Returns the recording dict."""
    seen: dict = {}
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        svc.provider, "run_text_agent", lambda prompt, **kw: seen.update(prompt=prompt, **kw) or "  hello  "
    )
    return seen


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


def test_no_llm_key_is_a_state_not_a_crash(db, monkeypatch):
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: False)
    assert svc.answer("p1", "u1", chat_id=None, message="hi") == {"disabled": True}


def test_reply_is_the_model_text_on_the_configured_model(db, model):
    out = svc.answer("p1", "u1", chat_id=None, message="what is a gate?")

    assert out["reply"] == "hello"
    assert "what is a gate?" in model["prompt"]
    assert "Tracely" in model["system_prompt"]
    assert model["model"] == svc.settings.assistant_model
    assert model["reasoning_effort"] == svc.settings.assistant_reasoning_effort


def test_the_assistant_never_spends_the_customers_key(db, monkeypatch):
    """The widget explains OUR product; it must not bill — or depend on — a workspace's key."""
    monkeypatch.setattr(
        svc.provider,
        "use_project_key",
        lambda _p: pytest.fail("the assistant must not use the customer's key"),
    )
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(svc.provider, "run_text_agent", lambda prompt, **kw: "ok")
    monkeypatch.setattr(provider.settings, "openrouter_api_key", "sk-ours")
    # a workspace with no key of its own still gets an answer, on the server key
    monkeypatch.setattr(provider, "_encrypted_key_for", lambda _p: None)
    assert svc.answer("p1", "u1", chat_id=None, message="hi")["reply"] == "ok"


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


def test_a_conversation_accumulates_across_turns(db, model):
    first = svc.answer("p1", "u1", chat_id=None, message="one")
    second = svc.answer("p1", "u1", chat_id=first["chat_id"], message="two")

    assert second["chat_id"] == first["chat_id"]  # same conversation, not a new one per turn
    assert second["title"] == "one"  # named by its opening question, and it stays named that
    with svc.SyncSessionLocal() as s:
        stored = svc.repo.assistant_chat_get(s, "p1", "u1", first["chat_id"]).messages
    assert [m["role"] for m in stored] == ["user", "assistant", "user", "assistant"]
    assert "one" in model["prompt"] and "two" in model["prompt"]  # the model saw the whole thread


def test_a_failed_turn_is_not_stored(db, monkeypatch):
    monkeypatch.setattr(svc.provider, "use_server_key", contextlib.nullcontext)
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)
    monkeypatch.setattr(
        svc.provider, "run_text_agent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("402"))
    )
    with pytest.raises(RuntimeError):
        svc.answer("p1", "u1", chat_id=None, message="hi")
    with svc.SyncSessionLocal() as s:
        assert svc.repo.assistant_chat_list(s, "p1", "u1") == []


def test_one_persons_chat_is_not_anothers(db, model):
    mine = svc.answer("p1", "u1", chat_id=None, message="mine")

    # a guessed id belonging to someone else must not read OR overwrite their conversation
    theirs = svc.answer("p1", "u2", chat_id=mine["chat_id"], message="theirs")
    assert theirs["chat_id"] != mine["chat_id"]

    with svc.SyncSessionLocal() as s:
        assert [c.id for c in svc.repo.assistant_chat_list(s, "p1", "u1")] == [mine["chat_id"]]
        assert [c.id for c in svc.repo.assistant_chat_list(s, "p1", "u2")] == [theirs["chat_id"]]


def test_signed_out_callers_share_the_projects_chats(db, model):
    """An ingest key (and dev mode) has no human identity — `user_id IS NULL`, which SQL will
    never match with `= NULL`, so this is the case a mocked repository would fake passing."""
    made = svc.answer("p1", None, chat_id=None, message="hi")
    with svc.SyncSessionLocal() as s:
        assert [c.id for c in svc.repo.assistant_chat_list(s, "p1", None)] == [made["chat_id"]]
        assert svc.repo.assistant_chat_get(s, "p1", None, made["chat_id"]) is not None
