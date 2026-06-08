"""⌘K global search across conversations, issues, cases, and gates."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.infrastructure.clickhouse.client import get_async_client
from tracely.infrastructure.db.engine import SyncSessionLocal
from tracely.infrastructure.db.models import EvaluationCase, FailureCluster, GateRun
from tracely.infrastructure.text import message_text

router = APIRouter(prefix="/api")


@router.get("/search")
async def search(q: str = "", project_id: str = Depends(get_project_id)) -> list[dict]:
    """Match any turn whose user message contains the query, then report the whole THREAD: its
    first message as the label, its TOTAL turn count, and its latest trace — so a multi-turn
    conversation links to /sessions (not a single matched turn) with the right turn count."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    out: list[dict] = []
    client = await get_async_client()
    res = await client.query(
        """
        SELECT thread, argMin(ti, tmin) AS first_input,
               argMax(trace_id, tmax) AS last_trace, count() AS turns, max(tmax) AS last_ts
        FROM (
          SELECT trace_id,
                 if(max(conversation_id) != '', max(conversation_id), trace_id) AS thread,
                 argMinIf(input, start_time, input != '') AS ti,
                 positionCaseInsensitive(argMinIf(input, start_time, input != ''), {q:String}) > 0 AS matched,
                 min(start_time) AS tmin, max(coalesce(end_time, start_time)) AS tmax
          FROM events FINAL WHERE project_id = {p:String} GROUP BY trace_id
        )
        GROUP BY thread HAVING max(matched) > 0
        ORDER BY last_ts DESC LIMIT 8
        """,
        parameters={"p": project_id, "q": q},
    )
    for thread, first_input, last_trace, turns, _ in res.result_rows:
        href = f"/sessions/{thread}" if turns > 1 else f"/traces/{last_trace}"
        out.append({
            "type": "trace",
            "label": message_text(first_input) or thread,
            "sub": f"{turns} turn(s)",
            "href": href,
        })

    def registry_rows():
        like = f"%{q}%"
        rows: list[dict] = []
        with SyncSessionLocal() as s:
            for cl in s.execute(
                select(FailureCluster)
                .where(FailureCluster.project_id == project_id, FailureCluster.label.ilike(like))
                .limit(6)
            ).scalars():
                rows.append({
                    "type": "issue", "label": cl.label, "sub": cl.taxonomy or "",
                    "href": f"/clusters/{cl.id}",
                })
            for c in s.execute(
                select(EvaluationCase)
                .where(EvaluationCase.project_id == project_id, EvaluationCase.title.ilike(like))
                .limit(6)
            ).scalars():
                rows.append({
                    "type": "case", "label": c.title, "sub": c.status, "href": f"/cases/{c.id}",
                })
            for g in s.execute(
                select(GateRun)
                .where(GateRun.project_id == project_id, GateRun.git_ref.ilike(like))
                .order_by(desc(GateRun.created_at))
                .limit(4)
            ).scalars():
                rows.append({
                    "type": "gate", "label": g.git_ref or g.id[:8], "sub": g.status,
                    "href": f"/gates/{g.id}",
                })
        return rows

    return out + await run_in_threadpool(registry_rows)
