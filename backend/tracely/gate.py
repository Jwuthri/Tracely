"""CI/CD gate: replay an agent's PROMOTED regression cases against candidate traces
emitted by a CI run (matched by input_digest within an env), aggregate -> PASS/FAIL.

A PR's CI step runs the agent and emits traces tagged tracely.env=ci; the gate finds
the candidate trace whose input matches each case and replays the case against it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely import blobstore, clickhouse
from tracely.models import Agent, EvaluationCase, GateCase, GateRun
from tracely.regression import _input_digest, evaluate_case, read_trace_spans
from tracely.trajectory import build_trajectory

log = structlog.get_logger()


def resolve_agent_id(session: Session, project_id: str, agent_ref: str) -> str | None:
    a = session.execute(
        select(Agent).where(Agent.project_id == project_id, Agent.slug == agent_ref)
    ).scalar_one_or_none()
    if a:
        return a.id
    a = session.get(Agent, agent_ref)
    return a.id if a and a.project_id == project_id else None


def _recover_input(client, project_id: str, source_trace_id: str) -> str:
    """The user-facing input recorded on a case's source trace — what to feed the agent on replay."""
    if not source_trace_id:
        return ""
    for s in read_trace_spans(client, project_id, source_trace_id):
        if s.get("input"):
            return str(s["input"])
    return ""


def _load_fixtures(case: EvaluationCase) -> dict:
    """The recorded tool/LLM outputs captured for this case at promote time (for hermetic replay)."""
    key = case.fixture_bundle_s3_key
    if not key:
        return {}
    try:
        raw = blobstore.get_blob(key)
        return json.loads(raw) if raw else {}
    except Exception as exc:  # missing/unreadable bundle -> replay falls back to live calls
        log.warning("fixture_load_failed", case_id=case.id, error=str(exc))
        return {}


def replay_suite(session: Session, project_id: str, agent_id: str) -> list[dict]:
    """The PROMOTED cases for an agent plus each one's recorded input and fixture bundle — the
    suite `tracely replay` re-runs the agent against (hermetically, when fixtures exist)."""
    client = clickhouse.get_client()
    cases = (
        session.execute(
            select(EvaluationCase).where(
                EvaluationCase.project_id == project_id,
                EvaluationCase.agent_id == agent_id,
                EvaluationCase.status == "PROMOTED",
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": c.id,
            "title": c.title,
            "input": _recover_input(client, project_id, c.source_trace_id),
            "input_digest": c.input_digest,
            "fixtures": _load_fixtures(c),
        }
        for c in cases
    ]


def run_gate(
    session: Session,
    project_id: str,
    agent_id: str,
    env: str = "ci",
    git_ref: str = "",
    pr_number: int | None = None,
    candidates: dict[str, str] | None = None,
) -> GateRun:
    """Replay an agent's PROMOTED cases against this run's candidate traces -> PASS/FAIL.

    Two ways to pair a candidate trace to a case:
    - `candidates` given (a {case_id: trace_id} map, as `tracely replay` produces): use the
      explicit pairing — we know exactly which trace replayed which case.
    - otherwise: match each case to the latest ci-tagged trace whose input digest equals the
      case's (for agents that emit their own ci traces and let the gate find them).
    """
    client = clickhouse.get_client()
    cases = (
        session.execute(
            select(EvaluationCase).where(
                EvaluationCase.project_id == project_id,
                EvaluationCase.agent_id == agent_id,
                EvaluationCase.status == "PROMOTED",
            )
        )
        .scalars()
        .all()
    )

    case_to_trace: dict[str, tuple[str, list]] = {}
    if candidates:
        for case in cases:
            tid = candidates.get(case.id)
            if tid:
                spans = read_trace_spans(client, project_id, tid)
                if spans:
                    case_to_trace[case.id] = (tid, spans)
    else:
        rows = client.query(
            "SELECT trace_id FROM events FINAL WHERE project_id = {p:String} AND agent_id = {a:String} "
            "AND env = {e:String} GROUP BY trace_id ORDER BY max(start_time) DESC LIMIT 300",
            parameters={"p": project_id, "a": agent_id, "e": env},
        ).result_rows
        # candidate trace per input signature (latest wins; rows are newest-first)
        digest_to_trace: dict[str, tuple[str, list]] = {}
        for (tid,) in rows:
            spans = read_trace_spans(client, project_id, tid)
            if not spans:
                continue
            digest_to_trace.setdefault(_input_digest(spans), (tid, spans))
        for case in cases:
            m = digest_to_trace.get(case.input_digest)
            if m:
                case_to_trace[case.id] = m

    gate = GateRun(
        id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id, env=env,
        git_ref=git_ref, pr_number=pr_number, status="RUNNING", total=len(cases),
    )
    session.add(gate)
    session.commit()

    passed = failed = skipped = 0
    for case in cases:
        match = case_to_trace.get(case.id)
        if not match:
            verdict, detail, cand = "SKIP", {"reason": "not exercised in this run"}, ""
            skipped += 1
        else:
            cand, spans = match
            verdict, detail = evaluate_case(case, build_trajectory(spans))
            if verdict == "PASS":
                passed += 1
            else:
                failed += 1
        session.add(
            GateCase(
                id=str(uuid.uuid4()), gate_run_id=gate.id, evaluation_case_id=case.id,
                candidate_trace_id=cand, verdict=verdict, detail=detail,
            )
        )

    gate.passed, gate.failed, gate.skipped = passed, failed, skipped
    gate.status = "FAIL" if failed > 0 else "PASS"  # fail-to-pass is the hard gate
    gate.finished_at = datetime.now(timezone.utc)
    session.commit()
    return gate
