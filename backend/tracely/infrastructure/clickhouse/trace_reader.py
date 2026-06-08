"""Read access to the ClickHouse `events` and `scores` tables.

Consolidates the SELECTs that were scattered across `regression_service` (read_trace_spans),
`gate_service` (_candidate_metrics, latest ci traces), `failure_intel_service` (failing-trace
reasons), and `api/routers/clusters.py` (_member_meta). One place owns the column lists and
parameter shapes, so a schema change touches one file.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from clickhouse_connect.driver.client import Client

from tracely.infrastructure.clickhouse.client import get_client

# Columns used by services to reconstruct a trace's spans (regression promote/replay, gate
# replay, failure intel summarization, evaluation runner).
_SPAN_COLS = [
    "span_id", "parent_span_id", "type", "name", "level", "status_message",
    "start_time", "end_time", "agent_id", "agent_version_id", "agent_run_id",
    "turn_id", "step_id", "model_id", "input", "output", "tool_call_names",
    "trace_id", "is_app_root",
]


class TraceReader:
    """All `events` / `scores` SELECTs go through here.

    `client` is constructed lazily — the API path passes its async client elsewhere; this is the
    sync reader used by Celery workers and the regression/gate/fi orchestrators.
    """

    def __init__(self, client: Client | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = get_client()
        return self._client

    # ── span reads ────────────────────────────────────────────────────────────

    def read_spans(self, project_id: str, trace_id: str) -> list[dict]:
        """All spans for one trace, ordered by start_time, with the columns services need."""
        res = self.client.query(
            f"SELECT {', '.join(_SPAN_COLS)} FROM events FINAL "
            "WHERE project_id = {p:String} AND trace_id = {t:String} ORDER BY start_time",
            parameters={"p": project_id, "t": trace_id},
        )
        return [dict(zip(res.column_names, row)) for row in res.result_rows]

    def candidate_metrics(
        self, project_id: str, trace_ids: Iterable[str]
    ) -> tuple[float, int, dict[str, tuple[float, int]]]:
        """Per-trace latency (ms) + token totals across `trace_ids`. Returns
        (total_lat, total_tok, per_trace_map). Latency/cost are exact for live runs and ~0 for
        hermetic replay (expected)."""
        uniq = sorted({t for t in trace_ids if t})
        if not uniq:
            return 0.0, 0, {}
        rows = self.client.query(
            "SELECT trace_id, "
            "dateDiff('millisecond', min(start_time), max(coalesce(end_time, start_time))) AS lat, "
            "toUInt64(sum(arraySum(mapValues(usage_details)))) AS toks "
            "FROM events FINAL WHERE project_id = {p:String} AND trace_id IN {t:Array(String)} "
            "GROUP BY trace_id",
            parameters={"p": project_id, "t": uniq},
        ).result_rows
        per = {tid: (float(lat), int(toks)) for tid, lat, toks in rows}
        return sum(v[0] for v in per.values()), sum(v[1] for v in per.values()), per

    def latest_traces_for_env(
        self, project_id: str, agent_id: str, env: str, limit: int = 300
    ) -> list[str]:
        """Recent trace_ids for `(agent_id, env)`, newest first. The gate uses this to find
        candidate traces when no explicit `tracely replay` pairing was provided."""
        rows = self.client.query(
            "SELECT trace_id FROM events FINAL WHERE project_id = {p:String} AND agent_id = {a:String} "
            "AND env = {e:String} GROUP BY trace_id ORDER BY max(start_time) DESC LIMIT {n:UInt32}",
            parameters={"p": project_id, "a": agent_id, "e": env, "n": limit},
        ).result_rows
        return [tid for (tid,) in rows]

    # ── score reads ───────────────────────────────────────────────────────────

    def failing_trace_reasons(
        self, project_id: str, limit: int = 5000
    ) -> dict[str, list[tuple[str, str]]]:
        """`{trace_id: [(score_name, comment), ...]}` for every auto-eval FAIL. Used by failure
        intelligence to know WHY each trace was flagged."""
        rows = self.client.query(
            "SELECT trace_id, name, comment FROM scores FINAL WHERE project_id = {p:String} "
            "AND source = 'EVAL' AND verdict = 'FAIL' AND evaluation_case_id = '' "
            "LIMIT {n:UInt32}",
            parameters={"p": project_id, "n": limit},
        ).result_rows
        by_tid: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for tid, name, comment in rows:
            by_tid[tid].append((name, comment))
        return by_tid

    # ── ui helpers ────────────────────────────────────────────────────────────

    def member_meta(
        self, project_id: str, trace_ids: Iterable[str]
    ) -> dict[str, dict[str, Any]]:
        """Per-member facts used by the cluster detail view: timestamp, latency, input snippet.
        Returns `{trace_id: {ts, latency_ms, input}}`. Drops trace_ids no longer present in
        events (wiped, or aged out by ClickHouse TTL)."""
        uniq = sorted({t for t in trace_ids if t})
        if not uniq:
            return {}
        rows = self.client.query(
            "SELECT trace_id, min(start_time) AS ts, "
            "dateDiff('millisecond', min(start_time), max(coalesce(end_time, start_time))) AS lat, "
            "argMinIf(input, start_time, input != '') AS inp "
            "FROM events FINAL WHERE project_id = {p:String} AND trace_id IN {t:Array(String)} "
            "GROUP BY trace_id",
            parameters={"p": project_id, "t": uniq},
        ).result_rows
        # input is left raw here; routers/services that want a readable snippet should pass it
        # through `tracely.infrastructure.text.message_text`.
        return {r[0]: {"ts": r[1], "latency_ms": float(r[2]), "input": r[3]} for r in rows}
