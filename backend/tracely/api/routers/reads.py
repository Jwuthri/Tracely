"""Minimal read API for the trace list + waterfall (ClickHouse-backed)."""

from __future__ import annotations

import json
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from starlette.concurrency import run_in_threadpool

from tracely.api.auth import get_project_id
from tracely.clickhouse import get_async_client
from tracely.db import SyncSessionLocal
from tracely.models import EvaluationCase, FailureCluster, GateRun
from tracely.schemas import SpanOut, TraceDetail
from tracely.textfmt import message_text

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


# thread/turn status reflects STRUCTURAL failures (errors, missing tools, silent failures); the
# subjective LLM-judge quality score is excluded here and shown per-trace instead.
_FAILING = (
    "SELECT trace_id FROM scores FINAL WHERE project_id = {p:String} "
    "AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = '' "
    "AND name != 'tracely.run.quality'"
)

_META_PREFIX = "tracely.metadata."


def _with_meta(row: dict) -> dict:
    """Parse the thread's aggregated `metadata` JSON (a Map dumped by ClickHouse) into a clean dict
    of user-set metadata, with the `tracely.metadata.` prefix stripped."""
    raw = row.get("metadata")
    meta: dict[str, str] = {}
    if raw:
        try:
            for k, v in json.loads(raw).items():
                meta[k[len(_META_PREFIX):] if k.startswith(_META_PREFIX) else k] = v
        except (ValueError, TypeError):
            pass
    row["metadata"] = meta
    return row


@router.get("/sessions")
async def list_sessions(limit: int = 50, project_id: str = Depends(get_project_id)) -> list[dict]:
    """Traces grouped into threads by conversation/session (a trace with no conversation is its own
    1-turn thread). Each row: first user input, last agent answer, turns, tokens, cost, status."""
    client = await get_async_client()
    res = await client.query(
        f"""
        SELECT
          if(conv != '', conv, trace_id)        AS thread,
          count()                               AS turns,
          argMin(t_input, ts_min)               AS first_input,
          argMax(t_output, ts_min)              AS last_output,
          sum(t_tokens)                         AS tokens,
          sum(t_input_tokens)                   AS input_tokens,
          sum(t_output_tokens)                  AS output_tokens,
          argMax(t_model, t_tokens)             AS model,
          sum(t_cost)                           AS cost,
          min(ts_min)                           AS first_ts,
          max(ts_max)                           AS last_ts,
          argMax(trace_id, ts_max)              AS last_trace_id,
          max(t_failing)                        AS failing,
          toJSONString(CAST(
            (groupArrayArray(mapKeys(t_meta)), groupArrayArray(mapValues(t_meta))),
            'Map(String, String)'))             AS metadata
        FROM (
          SELECT trace_id,
            max(conversation_id)                                          AS conv,
            argMinIf(input, start_time, input != '')                      AS t_input,
            if(anyIf(output, parent_span_id = '' AND output != '') != '',
               anyIf(output, parent_span_id = '' AND output != ''),
               argMaxIf(output, start_time, output != '' AND type != 'TOOL')) AS t_output,
            toUInt64(sum(arraySum(mapValues(usage_details))))             AS t_tokens,
            toUInt64(sum(usage_details['input']))                         AS t_input_tokens,
            toUInt64(sum(usage_details['output']))                        AS t_output_tokens,
            argMaxIf(model_id, arraySum(mapValues(usage_details)),
                     type = 'GENERATION' AND model_id != '')              AS t_model,
            toFloat64(sum(arraySum(mapValues(cost_details))))             AS t_cost,
            min(start_time)                                               AS ts_min,
            max(coalesce(end_time, start_time))                           AS ts_max,
            maxIf(1, trace_id IN ({_FAILING}))                            AS t_failing,
            CAST(
              (groupArrayArray(mapKeys(mapFilter((k, v) -> startsWith(k, 'tracely.metadata.'), CAST(metadata, 'Map(String, String)')))),
               groupArrayArray(mapValues(mapFilter((k, v) -> startsWith(k, 'tracely.metadata.'), CAST(metadata, 'Map(String, String)'))))),
              'Map(String, String)')                                      AS t_meta
          FROM events FINAL WHERE project_id = {{p:String}}
          GROUP BY trace_id
        )
        GROUP BY thread
        ORDER BY last_ts DESC
        LIMIT {{n:UInt32}}
        """,
        parameters={"p": project_id, "n": limit},
    )
    return [_with_meta(dict(zip(res.column_names, row))) for row in res.result_rows]


@router.get("/search")
async def search(q: str = "", project_id: str = Depends(get_project_id)) -> list[dict]:
    """Global search for the ⌘K palette: conversations (by user message), issues, cases, gates."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    out: list[dict] = []
    client = await get_async_client()
    # Match any turn whose user message contains the query, then report the whole THREAD: its first
    # message as the label, its TOTAL turn count, and its latest trace — so a multi-turn conversation
    # links to /sessions (not a single matched turn) with the right turn count.
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
        out.append({"type": "trace", "label": message_text(first_input) or thread, "sub": f"{turns} turn(s)", "href": href})

    def registry():
        like = f"%{q}%"
        rows: list[dict] = []
        with SyncSessionLocal() as s:
            for cl in s.execute(
                select(FailureCluster).where(FailureCluster.project_id == project_id, FailureCluster.label.ilike(like)).limit(6)
            ).scalars():
                rows.append({"type": "issue", "label": cl.label, "sub": cl.taxonomy or "", "href": f"/clusters/{cl.id}"})
            for c in s.execute(
                select(EvaluationCase).where(EvaluationCase.project_id == project_id, EvaluationCase.title.ilike(like)).limit(6)
            ).scalars():
                rows.append({"type": "case", "label": c.title, "sub": c.status, "href": f"/cases/{c.id}"})
            for g in s.execute(
                select(GateRun).where(GateRun.project_id == project_id, GateRun.git_ref.ilike(like))
                .order_by(desc(GateRun.created_at)).limit(4)
            ).scalars():
                rows.append({"type": "gate", "label": g.git_ref or g.id[:8], "sub": g.status, "href": f"/gates/{g.id}"})
        return rows

    return out + await run_in_threadpool(registry)


@router.get("/sessions/{thread_id}")
async def get_session(thread_id: str, project_id: str = Depends(get_project_id)) -> dict:
    """The turns (traces) inside one thread, oldest-first — a simple conversation replay."""
    client = await get_async_client()
    res = await client.query(
        f"""
        SELECT trace_id, input, output, tokens, input_tokens, output_tokens, model, cost, latency_ms, ts, failing FROM (
          SELECT trace_id,
            max(conversation_id)                                          AS conv,
            argMinIf(input, start_time, input != '')                      AS input,
            if(anyIf(output, parent_span_id = '' AND output != '') != '',
               anyIf(output, parent_span_id = '' AND output != ''),
               argMaxIf(output, start_time, output != '' AND type != 'TOOL')) AS output,
            toUInt64(sum(arraySum(mapValues(usage_details))))             AS tokens,
            toUInt64(sum(usage_details['input']))                         AS input_tokens,
            toUInt64(sum(usage_details['output']))                        AS output_tokens,
            argMaxIf(model_id, arraySum(mapValues(usage_details)),
                     type = 'GENERATION' AND model_id != '')              AS model,
            toFloat64(sum(arraySum(mapValues(cost_details))))             AS cost,
            dateDiff('millisecond', min(start_time), max(coalesce(end_time, start_time))) AS latency_ms,
            min(start_time)                                               AS ts,
            maxIf(1, trace_id IN ({_FAILING}))                            AS failing
          FROM events FINAL WHERE project_id = {{p:String}}
          GROUP BY trace_id
        )
        WHERE if(conv != '', conv, trace_id) = {{th:String}}
        ORDER BY ts ASC
        """,
        parameters={"p": project_id, "th": thread_id},
    )
    turns = [dict(zip(res.column_names, row)) for row in res.result_rows]

    # attach each turn's auto-eval scores (the same the trace page shows)
    tids = [t["trace_id"] for t in turns]
    if tids:
        sres = await client.query(
            "SELECT trace_id, name, evaluation_level, observation_id, value, verdict, comment, data_type "
            "FROM scores FINAL WHERE project_id = {p:String} AND trace_id IN {t:Array(String)} "
            "AND source = 'EVAL' AND evaluation_case_id = '' ORDER BY evaluation_level, name",
            parameters={"p": project_id, "t": tids},
        )
        by_trace: dict[str, list[dict]] = defaultdict(list)
        for row in sres.result_rows:
            d = dict(zip(sres.column_names, row))
            by_trace[d.pop("trace_id")].append(d)
        for t in turns:
            t["scores"] = by_trace.get(t["trace_id"], [])
            t["verdict"] = (
                "FAIL" if any(s["verdict"] == "FAIL" for s in t["scores"])
                else ("PASS" if t["scores"] else None)
            )
    return {"thread_id": thread_id, "turns": turns}


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, project_id: str = Depends(get_project_id)) -> TraceDetail:
    client = await get_async_client()
    res = await client.query(
        """
        SELECT span_id, parent_span_id, name, type, level, status_message,
               start_time, end_time, agent_id, agent_run_id, turn_id, step_name,
               model_id, input, output, metadata,
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
                metadata={str(k): str(v) for k, v in (d.get("metadata") or {}).items()},
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
