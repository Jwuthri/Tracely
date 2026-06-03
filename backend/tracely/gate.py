"""CI/CD gate: replay an agent's PROMOTED regression cases against candidate traces
emitted by a CI run (matched by input_digest within an env), aggregate -> PASS/FAIL.

A PR's CI step runs the agent and emits traces tagged tracely.env=ci; the gate finds
the candidate trace whose input matches each case and replays the case against it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely import clickhouse
from tracely.models import Agent, EvaluationCase, GateCase, GateRun
from tracely.regression import _input_digest, evaluate_case, read_trace_spans
from tracely.trajectory import build_trajectory


def resolve_agent_id(session: Session, project_id: str, agent_ref: str) -> str | None:
    a = session.execute(
        select(Agent).where(Agent.project_id == project_id, Agent.slug == agent_ref)
    ).scalar_one_or_none()
    if a:
        return a.id
    a = session.get(Agent, agent_ref)
    return a.id if a and a.project_id == project_id else None


def run_gate(
    session: Session,
    project_id: str,
    agent_id: str,
    env: str = "ci",
    git_ref: str = "",
    pr_number: int | None = None,
) -> GateRun:
    client = clickhouse.get_client()
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
        d = _input_digest(spans)
        digest_to_trace.setdefault(d, (tid, spans))

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

    gate = GateRun(
        id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id, env=env,
        git_ref=git_ref, pr_number=pr_number, status="RUNNING", total=len(cases),
    )
    session.add(gate)
    session.commit()

    passed = failed = skipped = 0
    for case in cases:
        match = digest_to_trace.get(case.input_digest)
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
