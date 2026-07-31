"""Structural (ingest-time) clustering: near-duplicate judge prose must land in ONE cluster.

Exact signature hashing alone gives one cluster per failing trace — every LLM judge comment is
worded differently. `StructuralClusteringService` falls back to a token-overlap match; these
tests pin that it merges reworded versions of the same failure and still keeps different
failure modes (and different evaluators) apart. In-memory SQLite, no infra.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def test_different_evaluators_never_merge(session):
    """Same words, different failed evaluator -> different issue. The hard gate."""
    _cluster(session, "t1", "the call timed out", name="tracely.run.quality")
    _cluster(session, "t2", "the call timed out", name="tracely.run.latency_ms")
    assert _counts(session) == [1, 1]


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
