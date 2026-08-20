"""The checkpoint prune must reclaim space without costing a conversation its transcript.

Postgres-only by nature: the statements are jsonb + `make_interval`, so there is nothing to assert
against the suite's SQLite. Skips when no Postgres is listening, which is the CI default — the
same bargain `EVAL_CHAT_ENABLED=false` makes in conftest.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tracely.config import settings


def _postgres_listening() -> bool:
    """A one-second TCP probe against the checkpointer's DSN."""
    from urllib.parse import urlparse

    url = urlparse(settings.alembic_database_url.replace("postgresql+psycopg://", "postgresql://"))
    try:
        with socket.create_connection((url.hostname or "localhost", url.port or 5432), timeout=1):
            return True
    except OSError:
        return False


@pytest.fixture()
def saver(monkeypatch):
    """A real PostgresSaver, or skip. Resets the module-global so the disabled-by-conftest
    sentinel from an earlier test doesn't answer for us."""
    monkeypatch.setattr(settings, "eval_chat_enabled", True)
    from tracely.infrastructure.llm import checkpointer

    # Probe the port first. `get_checkpointer()` opens a pool that retries for a full minute
    # before reporting failure — fine for a worker starting up, a 60s tax on every CI run here.
    if not _postgres_listening():
        pytest.skip("no Postgres for the checkpointer")
    monkeypatch.setattr(checkpointer, "_saver", None)
    s = checkpointer.get_checkpointer()
    if s is None:
        pytest.skip("no Postgres for the checkpointer")
    return s


def _write_turns(saver, thread: str, n: int, ts: str | None = None) -> None:
    """Append `n` steps to one conversation, the way a sequential column grades item by item."""
    from langchain_core.messages import AIMessage, HumanMessage

    ts = ts or datetime.now(timezone.utc).isoformat()

    cfg = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    msgs: list = []
    for i in range(n):
        msgs = msgs + [HumanMessage(f"item {i}"), AIMessage(f"verdict {i}")]
        cfg = saver.put(
            cfg,
            {
                "v": 4,
                # Lexically increasing, because that is the ordering LangGraph itself resolves
                # "latest" by (`ORDER BY checkpoint_id DESC`) and therefore the one prune keeps.
                # Real ids are uuid6 — time-ordered; a uuid4 here would pick a random winner.
                "id": f"{i:032d}",
                "ts": ts,
                "channel_values": {"messages": list(msgs)},
                "channel_versions": {"messages": f"{i + 1:032d}.0"},
                "versions_seen": {},
            },
            {"source": "loop", "step": i},
            {"messages": f"{i + 1:032d}.0"},
        )


@pytest.mark.skipif(os.getenv("CI_NO_PG") == "1", reason="explicitly disabled")
def test_prune_keeps_the_conversation_resumable(saver):
    """The whole point: N steps collapse to one checkpoint, and the transcript survives intact.

    Guards the predicate that decides which blobs are orphaned. Keeping only the max version per
    channel would pass a one-channel test like this and silently drop the still-referenced older
    version of a channel the last step didn't rewrite — so the assertion is on the RESUMED
    messages, not on row counts alone.
    """
    from tracely.infrastructure.llm.checkpointer import prune

    thread = f"test-prune-{uuid4()}"
    settled = datetime.now(timezone.utc) - timedelta(hours=2)  # past the grace window
    _write_turns(saver, thread, 8, ts=settled.isoformat())

    cfg = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    assert len(saver.get_tuple(cfg).checkpoint["channel_values"]["messages"]) == 16

    prune()

    resumed = saver.get_tuple(cfg)
    assert resumed is not None, "prune deleted the live checkpoint"
    msgs = resumed.checkpoint["channel_values"]["messages"]
    assert len(msgs) == 16, "prune cost the conversation its history"
    assert msgs[-1].content == "verdict 7"

    with saver.conn.connection() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) n FROM checkpoints WHERE thread_id = %s", (thread,))
        assert cur.fetchone()["n"] == 1, "superseded steps were not collapsed"
        cur.execute("SELECT count(*) n FROM checkpoint_blobs WHERE thread_id = %s", (thread,))
        assert cur.fetchone()["n"] == 1, "orphan blob versions were not reclaimed"
        cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread,))
        cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread,))


@pytest.mark.skipif(os.getenv("CI_NO_PG") == "1", reason="explicitly disabled")
def test_prune_expires_a_conversation_past_retention(saver):
    """A conversation whose thread has aged out of ClickHouse cannot be resumed, so its
    checkpoint is dead weight — the half of the sweep that bounds growth over time rather than
    over one long conversation."""
    from tracely.infrastructure.llm.checkpointer import CHAT_RETENTION_DAYS, prune

    thread = f"test-prune-old-{uuid4()}"
    stale = datetime.now(timezone.utc) - timedelta(days=CHAT_RETENTION_DAYS + 1)
    _write_turns(saver, thread, 3, ts=stale.isoformat())

    prune()

    cfg = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    assert saver.get_tuple(cfg) is None, "an expired conversation was kept"
    with saver.conn.connection() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) n FROM checkpoint_blobs WHERE thread_id = %s", (thread,))
        assert cur.fetchone()["n"] == 0, "expired conversation left its blobs behind"


def test_prune_is_a_noop_without_a_checkpointer(monkeypatch):
    """Disabled chat (and CI) must get an empty dict, never an exception — the sweep is
    best-effort by contract."""
    from tracely.infrastructure.llm import checkpointer

    monkeypatch.setattr(settings, "eval_chat_enabled", False)
    monkeypatch.setattr(checkpointer, "_saver", None)
    assert checkpointer.prune() == {}


@pytest.mark.skipif(os.getenv("CI_NO_PG") == "1", reason="explicitly disabled")
def test_prune_leaves_an_in_flight_conversation_alone(saver):
    """The grace window, which is the whole reason this sweep is safe to run against a live
    deployment. `PostgresSaver.put` is pipelined and our pool is autocommit, so a step's blobs
    commit before its checkpoint row: for an instant they reference a checkpoint that does not
    exist yet. Without the window the sweep would reclaim the transcript out from under a judge
    that is mid-conversation."""
    from tracely.infrastructure.llm.checkpointer import prune

    thread = f"test-prune-live-{uuid4()}"
    _write_turns(saver, thread, 5)  # ts defaults to now — i.e. still being graded

    prune()

    cfg = {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}
    assert len(saver.get_tuple(cfg).checkpoint["channel_values"]["messages"]) == 10
    with saver.conn.connection() as c, c.cursor() as cur:
        cur.execute("SELECT count(*) n FROM checkpoint_blobs WHERE thread_id = %s", (thread,))
        assert cur.fetchone()["n"] == 5, "grace window did not protect an in-flight conversation"
        cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread,))
        cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread,))
