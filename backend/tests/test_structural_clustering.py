"""Structural (ingest-time) clustering: near-duplicate judge prose must land in ONE cluster.

Exact signature hashing alone gives one cluster per failing trace — every LLM judge comment is
worded differently. `StructuralClusteringService` falls back to a token-overlap match; these
tests pin that it merges reworded versions of the same failure (even when the failed-evaluator
set flaps between traces) and still keeps genuinely different failure modes apart. In-memory
SQLite, no infra.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tracely.domain.failure.signature import FailureSignature, similarity, tokens
from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.models import Agent, ClusterMember, FailureCluster
from tracely.services.structural_clustering_service import StructuralClusteringService

PROJECT, AGENT = "p1", "a1"


@dataclass
class Ev:
    """EvalResult-shaped: what FailureSignature.compute reads."""

    name: str
    comment: str


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    # cluster tables + agents (the list query joins it); FKs to projects are inert on SQLite.
    FailureCluster.__table__.create(engine)
    ClusterMember.__table__.create(engine)
    Agent.__table__.create(engine)
    with Session(engine) as s:
        s.add(Agent(id=AGENT, project_id=PROJECT, slug="support-bot"))
        s.commit()
        yield s


def _cluster(s: Session, trace_id: str, comment: str, name: str = "tracely.run.quality") -> str:
    return StructuralClusteringService(s).cluster_failure(
        PROJECT, AGENT, trace_id, [Ev(name=name, comment=comment)], spans=[]
    )


def _counts(s: Session) -> list[int]:
    return sorted((c.count for c in s.execute(select(FailureCluster)).scalars()), reverse=True)


def test_reworded_same_failure_merges(session):
    """The screenshot case: four judge comments saying 'unhelpful answer' four ways."""
    ids = {
        _cluster(session, f"t{i}", c)
        for i, c in enumerate(
            [
                "The agent response is not helpful for the user's weather question",
                "The response is not a helpful reply to the user's weather question",
                "The agent answer provides no helpful weather information for the user question",
                "Agent output is unhelpful: it does not answer the user's weather question",
            ]
        )
    }
    assert len(ids) == 1
    assert _counts(session) == [4]


def test_different_failure_modes_stay_apart(session):
    _cluster(session, "t1", "The agent never called the weather tool")
    _cluster(session, "t2", "The agent leaked the system prompt verbatim")
    assert _counts(session) == [1, 1]


def test_different_evaluators_different_text_stay_apart(session):
    """Disjoint failed evaluators AND genuinely different text -> different issue."""
    _cluster(session, "t1", "the reply was rude and dismissive", name="tracely.run.quality")
    _cluster(session, "t2", "latency exceeded the configured budget", name="tracely.run.latency_ms")
    assert _counts(session) == [1, 1]


def test_same_error_text_merges_across_disjoint_evaluators(session):
    """Identical failure text is one issue no matter which evaluator caught it."""
    spans = [{"level": "ERROR", "status_message": "boom: connection reset by peer"}]
    a = StructuralClusteringService(session).cluster_failure(
        PROJECT, AGENT, "t1", [Ev("tracely.run.outcome", "")], spans
    )
    b = StructuralClusteringService(session).cluster_failure(
        PROJECT, AGENT, "t2", [Ev("tracely.tool.success", "")], spans
    )
    assert a == b
    assert _counts(session) == [2]


def test_flapping_advisory_judge_does_not_split_the_cluster(session):
    """The production dupe: the same masked pydantic error, once with only the outcome check
    failing and once with an advisory judge failing alongside — one issue, not two."""
    err = (
        "1 validation error for FindNearbyStoresToolArgs\nmax_results\n"
        "  Input should be less than or equal to 20 [type=less_than_equal, input_value=50]"
    )
    spans = [{"level": "ERROR", "status_message": err}]
    a = StructuralClusteringService(session).cluster_failure(
        PROJECT, AGENT, "t1", [Ev("tracely.run.outcome", "")], spans
    )
    b = StructuralClusteringService(session).cluster_failure(
        PROJECT,
        AGENT,
        "t2",
        [
            Ev("tracely.run.outcome", ""),
            Ev("tracely.run.quality", "the response never answered the question"),
        ],
        spans,
    )
    assert a == b
    assert _counts(session) == [2]


def test_whitespace_variants_share_one_key():
    """A traceback rendered with newlines vs spaces must hash to the same cluster_key."""
    a = FailureSignature.compute(
        [Ev("tracely.run.outcome", "validation error for X\n  max_results\n Input should be less")], []
    )
    b = FailureSignature.compute(
        [Ev("tracely.run.outcome", "validation error for X max_results Input should be less")], []
    )
    assert a.key == b.key


def test_create_race_joins_the_winning_row(session, monkeypatch):
    """Two workers, same brand-new signature: the loser's insert folds into the winner."""
    winner = _cluster(session, "t-other", "upstream returned http 502")
    svc = StructuralClusteringService(session)
    real_find = svc._find_existing
    misses = iter([True])  # first lookup misses, as if the winner committed just after it
    monkeypatch.setattr(
        svc, "_find_existing", lambda *a: None if next(misses, False) else real_find(*a)
    )
    monkeypatch.setattr(svc, "_find_similar", lambda *a: None)
    got = svc.cluster_failure(
        PROJECT, AGENT, "t-me", [Ev("tracely.run.quality", "upstream returned http 502")], []
    )
    assert got == winner
    assert _counts(session) == [2]


def test_structural_failure_joins_analyzed_issue(session):
    """After Analyze, embedding clusters carry a synthesized text-only signature; a fresh
    structural failure with the same wording folds in instead of opening a duplicate."""
    now = datetime.now(timezone.utc)
    session.add(
        FailureCluster(
            id="emb1",
            project_id=PROJECT,
            agent_id=AGENT,
            cluster_key="deadbeef00000000",
            label="Weather tool never called",
            taxonomy="execution: error",
            signature=" ## the weather tool was never called for the forecast question",
            method="embedding",
            count=3,
            status="OPEN",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    session.commit()
    got = _cluster(session, "t9", "the agent never called the weather tool for the forecast question")
    assert got == "emb1"


def test_ignored_cluster_is_not_resurrected(session):
    _cluster(session, "t1", "The agent response is not helpful for the user")
    session.execute(select(FailureCluster)).scalar_one().status = "IGNORED"
    session.commit()
    _cluster(session, "t2", "The agent answer is not helpful to the user")
    assert _counts(session) == [1, 1]


def test_negation_is_not_boilerplate():
    """'helpful' and 'not helpful' must not look like the same failure."""
    assert "not" in tokens("the response is not helpful")
    sig = FailureSignature.compute([Ev("tracely.run.quality", "the answer is helpful")], [])
    assert not sig.matches(
        FailureSignature.compute(
            [Ev("tracely.run.quality", "the answer is not helpful")], []
        ).signature,
        threshold=0.9,
    )


def test_similarity_edges():
    assert similarity(frozenset(), frozenset(["a"])) == 0.0
    assert similarity(frozenset(["a", "b"]), frozenset(["a", "b"])) == 1.0
    assert similarity(frozenset(["a", "b"]), frozenset(["b", "c"])) == pytest.approx(1 / 3)


def test_min_size_floor_hides_one_off_clusters(session):
    """`clusters_list_with_agent(min_size=...)` is what keeps single-occurrence noise off the page."""
    _cluster(session, "t1", "The agent leaked the system prompt verbatim")
    for i in range(5):
        _cluster(session, f"n{i}", f"The agent response is not helpful for the question {i}")

    assert [c.count for c, _ in repo.clusters_list_with_agent(session, PROJECT)] == [5, 1]
    assert [c.count for c, _ in repo.clusters_list_with_agent(session, PROJECT, 5)] == [5]
    assert repo.clusters_list_with_agent(session, PROJECT, 6) == []


def test_each_member_keeps_its_own_unmasked_reason(session):
    """The cluster's signature is masked so two traces can be recognised as the same failure; that
    same masking makes it useless as a per-trace explanation. Without the member summary the
    linked-traces list is a column of trace ids and nothing else."""
    _cluster(session, "t1", "The agent answered about order 4471 instead of order 9902")
    _cluster(session, "t2", "The agent answered about order 1234 instead of order 5678")

    members = {m.trace_id: m.summary for m in session.execute(select(ClusterMember)).scalars()}
    assert _counts(session) == [2], "masking should still merge them into one cluster"
    assert members["t1"].endswith("instead of order 9902")
    assert members["t2"].endswith("instead of order 5678")
