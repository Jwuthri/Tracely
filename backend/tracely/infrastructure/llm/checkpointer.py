"""Durable judge conversations — LangGraph's Postgres checkpointer, wired to our database.

A sequential evaluator does not ask the model N independent questions; it holds ONE conversation
with it: the rubric as the system prompt, then item → verdict → item → verdict. Two reasons that
matters, and only the second is about cost:

1. It is what "sequential" means. The judge grading turn 6 has literally seen what it decided on
   turns 1–5, instead of a paraphrase of the last one pasted into a fresh prompt.
2. The prefix is byte-identical from one call to the next, so provider prompt caching charges the
   cached rate for everything but the new item.

The conversation has to survive the process, because turns are graded minutes apart in different
Celery tasks. That is what a checkpointer is for: LangGraph loads the thread's messages, appends
the new one, and persists the result — so the caller sends only the new item.

A conversation only ever grows in item order, and only inside an ordered pass. A message-level
column's conversation persists across the settled-thread passes: each pass appends just the NEW
turns, guided by the chain-progress record (`eval_chain_progress`); when the thread's turn order
changes under it (a late-arriving trace) or a full re-grade is forced, the pass calls
`reset_chat` and rebuilds from turn 1 — appending out of order, or appending a second copy of
graded items, would show the judge duplicated history and verdicts from the thread's future. A
step-level column's conversation spans one message and is rebuilt whenever that trace is
re-graded.

Tables (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`) are LangGraph's own, created by
`setup()` on the first call in each process. They are NOT Alembic-managed: the schema belongs to
the library, and pinning our migrations to its internals would break on its next release.
"""

from __future__ import annotations

import threading
from typing import Any

import structlog

from tracely.config import settings

log = structlog.get_logger(__name__)

_saver: Any = None
_lock = threading.Lock()


def _dsn() -> str:
    """LangGraph wants a bare libpq DSN; ours is a SQLAlchemy URL."""
    return settings.alembic_database_url.replace("postgresql+psycopg://", "postgresql://")


def get_checkpointer() -> Any:
    """The process-wide `PostgresSaver`, or None when it can't be reached.

    None is a supported answer, not a failure: the judge then grades the item on its own. Losing
    the transcript costs continuity, which is worth strictly less than the grade itself — the same
    bargain `llm_enabled()` makes for the whole judge.
    """
    global _saver
    if not settings.eval_chat_enabled:
        return None
    if _saver is not None:
        # `or None` here too, not just at the bottom: `_saver` is False once a lookup has failed,
        # and returning that sentinel raw made `get_checkpointer() is None` answer "a checkpointer
        # exists" on every call after the first. The judge then stopped pasting the transcript in
        # AND had no thread to read it from — sequential silently became batch, which is precisely
        # the failure this function's contract exists to prevent.
        return _saver or None
    with _lock:
        if _saver is None:
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool

                # A pool we own, not `from_conn_string`: that returns a context manager, and
                # entering it without holding the reference lets the generator be collected —
                # which runs its `finally` and closes the connection under us ("the connection is
                # closed", on the first grade). A pool also survives a Postgres restart, which a
                # single long-lived connection in a Celery worker does not.
                # `autocommit` + `dict_row` are PostgresSaver's requirements; `prepare_threshold=0`
                # keeps pooled connections from accumulating prepared statements.
                pool = ConnectionPool(
                    conninfo=_dsn(),
                    min_size=1,
                    max_size=settings.eval_chat_pool_size,
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                    open=True,
                )
                saver = PostgresSaver(pool)
                # Create the tables HERE rather than in a deploy step. `setup()` is idempotent and
                # costs one round-trip per process, while a deploy step is one more thing that can
                # be skipped — and was: prod ran every sequential grade against a `checkpoints`
                # table that did not exist, so the judge raised, returned no result, and the column
                # read "not applicable" instead of failing loudly. Doing it on the way in also makes
                # the failure land in the one place that already degrades gracefully: a setup that
                # can't run marks the checkpointer unavailable (one-shot grades, transcript pasted
                # in) instead of raising on every grade for the life of the process.
                saver.setup()
                _saver = saver
            except Exception as exc:
                log.warning("checkpointer_unavailable", error=str(exc))
                _saver = False  # remember the failure; don't retry per grade
    return _saver or None


# NOTE — the judge's verdict is a pydantic model, so it rides into the checkpoint alongside the
# messages, and LangGraph logs "Deserializing unregistered type … ScoreVerdict" on every resume.
# The obvious fix is `serde=JsonPlusSerializer(allowed_msgpack_modules=…)`, and it is a trap:
# passing ANY explicit allowlist switches the serializer from warn-and-allow to block-what-is-not-
# listed, and the list takes exact (module, classname) pairs with no wildcard. Two of our verdict
# models are built at runtime (`CategoryVerdict`, and a user's `json` contract), so any list we
# write is a list that can be incomplete — and an incomplete one turns a log line into a blocked
# resume. Left on the default deliberately. When LangGraph makes strict the default, the fix is to
# stop putting a pydantic instance in the state, not to guess at the enumeration.


def setup() -> None:
    """Create LangGraph's checkpoint tables. Idempotent; `get_checkpointer()` already does this on
    first use — this is the explicit hook (`python -m tracely.infrastructure.llm.checkpointer`) for
    creating them ahead of time, and it RAISES so a deploy check can't pass on a silent skip."""
    saver = get_checkpointer()
    if saver is None:
        raise RuntimeError("checkpointer unavailable — cannot create checkpoint tables")
    saver.setup()


def reset_chat(chat_id: str) -> None:
    """Delete a judge conversation so the next pass rebuilds it from item 1 — the companion to
    clearing its chain progress. Best-effort: with no checkpointer there is nothing to delete, and
    a failed delete only costs a dirtier transcript — never the grades themselves."""
    saver = get_checkpointer()
    if saver is None:
        return
    try:
        saver.delete_thread(chat_id)
    except Exception as exc:
        log.warning("chat_reset_failed", chat_id=chat_id, error=str(exc))


def chat_id(project_id: str, score_name: str, subject: str) -> str:
    """The thread a metric's conversation lives on: one per (workspace, column, subject).

    Per COLUMN because two evaluators are two different conversations with different rubrics, and
    per SUBJECT so a thread's transcript can't bleed into an unrelated conversation's.
    """
    return f"{project_id}:{score_name}:{subject}"


if __name__ == "__main__":  # `python -m tracely.infrastructure.llm.checkpointer`
    setup()
    log.info("checkpoint_tables_ready")
