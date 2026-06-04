"""Minimal read API for the trace list + waterfall (ClickHouse-backed)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from tracely.api.auth import get_project_id
from tracely.clickhouse import get_async_client
from tracely.schemas import SpanOut, TraceDetail

router = APIRouter(prefix="/api")


@router.get("/traces")
async def list_traces(limit: int = 20, project_id: str = Depends(get_project_id)) -> list[dict]:
    client = await get_async_client()
    res = await client.query(
        """
        SELECT trace_id,
               min(start_time)                       AS ts,
               count()                               AS spans,
               anyIf(name, parent_span_id = '')      AS root_name,
               anyIf(agent_id, parent_span_id = '')  AS agent_id,
               maxIf(1, level = 'ERROR')             AS has_error
        FROM events
        WHERE project_id = {p:String}
        GROUP BY trace_id
        ORDER BY ts DESC
        LIMIT {n:UInt32}
        """,
        parameters={"p": project_id, "n": limit},
    )
    rows = [dict(zip(res.column_names, row)) for row in res.result_rows]
    # attach the auto-eval verdict per trace
    ev = await client.query(
        "SELECT trace_id, maxIf(1, verdict = 'FAIL') AS fail FROM scores FINAL "
        "WHERE project_id = {p:String} AND source = 'EVAL' AND evaluation_case_id = '' GROUP BY trace_id",
        parameters={"p": project_id},
    )
    verdict = {r[0]: ("FAIL" if r[1] else "PASS") for r in ev.result_rows}
    for r in rows:
        r["eval"] = verdict.get(r["trace_id"])
    return rows


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, project_id: str = Depends(get_project_id)) -> TraceDetail:
    client = await get_async_client()
    res = await client.query(
        """
        SELECT span_id, parent_span_id, name, type, level, status_message,
               start_time, end_time, agent_id, agent_run_id, turn_id, step_name,
               model_id, input, output,
               toUInt64(arraySum(mapValues(usage_details)))               AS tokens,
               toFloat64(arraySum(mapValues(cost_details)))               AS cost
        FROM events FINAL
        WHERE project_id = {p:String} AND trace_id = {t:String}
        ORDER BY start_time
        """,
        parameters={"p": project_id, "t": trace_id},
    )
    spans: list[SpanOut] = []
    for row in res.result_rows:
        d = dict(zip(res.column_names, row))
        latency = None
        if d.get("end_time") and d.get("start_time"):
            latency = (d["end_time"] - d["start_time"]).total_seconds() * 1000.0
        spans.append(
            SpanOut(
                span_id=d["span_id"],
                parent_span_id=d["parent_span_id"],
                name=d["name"],
                type=d["type"],
                level=d["level"],
                status_message=d["status_message"],
                start_time=d["start_time"],
                end_time=d["end_time"],
                latency_ms=latency,
                agent_id=d["agent_id"],
                agent_run_id=d["agent_run_id"],
                turn_id=d["turn_id"],
                step_name=d["step_name"],
                model_id=d["model_id"],
                tokens=int(d.get("tokens") or 0),
                cost=float(d.get("cost") or 0.0),
                input=d["input"],
                output=d["output"],
            )
        )
    sres = await client.query(
        "SELECT name, evaluation_level, observation_id, value, verdict, comment, data_type "
        "FROM scores FINAL WHERE project_id = {p:String} AND trace_id = {t:String} AND source = 'EVAL' "
        "AND evaluation_case_id = '' "  # online evals only (exclude regression/gate verdicts)
        "ORDER BY evaluation_level, name",
        parameters={"p": project_id, "t": trace_id},
    )
    scores = [dict(zip(sres.column_names, row)) for row in sres.result_rows]
    eval_verdict = (
        "FAIL" if any(s["verdict"] == "FAIL" for s in scores) else ("PASS" if scores else None)
    )
    return TraceDetail(trace_id=trace_id, spans=spans, scores=scores, eval_verdict=eval_verdict)
