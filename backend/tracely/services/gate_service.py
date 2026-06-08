"""CI/CD gate: replay an agent's PROMOTED regression cases against candidate traces
emitted by a CI run (matched by `input_digest` within an env), aggregate -> PASS/FAIL.

A PR's CI step runs the agent and emits traces tagged `tracely.env=ci`; the gate finds the
candidate trace whose input matches each case and replays the case against it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely.config import settings
from tracely.domain.gate.warnings import delta_warnings
from tracely.domain.regression.contract import evaluate_assertions
from tracely.domain.regression.fixtures import FixtureBundle
from tracely.domain.trajectory import build_trajectory
from tracely.domain.traces.spans import input_digest
from tracely.infrastructure.blob import s3 as blobstore
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db.models import Agent, EvaluationCase, GateCase, GateRun

log = structlog.get_logger()


class GateService:
    """Replay an agent's PROMOTED cases against a CI run's candidate traces."""

    def __init__(
        self,
        session: Session,
        trace_reader: TraceReader | None = None,
    ) -> None:
        self.session = session
        self.trace_reader = trace_reader or TraceReader()

    # ── public ops ────────────────────────────────────────────────────────────

    def resolve_agent_id(self, project_id: str, agent_ref: str) -> str | None:
        """Accept a slug OR a UUID. Returns the canonical agent id, or None if it doesn't
        belong to this project."""
        a = self.session.execute(
            select(Agent).where(Agent.project_id == project_id, Agent.slug == agent_ref)
        ).scalar_one_or_none()
        if a:
            return a.id
        a = self.session.get(Agent, agent_ref)
        return a.id if a and a.project_id == project_id else None

    def replay_suite(self, project_id: str, agent_id: str) -> list[dict]:
        """The PROMOTED cases for an agent plus each one's recorded input and fixture bundle —
        the suite `tracely replay` re-runs the agent against (hermetically, when fixtures
        exist)."""
        cases = self._promoted_cases(project_id, agent_id)
        return [
            {
                "id": c.id,
                "title": c.title,
                "input": self._recover_input(project_id, c.source_trace_id),
                "input_digest": c.input_digest,
                "fixtures": self._load_fixtures(c),
            }
            for c in cases
        ]

    def run_gate(
        self,
        project_id: str,
        agent_id: str,
        env: str = "ci",
        git_ref: str = "",
        pr_number: int | None = None,
        candidates: dict[str, str] | None = None,
    ) -> GateRun:
        """Replay an agent's PROMOTED cases -> PASS/FAIL. Two pairing modes:
        - `candidates` given: explicit `{case_id: trace_id}` map (as `tracely replay` produces).
        - otherwise: match each case to the latest ci-tagged trace whose `input_digest` equals.
        """
        cases = self._promoted_cases(project_id, agent_id)
        case_to_trace = self._pair_candidates(project_id, agent_id, env, cases, candidates)

        total_lat, total_tok, per_trace = self.trace_reader.candidate_metrics(
            project_id, [tid for tid, _ in case_to_trace.values()]
        )

        gate = GateRun(
            id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id, env=env,
            git_ref=git_ref, pr_number=pr_number, status="RUNNING", total=len(cases),
        )
        self.session.add(gate)
        self.session.commit()

        passed, failed, skipped = self._record_gate_cases(gate, cases, case_to_trace, per_trace)

        baseline = self._baseline_gate(project_id, agent_id, gate.id)
        warnings = delta_warnings(total_lat, total_tok, baseline)

        gate.passed, gate.failed, gate.skipped = passed, failed, skipped
        gate.latency_ms, gate.total_tokens, gate.warnings = total_lat, total_tok, warnings
        gate.status = self._final_status(failed, warnings)
        gate.finished_at = datetime.now(timezone.utc)
        self.session.commit()
        return gate

    # ── internals ─────────────────────────────────────────────────────────────

    def _promoted_cases(self, project_id: str, agent_id: str) -> list[EvaluationCase]:
        return list(
            self.session.execute(
                select(EvaluationCase).where(
                    EvaluationCase.project_id == project_id,
                    EvaluationCase.agent_id == agent_id,
                    EvaluationCase.status == "PROMOTED",
                )
            ).scalars()
        )

    def _pair_candidates(
        self,
        project_id: str,
        agent_id: str,
        env: str,
        cases: list[EvaluationCase],
        candidates: dict[str, str] | None,
    ) -> dict[str, tuple[str, list]]:
        case_to_trace: dict[str, tuple[str, list]] = {}
        if candidates:
            for case in cases:
                tid = candidates.get(case.id)
                if tid:
                    spans = self.trace_reader.read_spans(project_id, tid)
                    if spans:
                        case_to_trace[case.id] = (tid, spans)
            return case_to_trace

        trace_ids = self.trace_reader.latest_traces_for_env(project_id, agent_id, env, limit=300)
        digest_to_trace: dict[str, tuple[str, list]] = {}
        for tid in trace_ids:
            spans = self.trace_reader.read_spans(project_id, tid)
            if not spans:
                continue
            # Newest-first; setdefault preserves the latest per digest.
            digest_to_trace.setdefault(input_digest(spans), (tid, spans))
        for case in cases:
            m = digest_to_trace.get(case.input_digest)
            if m:
                case_to_trace[case.id] = m
        return case_to_trace

    def _record_gate_cases(
        self,
        gate: GateRun,
        cases: list[EvaluationCase],
        case_to_trace: dict[str, tuple[str, list]],
        per_trace: dict[str, tuple[float, int]],
    ) -> tuple[int, int, int]:
        passed = failed = skipped = 0
        for case in cases:
            match = case_to_trace.get(case.id)
            if not match:
                verdict, detail, cand = "SKIP", {"reason": "not exercised in this run"}, ""
                skipped += 1
            else:
                cand, spans = match
                verdict, detail = evaluate_assertions(
                    case.assertions or {}, case.match_mode, build_trajectory(spans)
                )
                lat, tok = per_trace.get(cand, (0.0, 0))
                detail = {**detail, "latency_ms": lat, "tokens": tok}
                if verdict == "PASS":
                    passed += 1
                else:
                    failed += 1
            self.session.add(GateCase(
                id=str(uuid.uuid4()), gate_run_id=gate.id, evaluation_case_id=case.id,
                candidate_trace_id=cand, verdict=verdict, detail=detail,
            ))
        return passed, failed, skipped

    def _baseline_gate(
        self, project_id: str, agent_id: str, exclude_id: str
    ) -> GateRun | None:
        return self.session.execute(
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

    @staticmethod
    def _final_status(failed: int, warnings: list[str]) -> str:
        if failed > 0:
            return "FAIL"  # fail-to-pass is the hard gate
        if warnings and settings.gate_block_on_warnings:
            return "FAIL"  # opt-in: treat soft regressions as blocking
        return "PASS"

    def _recover_input(self, project_id: str, source_trace_id: str) -> str:
        """The user-facing input recorded on a case's source trace — what to feed the agent on
        replay."""
        if not source_trace_id:
            return ""
        for s in self.trace_reader.read_spans(project_id, source_trace_id):
            if s.get("input"):
                return str(s["input"])
        return ""

    def _load_fixtures(self, case: EvaluationCase) -> dict:
        """Recorded tool/LLM outputs captured for this case at promote time (hermetic replay)."""
        key = case.fixture_bundle_s3_key
        if not key:
            return {}
        try:
            raw = blobstore.get_blob(key)
            return FixtureBundle.decode(raw)
        except Exception as exc:  # missing/unreadable bundle -> replay falls back to live calls
            log.warning("fixture_load_failed", case_id=case.id, error=str(exc))
            return {}
