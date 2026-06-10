"""Write access to the ClickHouse `scores` table.

Two flavors of scores go in here:
- Online eval scores (one per evaluator per target; ids derived from a stable UUID5 namespace so
  re-evaluating a target replaces rather than duplicates via ReplacingMergeTree). A target is a
  trace (AGENT_RUN), one of its spans (SPAN/TOOL/…, via `observation_id`), or — for
  CONVERSATION-level evaluators — the whole thread (addressed by `session_id`, no trace_id).
- Regression/gate verdict scores (one per case×trace; carries `evaluation_case_id`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from clickhouse_connect.driver.client import Client

from tracely.infrastructure.clickhouse.client import get_client, insert_rows

# UUID5 namespace for online eval scores — stable across re-evaluations so spans arriving in
# multiple batches converge to the same id under ReplacingMergeTree.
_ONLINE_EVAL_NS = uuid.UUID("c0ffee00-0000-0000-0000-000000000001")

_CONVERSATION = "CONVERSATION"

_ONLINE_EVAL_COLS = [
    "project_id", "id", "trace_id", "observation_id", "session_id", "agent_run_id", "name",
    "source", "data_type", "value", "string_value", "verdict", "evaluation_level", "comment",
    "created_at", "event_ts",
]

_REGRESSION_VERDICT_COLS = [
    "project_id", "id", "trace_id", "name", "source", "data_type", "value",
    "verdict", "evaluation_case_id", "evaluation_level", "comment", "created_at", "event_ts",
]


class _EvalResultLike(Protocol):
    """Structural type so we don't have to import EvalResult from domain.evaluation here."""

    name: str
    level: str
    verdict: str
    data_type: str
    value: float | None
    string_value: str
    target_span_id: str
    comment: str


class ScoreWriter:
    def __init__(self, client: Client | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Client:
        if self._client is None:
            self._client = get_client()
        return self._client

    def write_eval_scores(
        self,
        project_id: str,
        trace_id: str,
        agent_run_id: str,
        results: list[_EvalResultLike],
        thread_id: str = "",
    ) -> None:
        if not results:
            return
        now = datetime.now(timezone.utc)
        rows = []
        for r in results:
            if r.level == _CONVERSATION:
                # Thread-scoped: keyed by the thread so any turn's re-evaluation converges to
                # one row. No trace_id — readers find these via session_id.
                sid = str(uuid.uuid5(_ONLINE_EVAL_NS, f"thread:{thread_id}:{r.name}"))
                row_trace, row_session = None, thread_id
            else:
                sid = str(uuid.uuid5(_ONLINE_EVAL_NS, f"{trace_id}:{r.name}:{r.target_span_id}"))
                row_trace, row_session = trace_id, thread_id or None
            rows.append([
                project_id, sid, row_trace, r.target_span_id or None, row_session, agent_run_id,
                r.name, "EVAL", r.data_type, r.value, r.string_value or "", r.verdict, r.level,
                r.comment, now, now,
            ])
        insert_rows(self.client, "scores", _ONLINE_EVAL_COLS, rows)

    def write_regression_verdict(self, case, trace_id: str, verdict: str) -> None:
        now = datetime.now(timezone.utc)
        row = [
            case.project_id, str(uuid.uuid4()), trace_id, "tracely.regression.verdict", "EVAL",
            "BOOLEAN", 1.0 if verdict == "PASS" else 0.0, verdict, case.id, case.level, "", now, now,
        ]
        insert_rows(self.client, "scores", _REGRESSION_VERDICT_COLS, [row])
