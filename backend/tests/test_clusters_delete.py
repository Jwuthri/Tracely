"""DELETE /api/clusters — multi-select cluster pruning.

Runs against the sync SQLite db the clusters router uses (same harness as the evaluators API
tests), so the repository delete (cluster + members, project-scoped) is exercised for real.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from tracely.infrastructure.db import models
from tracely.infrastructure.db.base import Base

_TABLES = [
    models.Project.__table__,
    models.IngestKey.__table__,
    models.User.__table__,
    models.Membership.__table__,
    models.Invitation.__table__,
    models.Evaluator.__table__,
    models.Agent.__table__,
    models.FailureCluster.__table__,
    models.ClusterMember.__table__,
]


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    yield eng
    await eng.dispose()


@pytest.fixture
def sync_db(tmp_path, monkeypatch, engine):
    sync_eng = create_engine(f"sqlite:///{tmp_path}/test.db")
    maker = sessionmaker(sync_eng)
    import tracely.api.routers.clusters as clusters_router
    import tracely.api.routers.evaluators as evaluators_router

    monkeypatch.setattr(clusters_router, "SyncSessionLocal", maker)
    monkeypatch.setattr(evaluators_router, "SyncSessionLocal", maker)  # workspace bootstrap
    yield maker
    sync_eng.dispose()


async def _owner_token(client) -> str:
    r = await client.post("/auth/register", json={"email": "o@x.test", "password": "hunter2-pw"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _seed_cluster(maker, project_id: str, label: str) -> str:
    """One cluster with two members, under a (new) agent in `project_id`."""
    with maker() as s:
        agent = models.Agent(id=str(uuid4()), project_id=project_id, slug=f"agent-{uuid4().hex[:6]}")
        cl = models.FailureCluster(
            id=str(uuid4()), project_id=project_id, agent_id=agent.id,
            cluster_key=uuid4().hex[:16], label=label, count=2,
        )
        s.add_all([agent, cl])
        s.flush()
        s.add_all([models.ClusterMember(cluster_id=cl.id, trace_id=f"tr-{i}") for i in (1, 2)])
        s.commit()
        return cl.id


async def test_delete_clusters_removes_rows_and_members(client, sync_db):
    tok = await _owner_token(client)
    project_id = (await client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})).json()["project_id"]
    keep = _seed_cluster(sync_db, project_id, "keep me")
    drop = _seed_cluster(sync_db, project_id, "prune me")

    r = await client.request(
        "DELETE", "/api/clusters",
        headers={"Authorization": f"Bearer {tok}"},
        json={"cluster_ids": [drop, drop, ""]},  # duplicates/blanks are ignored
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": 1}

    with sync_db() as s:
        assert [c.id for c in s.execute(select(models.FailureCluster)).scalars()] == [keep]
        assert list(s.execute(select(models.ClusterMember.cluster_id)).scalars()) == [keep, keep]


async def test_delete_clusters_is_project_scoped_and_idempotent(client, sync_db):
    tok = await _owner_token(client)
    other = _seed_cluster(sync_db, "some-other-project", "not yours")

    r = await client.request(
        "DELETE", "/api/clusters", headers={"Authorization": f"Bearer {tok}"}, json={"cluster_ids": [other]}
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": 0}  # another project's cluster is invisible, not deleted

    empty = await client.request(
        "DELETE", "/api/clusters", headers={"Authorization": f"Bearer {tok}"}, json={"cluster_ids": []}
    )
    assert empty.status_code == 400

    with sync_db() as s:
        assert s.get(models.FailureCluster, other) is not None
