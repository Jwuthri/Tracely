"""Source-level guards on the two ClickHouse read rules that nothing else can enforce.

Both tables are `ReplacingMergeTree`, so a row is only ever "the current one" once the duplicate
versions have been collapsed — which happens at read time via `FINAL`. `scores` in particular is
partitioned by `created_at`, the WRITE time, so re-grading a trace in a later calendar month writes
the same score `id` into a different partition and background merges can never collapse the two.
`FINAL` is the only thing that reads them as one row (see the comment in `ddl/0002_scores.up.sql`).

Grepping the source is a blunt instrument, but it is the only one available: a missing FINAL is not
a crash, an exception, or a failing query — it is a score silently reported twice, potentially with
the stale verdict first. A test that runs in 5ms beats finding that in production.
"""

from __future__ import annotations

import re
from pathlib import Path

_CH_DIR = Path(__file__).resolve().parents[1] / "tracely" / "infrastructure" / "clickhouse"

# `FROM <table>` not followed by FINAL. Tolerates the quote/space runs the string-concatenated SQL
# leaves between clauses, and an alias in either form (`FROM scores AS s FINAL`, `FROM scores s
# FINAL`) — the alias sits between the table and the keyword.
_UNFINAL = r"FROM\s+{table}\b(?![\s\"']*(?:(?:AS[\s\"']+)?\w+[\s\"']+)?FINAL)"

# `deletes.py` issues lightweight DELETEs (`DELETE FROM events WHERE …`), which take no FINAL, and
# `migrations.py` runs the DDL itself.
_EXEMPT = {"deletes.py", "migrations.py"}


def _offenders(table: str) -> list[str]:
    pattern = re.compile(_UNFINAL.format(table=table), re.IGNORECASE)
    hits: list[str] = []
    for path in sorted(_CH_DIR.rglob("*.py")):
        if path.name in _EXEMPT:
            continue
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]  # a comment mentioning `FROM scores` is not a query
            if pattern.search(code):
                hits.append(f"{path.name}:{i}: {line.strip()}")
    return hits


def test_scores_reads_are_final():
    """Non-negotiable: `scores` duplicates survive on disk across month boundaries, so a read
    without FINAL returns a re-graded score twice."""
    assert _offenders("scores") == []


def test_events_reads_are_final():
    """Same rule for `events`: a span re-delivered by a retrying OTLP exporter is two rows until
    merged, and any `count()` over them reports a span total nothing else in the UI agrees with."""
    assert _offenders("events") == []


# ── the threads list's sortable headers ───────────────────────────────────────
# ORDER BY cannot be parameterized, so the sort key is the one piece of this query built by string
# interpolation. These pin the whitelist that keeps it safe, and the tie-break that keeps
# LIMIT/OFFSET paging honest once the sort column has ties (which is the normal case).

from tracely.infrastructure.clickhouse.async_reader import (  # noqa: E402
    SESSION_SORTS,
    session_order_clause,
)


def test_every_sort_key_maps_to_a_known_expression():
    for key in SESSION_SORTS:
        assert session_order_clause(key, "desc").startswith(f"ORDER BY {SESSION_SORTS[key]} DESC")


def test_unknown_sort_falls_back_instead_of_interpolating():
    """A renamed column in a bookmarked URL shows the default order; it never reaches the query."""
    for hostile in ("", "cost", "1; DROP TABLE events", "last_ts DESC, 1", None):
        clause = session_order_clause(hostile, "desc")  # type: ignore[arg-type]
        assert clause == "ORDER BY last_ts DESC, last_ts DESC, thread ASC"


def test_direction_is_two_valued():
    assert "ASC, last_ts DESC" in session_order_clause("tokens", "asc")
    for junk in ("ASC; DELETE", "descending", "", None):
        assert " DESC, last_ts DESC" in session_order_clause("tokens", junk)  # type: ignore[arg-type]


def test_every_sort_is_tie_broken():
    """Without this, page 2 of a duration-sorted list repeats rows from page 1 and drops others."""
    for key in SESSION_SORTS:
        for order in ("asc", "desc"):
            assert ", last_ts DESC" in session_order_clause(key, order)


def test_the_order_is_total():
    """The last tie-break must be a column that is UNIQUE per row, or the order still is not total
    and LIMIT/OFFSET keeps dropping threads.

    This is the regression: `recent` sorts on `last_ts`, so the clause used to end
    "last_ts DESC, last_ts DESC" — a tie-break on the very column being tied. A whole-workspace
    export paged 200 at a time and silently came back short."""
    for key in SESSION_SORTS:
        for order in ("asc", "desc"):
            clause = session_order_clause(key, order)
            assert clause.endswith(", thread ASC")
            assert clause[: -len(", thread ASC")].count("thread") == 0
