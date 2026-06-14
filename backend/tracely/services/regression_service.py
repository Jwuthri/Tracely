"""Promote a (failing) trace into a regression `EvaluationCase`, and replay cases.

A regression case derived from a failing trace asserts: replaying the same input must NOT
reproduce the failure AND must still call the required tools. That gives the FAIL-TO-PASS
contract for free — it FAILS on the broken run and PASSES once fixed.

The service composes:
- `TraceReader` (ClickHouse `events` reads)
- `ScoreWriter` (the regression verdict score row)
- `BlobStore` module functions (fixture bundle upload)
- pure `evaluate_assertions` from `domain.regression.contract`
- `FixtureBundle.capture` from `domain.regression.fixtures`
- `root_span` / `input_digest` from `domain.traces.spans`
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from tracely.config import settings
from tracely.domain.regression.contract import evaluate_assertions
from tracely.domain.regression.fixtures import FixtureBundle
from tracely.domain.trajectory import (
    Trajectory,
    build_trajectory,
    required_tools,
    split_errors,
)
from tracely.domain.traces.spans import input_digest, root_span
from tracely.infrastructure.blob import s3 as blobstore
from tracely.infrastructure.clickhouse.score_writer import ScoreWriter
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db.models import (
    CaseReplay,
    EvaluationCase,
    EvaluationSuite,
    EvaluationSuiteCase,
)
from tracely.services.evaluation_service import EvaluationService


class NotFound(Exception):
    pass


class RegressionService:
    """Use-case orchestrator: promote/replay regression cases."""

    def __init__(
        self,
        session: Session,
        trace_reader: TraceReader | None = None,
        score_writer: ScoreWriter | None = None,
        eval_service: EvaluationService | None = None,
    ) -> None:
        self.session = session
        self.trace_reader = trace_reader or TraceReader()
        self.score_writer = score_writer or ScoreWriter(self.trace_reader.client)
        # Grades answer quality on the source trace so a hallucination (clean trace, bad answer)
        # becomes a promotable, gate-able case — not just structural tool/error failures.
        self.eval_service = eval_service or EvaluationService(
            trace_reader=self.trace_reader, score_writer=self.score_writer
        )

    # ── reads (used by callers that just need the trace) ──────────────────────

    def read_spans(self, project_id: str, trace_id: str) -> list[dict]:
        return self.trace_reader.read_spans(project_id, trace_id)

    # ── core operations ───────────────────────────────────────────────────────

    def promote_trace(
        self, project_id: str, trace_id: str, title: str | None = None
    ) -> EvaluationCase:
        """Turn a (failing) trace into a regression `EvaluationCase`. Idempotent on
        `(project_id, agent_id, input_digest)`."""
        spans = self.trace_reader.read_spans(project_id, trace_id)
        if not spans:
            raise NotFound("trace not found")
        traj = build_trajectory(spans)
        root = root_span(spans)
        agent_id = root.get("agent_id") or next(
            (s.get("agent_id") for s in spans if s.get("agent_id")), ""
        )
        digest = input_digest(spans)

        existing = self._existing_case(project_id, agent_id, digest)
        if existing:
            return existing  # idempotent

        assertions = self._build_assertions(traj)
        # Answer-quality judges that the SOURCE trace failed → the case guards against them too,
        # so a hallucination with a structurally-clean trace is still promotable + gate-able.
        quality_failed = self._grade_source_quality(project_id, spans)
        if quality_failed:
            assertions["quality"] = {"score_names": quality_failed}
        fixture_key = self._store_fixtures(project_id, digest, spans)
        case = self._create_case(
            project_id=project_id, agent_id=agent_id, trace_id=trace_id, root=root,
            digest=digest, title=title, assertions=assertions, fixture_key=fixture_key,
            trajectory_json=traj.to_json(),
        )
        self._attach_to_regression_suite(project_id, agent_id, case)
        self._validate_fail_to_pass(case, traj, trace_id, quality_failed=bool(quality_failed))
        return case

    def replay_case(
        self, project_id: str, case_id: str, candidate_trace_id: str
    ) -> CaseReplay:
        """Re-evaluate a case against a candidate trace and record a `CaseReplay` row."""
        case = self.session.get(EvaluationCase, case_id)
        if not case or case.project_id != project_id:
            raise NotFound("case not found")
        spans = self.trace_reader.read_spans(project_id, candidate_trace_id)
        if not spans:
            raise NotFound("candidate trace not found")
        traj = build_trajectory(spans)
        verdict, detail = self._evaluate(case, traj)
        replay = CaseReplay(
            id=str(uuid.uuid4()), case_id=case.id, candidate_trace_id=candidate_trace_id,
            verdict=verdict, detail=detail,
        )
        self.session.add(replay)
        self.session.commit()
        self.score_writer.write_regression_verdict(case, candidate_trace_id, verdict)
        return replay

    # ── pure-ish helpers (no I/O beyond the session/trace_reader/score_writer) ────

    @staticmethod
    def _evaluate(case: EvaluationCase, traj: Trajectory) -> tuple[str, dict]:
        return evaluate_assertions(case.assertions or {}, case.match_mode, traj)

    def _grade_source_quality(self, project_id: str, spans: list[dict]) -> list[str]:
        """Answer-quality judge `score_name`s the SOURCE trace FAILed. The case is promoted to
        guard against these recurring; the gate re-checks them on replay. Empty when no judge is
        configured / no LLM key — the case then stays a structural-only regression (old behavior)."""
        return [
            r.name
            for r in self.eval_service.grade_trace_quality(project_id, spans)
            if r.verdict == "FAIL"
        ]

    @staticmethod
    def _build_assertions(traj: Trajectory) -> dict:
        # Required tools = everything the agent executed PLUS any tool the model requested but
        # never ran (the silent-failure gap). The case asserts the fixed agent actually calls it.
        ref_tools = required_tools(traj)
        # If the source failed because a tool errored AND the agent itself errored, the
        # regression is "handle the tool error gracefully" — tolerate tool errors and gate on
        # the run outcome.
        src_tool_errs, src_run_errs = split_errors(traj)
        allow_tool_errors = bool(src_tool_errs and src_run_errs)
        return {
            "no_error": True,
            "required_tools": ref_tools,
            "match_mode": "superset",
            "allow_tool_errors": allow_tool_errors,
        }

    @staticmethod
    def _store_fixtures(project_id: str, digest: str, spans: list[dict]) -> str:
        bundle = FixtureBundle.capture(spans)
        key = f"{settings.s3_event_prefix}fixtures/{project_id}/{digest}.json"
        blobstore.put_blob(key, bundle.encode(), "application/json")
        return key

    def _existing_case(
        self, project_id: str, agent_id: str, digest: str
    ) -> Optional[EvaluationCase]:
        return self.session.execute(
            select(EvaluationCase).where(
                EvaluationCase.project_id == project_id,
                EvaluationCase.agent_id == agent_id,
                EvaluationCase.input_digest == digest,
            )
        ).scalar_one_or_none()

    def _create_case(
        self,
        *,
        project_id: str,
        agent_id: str,
        trace_id: str,
        root: dict,
        digest: str,
        title: str | None,
        assertions: dict,
        fixture_key: str,
        trajectory_json: dict,
    ) -> EvaluationCase:
        case = EvaluationCase(
            id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id, level="AGENT_RUN",
            title=title or root.get("name", "") or "case", input_digest=digest, status="DRAFT",
            origin="MANUAL", source_trace_id=trace_id, source_span_id=root.get("span_id", ""),
            agent_version_first_failed=root.get("agent_version_id") or None,
            fixture_bundle_s3_key=fixture_key, reference_trajectory=trajectory_json,
            assertions=assertions, match_mode="superset", tool_args_mode="exact",
            fail_to_pass_validated=False, version=1, created_by="ui",
        )
        self.session.add(case)
        self.session.commit()
        return case

    def _attach_to_regression_suite(
        self, project_id: str, agent_id: str, case: EvaluationCase
    ) -> None:
        suite = self.session.execute(
            select(EvaluationSuite).where(
                EvaluationSuite.project_id == project_id,
                EvaluationSuite.agent_id == agent_id,
                EvaluationSuite.slug == "regressions",
            )
        ).scalar_one_or_none()
        if not suite:
            suite = EvaluationSuite(
                id=str(uuid.uuid4()), project_id=project_id, agent_id=agent_id,
                slug="regressions", name="Regressions", kind="REGRESSION",
            )
            self.session.add(suite)
            self.session.commit()
        self.session.add(EvaluationSuiteCase(suite_id=suite.id, case_id=case.id))
        self.session.commit()

    def _validate_fail_to_pass(
        self,
        case: EvaluationCase,
        traj: Trajectory,
        trace_id: str,
        quality_failed: bool = False,
    ) -> None:
        """The source (failing) trace must currently FAIL the case for it to be PROMOTED — either
        structurally (the tool/error contract) OR on answer quality (a hallucination whose trace
        is structurally clean). Otherwise the case is a non-discriminating no-op and stays DRAFT."""
        verdict, detail = self._evaluate(case, traj)
        recorded = "FAIL" if (verdict == "FAIL" or quality_failed) else verdict
        if quality_failed and verdict != "FAIL":
            detail = {**detail, "quality_pass": False, "promoted_on": "quality"}
        case.fail_to_pass_validated = recorded == "FAIL"
        case.status = "PROMOTED" if case.fail_to_pass_validated else "DRAFT"
        self.session.add(CaseReplay(
            id=str(uuid.uuid4()), case_id=case.id, candidate_trace_id=trace_id,
            verdict=recorded, detail={**detail, "validation": True},
        ))
        self.session.commit()
        self.score_writer.write_regression_verdict(case, trace_id, recorded)
