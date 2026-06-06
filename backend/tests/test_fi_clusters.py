"""Failure-cluster pruning — the project-wide-consistent rebuild (no infra).

`rebuild_clusters` only visits agents that have CURRENT failing traces; `_rebuild_agent`
deletes+rewrites just the agent it's given. An agent that drops out of the failing set (its
runs were fixed, or a reseed gave its traces new ids) is never visited, so without a prune its
clusters persist forever and accumulate across rebuilds. These tests drive `_prune_orphan_clusters`
directly against an in-memory SQLite DB holding only the two cluster tables (no pgvector column),
so no Postgres / ClickHouse / OpenAI is required.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tracely import fi
from tracely.models import ClusterMember, FailureCluster

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    # only the two cluster tables — FailureEmbedding's pgvector column won't build on SQLite, and
    # the FKs to projects/agents are inert here (SQLite doesn't enforce them by default).
    FailureCluster.__table__.create(engine)
    ClusterMember.__table__.create(engine)
    with Session(engine) as s:
        yield s


def _add_cluster(s: Session, project_id: str, agent_id: str, cluster_id: str,
                 trace_ids: list[str], status: str = "OPEN") -> None:
    s.add(FailureCluster(
        id=cluster_id, project_id=project_id, agent_id=agent_id, cluster_key=cluster_id[:16],
        label=cluster_id, method="embedding", count=len(trace_ids), status=status,
        first_seen_at=NOW, last_seen_at=NOW,
    ))
    for i, tid in enumerate(trace_ids):
        s.add(ClusterMember(cluster_id=cluster_id, trace_id=tid, is_medoid=(i == 0), added_at=NOW))
    s.commit()


def _cluster_ids(s: Session, project_id: str) -> set[str]:
    return set(s.execute(
        select(FailureCluster.id).where(FailureCluster.project_id == project_id)
    ).scalars())


def _member_cluster_ids(s: Session) -> set[str]:
    return set(s.execute(select(ClusterMember.cluster_id)).scalars())


def test_prune_drops_orphan_agents_keeps_rebuilt(session):
    # "keep" is in this rebuild; "orphan" dropped out of the failing set after a reseed.
    _add_cluster(session, "proj", "keep", "c-keep", ["t1", "t2"])
    _add_cluster(session, "proj", "orphan", "c-orphan-open", ["old1"])
    _add_cluster(session, "proj", "orphan", "c-orphan-promoted", ["old2"], status="PROMOTED")

    pruned = fi._prune_orphan_clusters(session, "proj", {"keep"})

    assert pruned == 2
    assert _cluster_ids(session, "proj") == {"c-keep"}
    # members of the pruned clusters are gone too — no dangling rows pointing at wiped traces.
    assert _member_cluster_ids(session) == {"c-keep"}


def test_prune_empty_keep_set_drops_all_in_project(session):
    # no agent is failing this run -> the project should end with zero clusters.
    _add_cluster(session, "proj", "a1", "c1", ["t1"])
    _add_cluster(session, "proj", "a2", "c2", ["t2"])

    pruned = fi._prune_orphan_clusters(session, "proj", set())

    assert pruned == 2
    assert _cluster_ids(session, "proj") == set()
    assert _member_cluster_ids(session) == set()


def test_prune_leaves_other_projects_untouched(session):
    _add_cluster(session, "proj", "orphan", "c1", ["t1"])
    _add_cluster(session, "other", "orphan", "c2", ["t2"])

    fi._prune_orphan_clusters(session, "proj", set())

    assert _cluster_ids(session, "proj") == set()
    assert _cluster_ids(session, "other") == {"c2"}  # scoped to project_id


def test_prune_noop_when_all_agents_kept(session):
    _add_cluster(session, "proj", "a1", "c1", ["t1"])
    _add_cluster(session, "proj", "a2", "c2", ["t2"])

    pruned = fi._prune_orphan_clusters(session, "proj", {"a1", "a2"})

    assert pruned == 0
    assert _cluster_ids(session, "proj") == {"c1", "c2"}
    assert _member_cluster_ids(session) == {"c1", "c2"}
