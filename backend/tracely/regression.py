"""Promote a (failing) trace into a regression EvaluationCase, and replay cases.

A regression case derived from a failing trace asserts: replaying the same input must NOT
reproduce the failure (no ERROR span) AND must still call the required tools. That gives the
FAIL-TO-PASS contract for free — it FAILS on the broken run and PASSES once fixed.

Live re-execution (actually invoking the agent) is deferred to the CI slice; MVP `replay`
evaluates a *candidate trace* against the case (record-replay / live runner comes with tracely.yaml).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely import blobstore, clickhouse
from tracely.config import settings
from tracely.models import CaseReplay, EvaluationCase, EvaluationSuite, EvaluationSuiteCase
from tracely.trajectory import (
    Trajectory,
    build_trajectory,
    erroring_steps,
    tool_sequence,
    tools_satisfied,
)

_SPAN_COLS = [
    "span_id", "parent_span_id", "type", "name", "level", "status_message",
    "start_time", "end_time", "agent_id", "agent_version_id", "agent_run_id",
    "turn_id", "step_id", "model_id", "input", "output", "tool_call_names",
    "trace_id", "is_app_root",
]


class NotFound(Exception):
    pass


def read_trace_spans(client, project_id: str, trace_id: str) -> list[dict]:
    res = client.query(
        f"SELECT {', '.join(_SPAN_COLS)} FROM events FINAL "
        "WHERE project_id = {p:String} AND trace_id = {t:String} ORDER BY start_time",
        parameters={"p": project_id, "t": trace_id},
    )
    return [dict(zip(res.column_names, row)) for row in res.result_rows]


def _root(spans: list[dict]) -> dict:
    return next((s for s in spans if s.get("parent_span_id", "") == "" or s.get("is_app_root")), spans[0])


def _input_digest(spans: list[dict]) -> str:
    r = _root(spans)
    payload = {"agent_id": r.get("agent_id", ""), "name": r.get("name", ""), "input": r.get("input") or ""}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def evaluate_case(case: EvaluationCase, traj: Trajectory) -> tuple[str, dict]:
    """Run the case's assertions against a produced trajectory -> (PASS|FAIL, detail)."""
    assertions = case.assertions or {}
    ref_tools: list[str] = assertions.get("required_tools", [])
    mode: str = assertions.get("match_mode", case.match_mode or "superset")
    produced = tool_sequence(traj)
    tools_ok, missing, extra = tools_satisfied(mode, produced, ref_tools)
    no_error_required = assertions.get("no_error", True)
    errs = erroring_steps(traj)
    error_ok = (len(errs) == 0) if no_error_required else True
    passed = tools_ok and error_ok
    detail = {
        "passed": passed,
        "tools_ok": tools_ok,
        "error_ok": error_ok,
        "match_mode": mode,
        "required_tools": ref_tools,
        "produced_tools": produced,
        "missing_tools": missing,
        "extra_tools": extra,
        "erroring_steps": errs,
    }
    return ("PASS" if passed else "FAIL"), detail


def _get_or_create_suite(session: Session, project_id: str, agent_id: str) -> EvaluationSuite:
    suite = session.execute(
        select(EvaluationSuite).where(
            EvaluationSuite.project_id == project_id,
            EvaluationSuite.agent_id == agent_id,
            EvaluationSuite.slug == "regressions",
        )
    ).scalar_one_or_none()
    if suite:
        return suite
    suite = EvaluationSuite(
        id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id,
        slug="regressions", name="Regressions", kind="REGRESSION",
    )
    session.add(suite)
    session.commit()
    return suite


def promote_trace(session: Session, project_id: str, trace_id: str) -> EvaluationCase:
    client = clickhouse.get_client()
    spans = read_trace_spans(client, project_id, trace_id)
    if not spans:
        raise NotFound("trace not found")
    traj = build_trajectory(spans)
    root = _root(spans)
    agent_id = root.get("agent_id") or next((s.get("agent_id") for s in spans if s.get("agent_id")), "")
    digest = _input_digest(spans)

    existing = session.execute(
        select(EvaluationCase).where(
            EvaluationCase.project_id == project_id,
            EvaluationCase.agent_id == agent_id,
            EvaluationCase.input_digest == digest,
        )
    ).scalar_one_or_none()
    if existing:
        return existing  # idempotent

    ref_tools = tool_sequence(traj)
    assertions = {"no_error": True, "required_tools": ref_tools, "match_mode": "superset"}

    # capture fixtures (recorded tool/LLM outputs) for future hermetic replay
    fixtures = {
        "tools": {s["name"]: s.get("output") for s in spans if s.get("type") == "TOOL"},
        "llm": {s["name"]: s.get("output") for s in spans if s.get("type") == "GENERATION"},
    }
    fixture_key = f"{settings.s3_event_prefix}fixtures/{project_id}/{digest}.json"
    blobstore.put_blob(fixture_key, json.dumps(fixtures, default=str).encode(), "application/json")

    case = EvaluationCase(
        id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id, level="AGENT_RUN",
        title=root.get("name", "") or "case", input_digest=digest, status="DRAFT", origin="MANUAL",
        source_trace_id=trace_id, source_span_id=root.get("span_id", ""),
        agent_version_first_failed=root.get("agent_version_id") or None,
        fixture_bundle_s3_key=fixture_key, reference_trajectory=traj.to_json(),
        assertions=assertions, match_mode="superset", tool_args_mode="exact",
        fail_to_pass_validated=False, version=1, created_by="ui",
    )
    session.add(case)
    session.commit()

    suite = _get_or_create_suite(session, project_id, agent_id)
    session.add(EvaluationSuiteCase(suite_id=suite.id, case_id=case.id))
    session.commit()

    # FAIL-TO-PASS validation: the source (failing) trace must currently FAIL the case.
    verdict, detail = evaluate_case(case, traj)
    case.fail_to_pass_validated = verdict == "FAIL"
    case.status = "PROMOTED" if case.fail_to_pass_validated else "DRAFT"
    session.add(CaseReplay(
        id=str(uuid.uuid4()), case_id=case.id, candidate_trace_id=trace_id,
        verdict=verdict, detail={**detail, "validation": True},
    ))
    session.commit()
    _write_score(client, case, trace_id, verdict)
    return case


def replay_case(session: Session, project_id: str, case_id: str, candidate_trace_id: str) -> CaseReplay:
    case = session.get(EvaluationCase, case_id)
    if not case or case.project_id != project_id:
        raise NotFound("case not found")
    client = clickhouse.get_client()
    spans = read_trace_spans(client, project_id, candidate_trace_id)
    if not spans:
        raise NotFound("candidate trace not found")
    traj = build_trajectory(spans)
    verdict, detail = evaluate_case(case, traj)
    replay = CaseReplay(
        id=str(uuid.uuid4()), case_id=case.id, candidate_trace_id=candidate_trace_id,
        verdict=verdict, detail=detail,
    )
    session.add(replay)
    session.commit()
    _write_score(client, case, candidate_trace_id, verdict)
    return replay


_SCORE_COLS = [
    "project_id", "id", "trace_id", "name", "source", "data_type", "value",
    "verdict", "evaluation_case_id", "evaluation_level", "comment", "created_at", "event_ts",
]


def _write_score(client, case: EvaluationCase, trace_id: str, verdict: str) -> None:
    now = datetime.now(timezone.utc)
    row = [
        case.project_id, str(uuid.uuid4()), trace_id, "tracely.regression.verdict", "EVAL",
        "BOOLEAN", 1.0 if verdict == "PASS" else 0.0, verdict, case.id, case.level, "", now, now,
    ]
    clickhouse.insert_rows(client, "scores", _SCORE_COLS, [row])
