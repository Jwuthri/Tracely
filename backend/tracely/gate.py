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
from tracely.config import settings
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


def _candidate_metrics(client, project_id: str, trace_ids: list[str]) -> tuple[float, int, dict]:
    """Per-candidate latency (ms) and token usage, plus run totals — the raw inputs to the soft
    delta gates. Latency/cost are exact for live runs and ~0 for hermetic replay (expected)."""
    uniq = sorted({t for t in trace_ids if t})
    if not uniq:
        return 0.0, 0, {}
    rows = client.query(
        "SELECT trace_id, "
        "dateDiff('millisecond', min(start_time), max(coalesce(end_time, start_time))) AS lat, "
        "toUInt64(sum(arraySum(mapValues(usage_details)))) AS toks "
        "FROM events FINAL WHERE project_id = {p:String} AND trace_id IN {t:Array(String)} "
        "GROUP BY trace_id",
        parameters={"p": project_id, "t": uniq},
    ).result_rows
    per = {tid: (float(lat), int(toks)) for tid, lat, toks in rows}
    return sum(v[0] for v in per.values()), sum(v[1] for v in per.values()), per


def _baseline_gate(session: Session, project_id: str, agent_id: str, exclude_id: str) -> GateRun | None:
    """The agent's most recent GREEN gate run — the baseline the deltas compare against."""
    return session.execute(
        select(GateRun)
        .where(
            GateRun.project_id == project_id,
            GateRun.agent_id == agent_id,
            GateRun.status == "PASS",
            GateRun.id != exclude_id,
        )
        .order_by(GateRun.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _delta_warnings(latency_ms: float, total_tokens: int, baseline: GateRun | None) -> list[str]:
    """Soft (non-blocking) warnings when this run is materially worse than the baseline green gate."""
    if baseline is None:
        return []
    warns: list[str] = []
    if (baseline.latency_ms or 0) >= 50:  # floor: don't flag noise on tiny hermetic latencies
        d = (latency_ms - baseline.latency_ms) / baseline.latency_ms * 100
        if d >= settings.gate_latency_warn_pct:
            warns.append(f"latency +{d:.0f}% vs baseline ({baseline.latency_ms:.0f}→{latency_ms:.0f} ms)")
    if (baseline.total_tokens or 0) > 0:
        d = (total_tokens - baseline.total_tokens) / baseline.total_tokens * 100
        if d >= settings.gate_tokens_warn_pct:
            warns.append(f"tokens +{d:.0f}% vs baseline ({baseline.total_tokens}→{total_tokens})")
    return warns


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

    # soft metrics over the matched candidate traces (latency/tokens), and per-trace lookup
    total_lat, total_tok, per_trace = _candidate_metrics(
        client, project_id, [tid for tid, _ in case_to_trace.values()]
    )

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
            lat, tok = per_trace.get(cand, (0.0, 0))
            detail = {**detail, "latency_ms": lat, "tokens": tok}
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

    # soft delta gates vs the last green gate: surface as WARNINGS (non-blocking by default)
    baseline = _baseline_gate(session, project_id, agent_id, gate.id)
    warnings = _delta_warnings(total_lat, total_tok, baseline)

    gate.passed, gate.failed, gate.skipped = passed, failed, skipped
    gate.latency_ms, gate.total_tokens, gate.warnings = total_lat, total_tok, warnings
    if failed > 0:
        gate.status = "FAIL"  # fail-to-pass is the hard gate
    elif warnings and settings.gate_block_on_warnings:
        gate.status = "FAIL"  # opt-in: treat soft regressions as blocking
    else:
        gate.status = "PASS"
    gate.finished_at = datetime.now(timezone.utc)
    session.commit()
    return gate
