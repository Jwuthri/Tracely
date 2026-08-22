"""The calibration queue may only serve verdicts a human can actually review.

Scores and spans live in different stores with no cascade, so deleting a conversation (or letting
the events TTL expire it) leaves the scores behind. Served for review, those render as a card with
no input, no output and nothing to grade — 40% of one real workspace's queue. The counts have to
agree with the queue too, or "1 / 50" is a denominator nobody can finish.
"""

from __future__ import annotations

import pytest

from tracely.infrastructure.clickhouse import async_reader


class FakeClient:
    """Captures the SQL so we can assert on the filters the queue applies."""

    def __init__(self):
        self.sql = ""
        self.params: dict = {}

    async def query(self, sql, parameters=None):
        self.sql = " ".join(sql.split())
        self.params = parameters or {}

        class R:
            column_names: list = []
            result_rows: list = []

        return R()


@pytest.fixture
def fake(monkeypatch):
    c = FakeClient()

    async def _get():
        return c

    monkeypatch.setattr(async_reader, "get_async_client", _get)
    return c


async def test_queue_only_serves_scores_whose_trace_still_exists(fake):
    await async_reader.evaluator_score_queue("p1", "tracely.run.outcome")
    assert "trace_id IN (SELECT trace_id FROM events" in fake.sql
    # ...and that subquery is scoped + excludes Tracely's own runs, like every other listing
    assert "WHERE project_id = {p:String} AND internal_kind = ''" in fake.sql
    assert fake.params["p"] == "p1"


async def test_queue_skips_tombstoned_scores(fake):
    """FINAL collapses row versions; it does not drop deleted ones."""
    await async_reader.evaluator_score_queue("p1", "n")
    assert "is_deleted = 0" in fake.sql


async def test_catalog_counts_match_what_the_queue_serves(fake):
    await async_reader.evaluator_catalog("p1")
    assert "is_deleted = 0" in fake.sql
    assert "trace_id IN (SELECT trace_id FROM events" in fake.sql


async def test_queue_still_filters_by_name_and_verdict(fake):
    await async_reader.evaluator_score_queue("p1", "tracely.run.quality", verdict="fail")
    assert "name = {n:String}" in fake.sql
    assert fake.params["n"] == "tracely.run.quality"
    assert fake.params["v"] == "FAIL"  # upper-cased for the caller
