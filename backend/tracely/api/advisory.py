"""Fetch a project's advisory score-names for the async read routers.

The roll-up-verdict policy (see `domain.evaluation.verdict`) excludes "advisory" evaluators' FAILs.
Which evaluators are advisory lives in Postgres (evaluator config), so this bridges the sync registry
session onto the async read path — one place, so every endpoint that computes a verdict (threads
list, trace detail, session, trends) sources the exclusion set identically.
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from tracely.infrastructure.db import repositories as repo
from tracely.infrastructure.db.engine import SyncSessionLocal


async def advisory_score_names(project_id: str) -> list[str]:
    def work() -> list[str]:
        with SyncSessionLocal() as s:
            return repo.advisory_score_names(s, project_id)

    return await run_in_threadpool(work)
