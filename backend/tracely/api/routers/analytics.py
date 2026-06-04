"""Trends & analytics: time-series + roll-ups over traces, failures, gates, and clusters."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from tracely import clickhouse
from tracely.api.auth import get_project_id
from tracely.db import SyncSessionLocal
from tracely.models import EvaluationCase, FailureCluster, GateRun

router = APIRouter(prefix="/api")


@router.get("/trends")
async def trends(days: int = 14, project_id: str = Depends(get_project_id)) -> dict:
    days = max(1, min(days, 90))

    def work():
        c = clickhouse.get_client()
        # daily traces + failing traces, BOTH dated by the trace's own start_time (so failures<=traces);
        # a trace "failed" if it has any auto-detected EVAL FAIL score (no case id).
        rows = c.query(
            "SELECT toDate(start_time) AS d, uniqExact(trace_id) AS traces, "
            "uniqExactIf(trace_id, trace_id IN ("
            "  SELECT trace_id FROM scores FINAL WHERE project_id = {p:String} "
            "  AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = '')) AS failures "
            "FROM events FINAL "
            "WHERE project_id = {p:String} AND start_time >= subtractDays(now(), {d:UInt32}) "
            "GROUP BY d ORDER BY d",
            parameters={"p": project_id, "d": days},
        ).result_rows
        daily = [{"date": str(d), "traces": int(t), "failures": int(f)} for d, t, f in rows]

        def _scalar(sql: str) -> int:
            r = c.query(sql, parameters={"p": project_id}).result_rows
            return int(r[0][0]) if r and r[0][0] is not None else 0

        total_traces = _scalar("SELECT uniqExact(trace_id) FROM events FINAL WHERE project_id = {p:String}")
        total_failures = _scalar(
            "SELECT uniqExact(trace_id) FROM scores FINAL WHERE project_id = {p:String} "
            "AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = ''"
        )

        with SyncSessionLocal() as s:
            gates = s.execute(select(GateRun).where(GateRun.project_id == project_id)).scalars().all()
            gate_total = len(gates)
            gate_passed = sum(1 for g in gates if g.status == "PASS")
            by_day: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [passed, failed]
            for g in gates:
                if g.created_at and g.status in ("PASS", "FAIL"):
                    by_day[g.created_at.date().isoformat()][0 if g.status == "PASS" else 1] += 1
            gates_daily = [{"date": k, "passed": v[0], "failed": v[1]} for k, v in sorted(by_day.items())]

            clusters = s.execute(
                select(FailureCluster).where(FailureCluster.project_id == project_id)
            ).scalars().all()
            open_c = sum(1 for cl in clusters if cl.status == "OPEN")
            resolved_c = sum(1 for cl in clusters if cl.status == "PROMOTED")
            cases = s.execute(
                select(func.count()).select_from(EvaluationCase).where(EvaluationCase.project_id == project_id)
            ).scalar() or 0

            # MTTR proxy: hours from a cluster's first-seen to the regression case it was promoted into
            case_created = {
                cc.id: cc.created_at
                for cc in s.execute(
                    select(EvaluationCase).where(EvaluationCase.project_id == project_id)
                ).scalars().all()
            }
            spans = []
            for cl in clusters:
                if cl.status == "PROMOTED" and cl.candidate_case_id and cl.first_seen_at:
                    created = case_created.get(cl.candidate_case_id)
                    if created:
                        h = (created - cl.first_seen_at).total_seconds() / 3600.0
                        if h >= 0:
                            spans.append(h)
            mttr_hours = round(sum(spans) / len(spans), 1) if spans else None

        return {
            "days": days,
            "daily": daily,
            "gates_daily": gates_daily,
            "summary": {
                "total_traces": total_traces,
                "total_failures": total_failures,
                "failure_rate": round(total_failures / total_traces, 3) if total_traces else 0.0,
                "gate_runs": gate_total,
                "gate_pass_rate": round(gate_passed / gate_total, 3) if gate_total else 0.0,
                "cases": int(cases),
                "open_clusters": open_c,
                "resolved_clusters": resolved_c,
                "mttr_hours": mttr_hours,
            },
        }

    return await run_in_threadpool(work)
