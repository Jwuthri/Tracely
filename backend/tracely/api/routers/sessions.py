"""Session/thread endpoints: traces grouped into conversations + per-turn rollups."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends

from tracely.api.auth import get_project_id
from tracely.domain.traces.metadata import parse_thread_meta
from tracely.infrastructure.clickhouse.client import get_async_client

router = APIRouter(prefix="/api")

# Thread/turn status reflects STRUCTURAL failures (errors, missing tools, silent failures);
# the subjective LLM-judge quality score is excluded here and shown per-trace instead.
_FAILING = (
    "SELECT trace_id FROM scores FINAL WHERE project_id = {p:String} "
    "AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = '' "
    "AND name != 'tracely.run.quality'"
)


@router.get("/sessions")
async def list_sessions(
    limit: int = 50, project_id: str = Depends(get_project_id)
) -> list[dict]:
    """Traces grouped into threads by conversation/session (a trace with no conversation is its
    own 1-turn thread). Each row: first user input, last agent answer, turns, tokens, cost,
    status."""
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
            -- Prefer the EARLIEST GENERATION input (carries the actual user message in the chat
            -- array), fall back to the earliest non-empty input from any other span — so the
            -- conversation title isn't pinned to framework internals like CrewAI's agent-config
            -- payload or LlamaIndex's workflow-start event.
            if(argMinIf(input, start_time, input != '' AND type = 'GENERATION') != '',
               argMinIf(input, start_time, input != '' AND type = 'GENERATION'),
               argMinIf(input, start_time, input != ''))                    AS t_input,
            -- Pick the LATEST GENERATION output as the run's answer (skip TOOL results and
            -- framework CHAIN router signals like LangGraph's `__end__`). Fall back to root, then
            -- to any non-TOOL non-CHAIN span.
            if(argMaxIf(output, start_time, output != '' AND type = 'GENERATION') != '',
               argMaxIf(output, start_time, output != '' AND type = 'GENERATION'),
               if(anyIf(output, parent_span_id = '' AND output != '') != '',
                  anyIf(output, parent_span_id = '' AND output != ''),
                  argMaxIf(output, start_time, output != '' AND type NOT IN ('TOOL','CHAIN')))) AS t_output,
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
    rows = []
    for row in res.result_rows:
        d = dict(zip(res.column_names, row))
        d["metadata"] = parse_thread_meta(d.get("metadata"))
        rows.append(d)
    return rows


@router.get("/sessions/{thread_id}")
async def get_session(
    thread_id: str, project_id: str = Depends(get_project_id)
) -> dict:
    """The turns (traces) inside one thread, oldest-first — a simple conversation replay."""
    client = await get_async_client()
    res = await client.query(
        f"""
        SELECT trace_id, input, output, tokens, input_tokens, output_tokens, model, cost, latency_ms, ts, failing FROM (
          SELECT trace_id,
            max(conversation_id)                                          AS conv,
            -- Prefer the EARLIEST GENERATION input (the actual user message) over framework
            -- internals (CrewAI agent-config payload, LlamaIndex workflow state, etc.).
            if(argMinIf(input, start_time, input != '' AND type = 'GENERATION') != '',
               argMinIf(input, start_time, input != '' AND type = 'GENERATION'),
               argMinIf(input, start_time, input != ''))                    AS input,
            -- Prefer the latest GENERATION output (skip TOOL + CHAIN router signals like
            -- LangGraph's `__end__`); fall back to root output, then any non-TOOL/non-CHAIN.
            if(argMaxIf(output, start_time, output != '' AND type = 'GENERATION') != '',
               argMaxIf(output, start_time, output != '' AND type = 'GENERATION'),
               if(anyIf(output, parent_span_id = '' AND output != '') != '',
                  anyIf(output, parent_span_id = '' AND output != ''),
                  argMaxIf(output, start_time, output != '' AND type NOT IN ('TOOL','CHAIN')))) AS output,
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
