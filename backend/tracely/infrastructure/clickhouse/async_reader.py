"""Async read access to ClickHouse for the API layer.

EVERY ClickHouse query the routers need lives here — routers parse the request, await these,
and shape the HTTP response; they never embed SQL. This is the async twin of
`trace_reader.TraceReader` (the sync reader used by Celery workers and the
regression/gate/failure-intel services). One place owns the column lists and parameter
shapes, so a schema change touches one file.
"""

from __future__ import annotations

from collections import defaultdict

from tracely.domain.traces.metadata import parse_thread_meta
from tracely.infrastructure.clickhouse.client import get_async_client
from tracely.infrastructure.clickhouse.trace_reader import _SPAN_COLS

# Online-eval score filter: auto/on-demand evaluator results only (regression/gate verdict
# rows carry an evaluation_case_id and are excluded everywhere in the UI reads).
_ONLINE = "source = 'EVAL' AND evaluation_case_id = ''"

# Thread/turn status reflects STRUCTURAL failures (errors, missing tools, silent failures);
# the subjective LLM-judge quality score is excluded here and shown per-trace instead.
_FAILING = (
    "SELECT trace_id FROM scores FINAL WHERE project_id = {p:String} "
    f"AND {_ONLINE} AND verdict = 'FAIL' "
    "AND name != 'tracely.run.quality'"
)

_SCORE_COLS = "name, evaluation_level, observation_id, value, string_value, verdict, comment, data_type"


# ── traces ────────────────────────────────────────────────────────────────────


async def traces_overview(project_id: str, limit: int) -> list[dict]:
    """Newest traces with span counts + the per-trace online-eval verdict."""
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
    ev = await client.query(
        "SELECT trace_id, maxIf(1, verdict = 'FAIL') AS fail FROM scores FINAL "
        f"WHERE project_id = {{p:String}} AND {_ONLINE} GROUP BY trace_id",
        parameters={"p": project_id},
    )
    verdict = {r[0]: ("FAIL" if r[1] else "PASS") for r in ev.result_rows}
    for r in rows:
        r["eval"] = verdict.get(r["trace_id"])
    return rows


async def trace_spans(project_id: str, trace_id: str) -> list[dict]:
    """One trace's spans (ordered), as raw dicts with derived tokens/cost per span."""
    client = await get_async_client()
    res = await client.query(
        """
        SELECT span_id, parent_span_id, name, type, level, status_message,
               start_time, end_time, agent_id, agent_run_id, turn_id, step_name,
               model_id, input, output, metadata, conversation_id,
               toUInt64(arraySum(mapValues(usage_details)))               AS tokens,
               toFloat64(arraySum(mapValues(cost_details)))               AS cost
        FROM events FINAL
        WHERE project_id = {p:String} AND trace_id = {t:String}
        ORDER BY start_time
        """,
        parameters={"p": project_id, "t": trace_id},
    )
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


async def thread_spans_full(project_id: str, thread_id: str) -> list[dict]:
    """All spans across a thread with the SAME columns as the sync eval reader (`_SPAN_COLS`) — so
    the advanced-template PREVIEW resolves against data identical to what the run path grades. The
    `trace_spans` / sessions UI readers select a lighter, divergent set (no `tool_calls`, no
    `is_app_root`); do NOT reuse those here or the preview would lie about production."""
    client = await get_async_client()
    res = await client.query(
        f"SELECT {', '.join(_SPAN_COLS)} FROM events FINAL "
        "WHERE project_id = {p:String} "
        "AND (conversation_id = {th:String} OR trace_id = {th:String}) "
        "ORDER BY start_time",
        parameters={"p": project_id, "th": thread_id},
    )
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


async def trace_scores(project_id: str, trace_id: str, thread_id: str) -> list[dict]:
    """Online scores for one trace PLUS its thread's CONVERSATION-level scores (so the
    conversation metric columns render on the trace page)."""
    client = await get_async_client()
    res = await client.query(
        f"SELECT {_SCORE_COLS} "
        f"FROM scores FINAL WHERE project_id = {{p:String}} AND {_ONLINE} "
        "AND (trace_id = {t:String} OR (evaluation_level = 'CONVERSATION' AND session_id = {th:String})) "
        "ORDER BY evaluation_level, name",
        parameters={"p": project_id, "t": trace_id, "th": thread_id},
    )
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


async def evaluator_cost(project_id: str, days: int = 30) -> dict[str, dict]:
    """Per-evaluator LLM-judge token usage over the last `days` (from `scores.metadata`), keyed by
    `score_name` — the cost of each judge column. Structural checks make no LLM call so they don't
    appear. `{score_name: {runs, input_tokens, output_tokens, total_tokens, model}}`."""
    client = await get_async_client()
    res = await client.query(
        "SELECT name, "
        "countIf(mapContains(metadata, 'eval.total_tokens')) AS runs, "
        "sum(toUInt64OrZero(metadata['eval.input_tokens'])) AS input_tokens, "
        "sum(toUInt64OrZero(metadata['eval.output_tokens'])) AS output_tokens, "
        "sum(toUInt64OrZero(metadata['eval.total_tokens'])) AS total_tokens, "
        "anyLast(metadata['eval.model']) AS model "
        f"FROM scores FINAL WHERE project_id = {{p:String}} AND {_ONLINE} "
        "AND created_at >= now() - toIntervalDay({d:UInt32}) "
        "GROUP BY name HAVING runs > 0",
        parameters={"p": project_id, "d": days},
    )
    return {
        r[0]: {
            "runs": int(r[1]), "input_tokens": int(r[2]), "output_tokens": int(r[3]),
            "total_tokens": int(r[4]), "model": r[5] or "",
        }
        for r in res.result_rows
    }


# ── sessions / threads ────────────────────────────────────────────────────────


async def sessions_overview(
    project_id: str,
    limit: int,
    offset: int,
    from_ts: str | None = None,
    to_ts: str | None = None,
) -> list[dict]:
    """Traces grouped into threads by conversation (a trace with no conversation is its own
    1-turn thread), newest-last-activity first, with per-thread rollups + parsed metadata.
    The optional time window bounds each trace's start_time INSIDE the per-trace subquery so
    ClickHouse can prune by the `toYYYYMM(start_time)` partition."""
    client = await get_async_client()
    time_clause = ""
    params: dict = {"p": project_id, "n": limit, "o": max(offset, 0)}
    if from_ts:
        time_clause += " AND start_time >= parseDateTimeBestEffort({from:String})"
        params["from"] = from_ts
    if to_ts:
        time_clause += " AND start_time < parseDateTimeBestEffort({to:String})"
        params["to"] = to_ts
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
          FROM events FINAL WHERE project_id = {{p:String}}{time_clause}
          GROUP BY trace_id
        )
        GROUP BY thread
        ORDER BY last_ts DESC
        LIMIT {{n:UInt32}} OFFSET {{o:UInt32}}
        """,
        parameters=params,
    )
    rows = []
    for row in res.result_rows:
        d = dict(zip(res.column_names, row))
        d["metadata"] = parse_thread_meta(d.get("metadata"))
        rows.append(d)
    return rows


async def session_turns(project_id: str, thread_id: str) -> list[dict]:
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
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


# ── scores ────────────────────────────────────────────────────────────────────


async def scores_by_trace(project_id: str, trace_ids: list[str]) -> dict[str, list[dict]]:
    """`{trace_id: [score, …]}` for the given traces (all levels, online evals only)."""
    if not trace_ids:
        return {}
    client = await get_async_client()
    res = await client.query(
        f"SELECT trace_id, {_SCORE_COLS} "
        f"FROM scores FINAL WHERE project_id = {{p:String}} AND trace_id IN {{t:Array(String)}} "
        f"AND {_ONLINE} ORDER BY evaluation_level, name",
        parameters={"p": project_id, "t": trace_ids},
    )
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for row in res.result_rows:
        d = dict(zip(res.column_names, row))
        by_trace[d.pop("trace_id")].append(d)
    return by_trace


async def conversation_scores_by_thread(
    project_id: str, thread_ids: list[str]
) -> dict[str, list[dict]]:
    """`{thread: [score, …]}` of CONVERSATION-level scores (the C-row metric columns)."""
    if not thread_ids:
        return {}
    client = await get_async_client()
    res = await client.query(
        f"SELECT session_id, {_SCORE_COLS} "
        f"FROM scores FINAL WHERE project_id = {{p:String}} AND {_ONLINE} "
        "AND evaluation_level = 'CONVERSATION' AND session_id IN {t:Array(String)} ORDER BY name",
        parameters={"p": project_id, "t": thread_ids},
    )
    by_thread: dict[str, list[dict]] = defaultdict(list)
    for row in res.result_rows:
        d = dict(zip(res.column_names, row))
        by_thread[d.pop("session_id")].append(d)
    return by_thread


async def conversation_scores(project_id: str, thread_id: str) -> list[dict]:
    """One thread's CONVERSATION-level scores."""
    return (await conversation_scores_by_thread(project_id, [thread_id])).get(thread_id, [])


# ── search / stats / trends ───────────────────────────────────────────────────


async def search_threads(project_id: str, q: str, limit: int = 8) -> list[dict]:
    """Threads whose first user message matches `q` (case-insensitive), newest first. Reports
    the whole THREAD: first message, total turn count, latest trace."""
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
        ORDER BY last_ts DESC LIMIT {n:UInt32}
        """,
        parameters={"p": project_id, "q": q, "n": limit},
    )
    return [
        {"thread": thread, "first_input": first_input, "last_trace": last_trace, "turns": int(turns)}
        for thread, first_input, last_trace, turns, _ in res.result_rows
    ]


async def stats_counts(project_id: str) -> dict:
    """Headline counters for the dashboard: traces/spans, error traces, auto-eval failures."""
    client = await get_async_client()
    r = (
        await client.query(
            "SELECT uniqExact(trace_id), count() FROM events FINAL WHERE project_id = {p:String}",
            parameters={"p": project_id},
        )
    ).result_rows
    traces, spans = (int(r[0][0]), int(r[0][1])) if r else (0, 0)
    f = (
        await client.query(
            "SELECT uniqExact(trace_id) FROM events FINAL WHERE project_id = {p:String} AND level = 'ERROR'",
            parameters={"p": project_id},
        )
    ).result_rows
    failing = int(f[0][0]) if f else 0
    af = (
        await client.query(
            "SELECT uniqExact(trace_id) FROM scores FINAL WHERE project_id = {p:String} "
            f"AND {_ONLINE} AND verdict = 'FAIL'",
            parameters={"p": project_id},
        )
    ).result_rows
    auto_failures = int(af[0][0]) if af else 0
    return {"traces": traces, "spans": spans, "failing_traces": failing, "auto_failures": auto_failures}


async def daily_trace_failures(project_id: str, days: int) -> list[dict]:
    """Per-day trace + failing-trace counts, both dated by the trace's own start_time (so
    failures<=traces); a trace 'failed' if it has any online EVAL FAIL score."""
    client = await get_async_client()
    rows = (
        await client.query(
            "SELECT toDate(start_time) AS d, uniqExact(trace_id) AS traces, "
            "uniqExactIf(trace_id, trace_id IN ("
            "  SELECT trace_id FROM scores FINAL WHERE project_id = {p:String} "
            f"  AND {_ONLINE} AND verdict = 'FAIL')) AS failures "
            "FROM events FINAL "
            "WHERE project_id = {p:String} AND start_time >= subtractDays(now(), {d:UInt32}) "
            "GROUP BY d ORDER BY d",
            parameters={"p": project_id, "d": days},
        )
    ).result_rows
    return [{"date": str(d), "traces": int(t), "failures": int(f)} for d, t, f in rows]


async def trace_failure_totals(project_id: str) -> tuple[int, int]:
    """(total traces, total traces with an online EVAL FAIL)."""
    client = await get_async_client()

    async def _scalar(sql: str) -> int:
        r = (await client.query(sql, parameters={"p": project_id})).result_rows
        return int(r[0][0]) if r and r[0][0] is not None else 0

    total = await _scalar(
        "SELECT uniqExact(trace_id) FROM events FINAL WHERE project_id = {p:String}"
    )
    failures = await _scalar(
        "SELECT uniqExact(trace_id) FROM scores FINAL WHERE project_id = {p:String} "
        f"AND {_ONLINE} AND verdict = 'FAIL'"
    )
    return total, failures
