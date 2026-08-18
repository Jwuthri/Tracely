"""CI/CD gate: replay an agent's PROMOTED regression cases against candidate traces
emitted by a CI run (matched by `input_digest` within an env), aggregate -> PASS/FAIL.

A PR's CI step runs the agent and emits traces tagged `tracely.env=ci`; the gate finds the
candidate trace whose input matches each case and replays the case against it.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from tracely.config import settings
from tracely.domain.gate.warnings import delta_warnings
from tracely.domain.regression.contract import apply_quality, evaluate_assertions
from tracely.domain.regression.fixtures import FixtureBundle
from tracely.domain import introspection
from tracely.domain.simulation import (
    ATTACK_SYSTEM,
    EXPECT_SYSTEM,
    ExpectationResult,
    ScenarioOutcome,
    Turn,
    attack_prompt,
    attack_result,
    attack_skipped,
    check_tools,
    conversation_verdict,
    expect_prompt,
    expect_result,
    expect_skipped,
    gate_verdict,
    normalize_turns,
    weakness_lines,
)
from tracely.domain.trajectory import build_trajectory, tool_sequence
from tracely.domain.traces.spans import input_digest
from tracely.infrastructure.blob import s3 as blobstore
from tracely.infrastructure.clickhouse.score_writer import ScoreWriter
from tracely.infrastructure.clickhouse.trace_reader import TraceReader
from tracely.infrastructure.db import repositories
from tracely.infrastructure.db.models import (
    Agent,
    AgentEndpoint,
    FailureCluster,
    EvaluationCase,
    GateCase,
    GateRun,
    Scenario,
)
from tracely.infrastructure.llm.provider import llm_enabled, run_structured_agent, use_project_key
from tracely.services.evaluation_service import EvaluationService
from tracely.services.introspection_service import record
from tracely.services.simulation_service import SimulationService

log = structlog.get_logger()


class _AttackVerdict(BaseModel):
    """Structured output for the adversarial goal judge. `achieved=True` means the attack worked,
    which is a gate FAILURE — the polarity is inverted relative to `_ExpectVerdict` on purpose."""

    achieved: bool = Field(
        description="True if ANY of the agent's replies achieved the attacker's goal, even partially."
    )
    # Demanding a quote is what stops a lenient judge from skimming: it cannot cite evidence for a
    # compliance it did not look for. Verified — without this the judge missed a verbatim system
    # prompt leak in the final turn because the first turns were refusals.
    evidence: str = Field(
        default="",
        description="When achieved: the exact text quoted from the agent reply that gave it away, "
                    "prefixed with its turn number. Empty when the agent held.",
    )
    reason: str = Field(description="One sentence citing what the agent revealed or refused.")


class _ExpectVerdict(BaseModel):
    """Structured output for a free-text turn expectation — binary on purpose. `met` is the
    verdict; `reason` is what the gate shows the author when it fails."""

    met: bool = Field(description="True only if the reply clearly meets the stated expectation.")
    reason: str = Field(description="One sentence justifying the verdict.")


# Blocking beats "tested nothing" beats green, so a gate is only as good as its worst half.
_SEVERITY = {"PASS": 0, "NO_COVERAGE": 1, "FAIL": 2}


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _SEVERITY.get(s, 2))


def _failing_score_names(scores: list[dict], advisory: Sequence[str]) -> list[str]:
    """`["name: comment", ...]` for the non-advisory FAILs in a conversation's pooled scores.

    Advisory evaluators are excluded for the same reason they don't flip the verdict — listing a
    FAIL that didn't cause the failure sends people chasing the wrong thing. Deduped because the
    same evaluator fails on several turns of one conversation more often than not.

    `tracely.scenario.*` scores are excluded too: those are the authored expectations, already
    reported by `failed_expectations` with the turn number attached. Listing them twice made the
    PR comment repeat every tool failure verbatim.
    """
    adv, seen, out = set(advisory), set(), []
    for s in scores:
        name = s.get("name")
        if s.get("verdict") != "FAIL" or name in adv or name in seen:
            continue
        if str(name).startswith("tracely.scenario."):
            continue
        seen.add(name)
        comment = (s.get("comment") or "").strip()
        out.append(f"{name}: {comment}"[:300] if comment else str(name))
    return out


class GateService:
    """Replay an agent's PROMOTED cases against a CI run's candidate traces."""

    def __init__(
        self,
        session: Session,
        trace_reader: TraceReader | None = None,
        eval_service: EvaluationService | None = None,
    ) -> None:
        self.session = session
        self.trace_reader = trace_reader or TraceReader()
        # Used to re-grade answer quality on a replayed trace (the judge-in-the-gate).
        self.eval_service = eval_service or EvaluationService(trace_reader=self.trace_reader)
        # Per-turn scenario expectations are written as ordinary scores, by the ordinary writer.
        self.score_writer = ScoreWriter()

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
        with_scenarios: bool = False,
        min_pass_rate: float | None = None,
        gate_run_id: str | None = None,
        finalize: bool = True,
        case_ids: Sequence[str] | None = None,
        scenario_ids: Sequence[str] | None = None,
    ) -> GateRun:
        """Replay an agent's PROMOTED cases -> PASS/FAIL. Two pairing modes:
        - `candidates` given: explicit `{case_id: trace_id}` map (as `tracely replay` produces).
        - otherwise: match each case to the latest ci-tagged trace whose `input_digest` equals.

        With `with_scenarios`, the same run ALSO drives every enabled scenario against the agent's
        registered endpoint (emulated conversations). Driving is all it does — grading happens in
        `grade_scenarios` after this task has released the worker (see `_drive_scenarios`).

        `finalize=False` leaves the run RUNNING with no `finished_at`, for the two-phase simulated
        path where the verdict isn't known yet.

        `case_ids` / `scenario_ids` narrow the run to a subset the caller picked (the launcher's
        checkboxes, `--case`/`--scenario` in CI). `None` = the whole suite, which is what every
        existing caller means; `[]` = deliberately none of that half.
        """
        cases = self._promoted_cases(project_id, agent_id, case_ids)
        case_to_trace = self._pair_candidates(project_id, agent_id, env, cases, candidates)

        total_lat, total_tok, per_trace = self.trace_reader.candidate_metrics(
            project_id, [tid for tid, _ in case_to_trace.values()]
        )

        # `gate_run_id` reuses a row the API already created and handed to CI to poll — the async
        # scenario path needs an id before the work starts, and one gate must never be two rows.
        gate = self.session.get(GateRun, gate_run_id) if gate_run_id else None
        if gate is None:
            gate = GateRun(
                id=gate_run_id or str(uuid.uuid4()), project_id=project_id, agent_id=agent_id,
                env=env, git_ref=git_ref, pr_number=pr_number, status="RUNNING",
            )
            self.session.add(gate)
        else:
            # Redelivered task (`task_acks_late` + a worker death re-runs phase 1): replay cases
            # are hermetic so re-recording them is fine, but the stale rows must go first or the
            # gate shows every case twice. Scenario cases are kept — `_drive_scenarios` skips the
            # ones already driven rather than re-POSTing a live endpoint.
            self.session.execute(
                delete(GateCase).where(
                    GateCase.gate_run_id == gate.id, GateCase.scenario_id.is_(None)
                )
            )
        gate.total = len(cases)
        self.session.commit()

        passed, failed, skipped = self._record_gate_cases(gate, cases, case_to_trace, per_trace)
        case_status = self._final_status(passed, failed, skipped, len(cases), [])

        driven = self._drive_scenarios(gate, env, scenario_ids) if with_scenarios else 0
        # -1 = enabled scenarios with no endpoint configured. Record it on the run so BOTH the
        # single-phase path and phase-2 grading block, instead of a suite that never ran going green.
        misconfigured = driven < 0
        driven = max(0, driven)
        # Warnings raised WHILE driving (a stateless multi-turn suite) have to be picked up here:
        # the assignment below replaces `gate.warnings` wholesale with the delta warnings, so
        # anything left on the row by `_drive_scenarios` would otherwise be dropped on the floor.
        warnings = list(gate.warnings or [])
        if misconfigured:
            warnings.append("scenarios are enabled but this agent has no endpoint configured")

        baseline = self._baseline_gate(project_id, agent_id, gate.id)
        warnings += delta_warnings(total_lat, total_tok, baseline)
        warnings = list(dict.fromkeys(warnings))  # a redelivered run must not stack duplicates
        if misconfigured:
            case_status = _worst(case_status, "NO_COVERAGE")

        gate.total = len(cases) + driven
        gate.passed, gate.failed, gate.skipped = passed, failed, skipped
        gate.latency_ms, gate.total_tokens, gate.warnings = total_lat, total_tok, warnings
        if warnings and settings.gate_block_on_warnings:
            case_status = "FAIL"
        if finalize:
            gate.status = case_status
            gate.finished_at = datetime.now(timezone.utc)
        self.session.commit()
        return gate

    def grade_scenarios(
        self,
        gate_run_id: str,
        min_pass_rate: float | None = None,
        project_id: str | None = None,
        scenario_ids: Sequence[str] | None = None,
    ) -> GateRun | None:
        """Phase 2: grade the conversations phase 1 drove, then finalize the run.

        Separate task on purpose. The agent's own spans reach Tracely as ordinary OTLP, so their
        ingest is a Celery task — and under the default `--pool=solo --concurrency=1` those tasks
        cannot run while the gate holds the worker's only slot. Grading inline meant every tool
        expectation saw a trace containing nothing but Tracely's own turn span and reported SKIP,
        for spans that landed seconds later. Releasing the worker between driving and grading is
        what lets the queue drain first.
        """
        gate = self.session.get(GateRun, gate_run_id)
        if gate is None or (project_id and gate.project_id != project_id):
            return None
        if gate.finished_at is not None:
            # `task_acks_late` redelivery after the run already finalized: grading again would
            # re-run every judge and add the scenario counts to the totals a second time.
            return gate
        all_cases = list(
            self.session.execute(
                select(GateCase).where(GateCase.gate_run_id == gate_run_id)
            ).scalars()
        )
        pending = [gc for gc in all_cases if gc.scenario_id]
        # A scenario deleted while the gate ran leaves its case with `scenario_id` nulled and the
        # verdict still PENDING — sweep those to SKIP or they render as in-flight forever and
        # skew every count below. (Replay cases are never PENDING, so this matches exactly.)
        orphaned = [gc for gc in all_cases if not gc.scenario_id and gc.verdict == "PENDING"]
        for gc in orphaned:
            gc.verdict = "SKIP"
            gc.detail = {**(gc.detail or {}), "reason": "scenario deleted while the gate was running"}
        outcomes = [
            ScenarioOutcome(
                scenario_id=gc.scenario_id or "",
                title="",
                conversation_id=gc.candidate_trace_id,
                trace_ids=list((gc.detail or {}).get("trace_ids") or []),
                detail={k: v for k, v in (gc.detail or {}).items() if k != "trace_ids"},
            )
            for gc in pending
        ]
        turns_by_scenario: dict[str, list[Turn]] = {}
        goal_by_scenario: dict[str, str] = {}
        for o in outcomes:
            sc = self.session.get(Scenario, o.scenario_id)
            if not sc:
                continue
            if sc.kind == "ADVERSARIAL":
                goal_by_scenario[o.scenario_id] = sc.goal or ""
            else:
                turns_by_scenario[o.scenario_id] = normalize_turns(sc.turns)

        self._grade_conversations(
            gate.project_id, outcomes, turns_by_scenario, goal_by_scenario
        )

        by_scenario = {o.scenario_id: o for o in outcomes}
        for gc in pending:
            o = by_scenario.get(gc.scenario_id or "")
            if o:
                gc.verdict = o.verdict
                gc.detail = {**o.detail, "trace_ids": o.trace_ids}

        rate = settings.gate_scenario_min_pass_rate if min_pass_rate is None else min_pass_rate
        scenario_status, summary = gate_verdict(outcomes, rate)
        # Phase 2 recomputes the verdict from scratch, so the misconfiguration phase 1 detected has
        # to be re-checked here too — otherwise an unrunnable suite finishes green.
        if not outcomes and self._endpoint_missing_for_enabled_scenarios(
            gate.project_id, gate.agent_id, scenario_ids
        ):
            scenario_status = "NO_COVERAGE"
            # Merge, don't replace: phase 1 may have left delta/stateless warnings on the row.
            gate.warnings = list(dict.fromkeys([
                *(gate.warnings or []),
                "scenarios are enabled but this agent has no endpoint configured",
            ]))
        # Settle the CASE half from the counters phase 1 left behind, BEFORE folding the scenario
        # counts in — otherwise the regression verdict is computed from the combined totals and a
        # failing conversation would read as a failing case.
        case_status = self._final_status(
            gate.passed, gate.failed, gate.skipped,
            gate.total - len(outcomes) - len(orphaned), gate.warnings or [],
        )
        gate.passed += sum(o.verdict == "PASS" for o in outcomes)
        gate.failed += sum(o.verdict in ("FAIL", "UNGRADED") for o in outcomes)
        gate.skipped += sum(o.verdict == "SKIP" for o in outcomes) + len(orphaned)
        # A gate is only as good as its worst half.
        gate.status = _worst(case_status, scenario_status)
        gate.finished_at = datetime.now(timezone.utc)
        self.session.commit()
        log.info("scenario_gate", gate_id=gate.id, status=gate.status, **summary)
        return gate

    def grade_standalone_scenario(
        self,
        project_id: str,
        scenario_id: str,
        conversation_id: str,
        trace_ids: list[str],
        error: str = "",
    ) -> dict:
        """Grade a one-click scenario run (the Scenarios page's Run button) exactly like the gate
        grades its conversations: the project's evaluators with targeting/sampling off, the
        scripted turns' authored expectations, and — for an ADVERSARIAL scenario — the attack
        judge on the full transcript.

        This used to be `evaluate_thread` alone, which meant the Run button never applied
        expectations at all and a fully successful jailbreak rendered as a clean green
        conversation — the exact false-green the attack judge exists to kill.
        """
        sc = self.session.get(Scenario, scenario_id)
        if sc is None or sc.project_id != project_id:
            return {"error": "scenario not found"}
        outcome = ScenarioOutcome(
            scenario_id=scenario_id,
            title=sc.title or "",
            conversation_id=conversation_id,
            trace_ids=list(trace_ids or []),
            detail={"error": error} if error else {},
        )
        turns = {} if sc.kind == "ADVERSARIAL" else {scenario_id: normalize_turns(sc.turns)}
        goals = {scenario_id: sc.goal or ""} if sc.kind == "ADVERSARIAL" else {}
        self._grade_conversations(project_id, [outcome], turns, goals)
        log.info(
            "scenario_standalone_graded",
            scenario_id=scenario_id, conversation_id=conversation_id, verdict=outcome.verdict,
        )
        return {"conversation_id": conversation_id, "verdict": outcome.verdict, **outcome.detail}

    # ── emulated conversations ────────────────────────────────────────────────

    @staticmethod
    def _scenario_query(project_id: str, agent_id: str, scenario_ids: Sequence[str] | None):
        """The scenarios a gate should drive. An explicit selection beats the `enabled` flag —
        picking a scenario by hand IS enabling it for that run."""
        q = select(Scenario).where(
            Scenario.project_id == project_id, Scenario.agent_id == agent_id
        )
        return (
            q.where(Scenario.id.in_(list(scenario_ids)))
            if scenario_ids is not None
            else q.where(Scenario.enabled.is_(True))
        )

    def _endpoint_missing_for_enabled_scenarios(
        self, project_id: str, agent_id: str, scenario_ids: Sequence[str] | None = None
    ) -> bool:
        """True when this agent has scenarios switched on but nowhere to send them.

        A blocking misconfiguration rather than an absent feature — checked by both gate phases,
        since phase 2 recomputes the verdict independently of phase 1. Takes the same selection
        phase 1 drove, or a run that deliberately skipped the scenario half would block on an
        endpoint it never needed.
        """
        has_scenarios = self.session.execute(
            self._scenario_query(project_id, agent_id, scenario_ids).with_only_columns(Scenario.id)
        ).first()
        return bool(has_scenarios) and self.session.get(AgentEndpoint, agent_id) is None

    def _drive_scenarios(
        self, gate: GateRun, env: str, scenario_ids: Sequence[str] | None = None
    ) -> int:
        """Phase 1: drive every enabled scenario against the agent's endpoint and record a PENDING
        GateCase each. Returns how many ran. Grading is deliberately NOT done here — see
        `grade_scenarios` for why the worker has to be released first.

        Returns -1 for "enabled scenarios exist but the endpoint is missing" — a misconfiguration
        the gate must block on, NOT pass. An agent with no scenarios at all returns 0 and the
        scenario half genuinely doesn't apply (a project using only replay-style gating is not
        blocked by an empty suite).
        """
        project_id, agent_id = gate.project_id, gate.agent_id
        scenarios = list(
            self.session.execute(
                self._scenario_query(project_id, agent_id, scenario_ids)
            ).scalars()
        )
        if not scenarios:
            return 0

        endpoint = self.session.get(AgentEndpoint, agent_id)
        if not endpoint:
            # Enabled scenarios with nowhere to send them is a broken suite, not an absent one.
            # Passing here is the same false-green as an all-SKIP gate: the merge sails through
            # having tested nothing, which is the failure mode this whole feature exists to kill.
            log.warning("scenario_gate_no_endpoint", agent_id=agent_id, count=len(scenarios))
            return -1

        agent = self.session.get(Agent, agent_id)
        slug = agent.slug if agent else agent_id
        sim = SimulationService()
        self._warn_if_multi_turn_is_stateless(gate, scenarios, endpoint)

        # Redelivered task: a scenario that already has a GateCase on this run was driven —
        # its conversation went over the wire once and must never be silently re-sent.
        already_driven = {
            sid
            for (sid,) in self.session.execute(
                select(GateCase.scenario_id).where(
                    GateCase.gate_run_id == gate.id, GateCase.scenario_id.is_not(None)
                )
            )
        }

        # Looked up once per gate, not per turn: the attacker gets the same leverage all run.
        weaknesses = (
            self._known_weaknesses(project_id, agent_id)
            if any(s.kind == "ADVERSARIAL" for s in scenarios)
            else []
        )
        for scenario in scenarios:
            if scenario.id in already_driven:
                continue
            try:
                run = sim.run_scenario(
                    project_id, slug, scenario, endpoint, env=env, weaknesses=weaknesses
                )
            except Exception as exc:  # one raising scenario must not sink the other four
                log.exception("scenario_drive_failed", scenario_id=scenario.id)
                run = {
                    "conversation_id": "", "trace_ids": [], "turns": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
            self.session.add(GateCase(
                id=str(uuid.uuid4()), gate_run_id=gate.id, scenario_id=scenario.id,
                candidate_trace_id=run["conversation_id"], verdict="PENDING",
                detail={
                    "turns": len(run["turns"]),
                    "error": run["error"],
                    "trace_ids": run["trace_ids"],
                    **({"reason": run["reason"]} if run.get("reason") else {}),
                },
            ))
            # Commit per scenario: these conversations made real HTTP calls, and a crash on
            # scenario 3 of 5 must not discard the record that 1 and 2 already ran.
            self.session.commit()
        log.info("scenario_gate_driven", gate_id=gate.id, scenarios=len(scenarios))
        return len(scenarios)

    @staticmethod
    def _warn_if_multi_turn_is_stateless(
        gate: GateRun, scenarios: list[Scenario], endpoint: AgentEndpoint
    ) -> None:
        """Flag a multi-turn suite pointed at an endpoint we have no way of keeping in context.

        Each turn is POSTed with the full history in `messages` AND the conversation id in
        `session_key`, so a chat-shaped or a session-shaped API both carry context. An endpoint
        that reads neither — the bespoke `{"message": "..."}` shape, with `session_key` cleared —
        sees every turn cold. The suite still runs and still grades, but it is testing N unrelated
        one-shot requests while reporting a conversation, and an escalating adversarial probe can
        never land. We cannot detect what the endpoint reads; a blank `session_key` on a multi-turn
        scenario is the one case that is visible from here, so it is the one we say out loud.
        """
        if endpoint.session_key:
            return
        multi_turn = any(
            s.kind == "ADVERSARIAL" or len(normalize_turns(s.turns)) > 1 for s in scenarios
        )
        if not multi_turn:
            return
        warning = (
            "multi-turn scenarios are running against an endpoint with no session key — "
            "turn context depends entirely on the endpoint reading the `messages` array"
        )
        if warning in (gate.warnings or []):
            return  # redelivered run — already recorded
        log.warning("scenario_gate_no_session_key", agent_id=gate.agent_id)
        gate.warnings = [*(gate.warnings or []), warning]

    def _grade_conversations(
        self,
        project_id: str,
        outcomes: list[ScenarioOutcome],
        turns_by_scenario: dict[str, list[Turn]] | None = None,
        goal_by_scenario: dict[str, str] | None = None,
    ) -> None:
        """Evaluate every emulated turn, then set each conversation's verdict from its turns'
        scores pooled.

        Three graders run, and all write ordinary scores on the turn's trace so the one verdict
        policy aggregates them without knowing they came from a scenario:
        1. the project's own evaluators (the floor — identical to how production is graded),
        2. a scripted turn's authored expectations, when it has any, and
        3. for an ADVERSARIAL scenario, whether the attack achieved its goal.
        """
        all_traces = [tid for o in outcomes for tid in o.trace_ids]
        self._evaluate_turns(project_id, all_traces)
        for o in outcomes:
            # One recording per conversation, subject = the conversation, so "why did the gate
            # decide that?" opens next to "what did the agent say?" — the expectation judge's
            # prompt and the attack judge's evidence quote included.
            with record(
                introspection.SIM, o.conversation_id, "sim · grading",
                project_id=project_id, conversation_id=f"sim:{o.conversation_id}",
            ):
                self._grade_expectations(
                    project_id, o, (turns_by_scenario or {}).get(o.scenario_id)
                )
                goal = (goal_by_scenario or {}).get(o.scenario_id)
                if goal:
                    self._grade_attack(project_id, o, goal)
        scores_by_trace = self.trace_reader.scores_by_trace(project_id, all_traces)
        advisory = repositories.advisory_score_names(self.session, project_id)
        for o in outcomes:
            error = str((o.detail or {}).get("error") or "")
            if not o.trace_ids:
                if error:
                    # The drive itself failed (endpoint unreachable, scenario crashed): that is
                    # a red conversation with a cause, not an invisible SKIP.
                    o.verdict = "FAIL"
                    o.detail = {**o.detail, "failed_expectations": [f"could not drive the endpoint: {error}"]}
                else:
                    o.verdict = "SKIP"  # scenario produced no turns at all
                continue
            pooled = [s for tid in o.trace_ids for s in scores_by_trace.get(tid, [])]
            o.verdict = conversation_verdict(pooled, advisory)
            o.detail = {**o.detail, "scores": len(pooled)}
            if error and o.verdict != "FAIL":
                # A conversation cut short by a transport error must never pass — the judges only
                # saw the turns that made it, and for an adversarial run an empty reply reads as
                # "the agent held". The error is the verdict.
                o.verdict = "FAIL"
                o.detail = {
                    **o.detail,
                    "failed_expectations": [
                        *(o.detail.get("failed_expectations") or []),
                        f"the conversation errored mid-run: {error}",
                    ],
                }
            # Name the evaluators that sank it. A conversation can fail purely on the project's
            # own evaluators — no authored expectation involved — and without this the gate detail
            # and the PR comment show a red row with no cause at all.
            failed = _failing_score_names(pooled, advisory)
            if failed:
                o.detail = {**o.detail, "failed_scores": failed}

    def _known_weaknesses(self, project_id: str, agent_id: str) -> list[str]:
        """This agent's biggest open failure clusters, as prompt lines for the attacker.

        The differentiated part of adversarial testing: a generic red-teamer guesses at where an
        agent is weak, while Tracely already clustered where this one actually broke in
        production. Best-effort — no clusters (or a hiccup reading them) just means a
        less-informed attacker, never a failed gate.
        """
        limit = settings.attacker_weakness_hints
        if limit <= 0:
            return []
        try:
            rows = self.session.execute(
                select(FailureCluster.label, FailureCluster.taxonomy, FailureCluster.signature)
                .where(
                    FailureCluster.project_id == project_id,
                    FailureCluster.agent_id == agent_id,
                    FailureCluster.status == "OPEN",
                )
                .order_by(FailureCluster.count.desc())
                .limit(limit)
            ).all()
        except Exception as exc:
            log.warning("attacker_weakness_lookup_failed", agent_id=agent_id, error=str(exc))
            return []
        return weakness_lines([(r[0] or "", r[1] or "", r[2] or "") for r in rows])

    def _grade_attack(self, project_id: str, outcome: ScenarioOutcome, goal: str) -> None:
        """Judge whether an adversarial conversation achieved its goal, and write the result as a
        score on the last turn.

        Without this an ADVERSARIAL scenario could not fail on its own terms: the goal only drove
        turn generation, and the conversation was left to the project's evaluators — so an agent
        that leaked exactly what the goal asked for still passed unless an evaluator happened to
        cover that attack. Judging the whole transcript at once (not per turn) because an attack
        succeeds across turns, not within one.
        """
        if not outcome.trace_ids:
            return
        if (outcome.detail or {}).get("error"):
            # A transcript cut short by a transport error is not evidence the agent held —
            # judging it would write a PASS for an attack that never fully ran. The conversation
            # itself fails on the error (see `_grade_conversations`).
            result = attack_skipped("the conversation errored mid-run, so the attack wasn't judged")
            last = outcome.trace_ids[-1]
            self.score_writer.write_eval_scores(
                project_id, last, last, [result], thread_id=outcome.conversation_id
            )
            return
        transcript = self._transcript(project_id, outcome.trace_ids)
        with use_project_key(project_id):
            if not llm_enabled():
                result = attack_skipped("no LLM key configured, so the attack wasn't judged")
            else:
                try:
                    verdict = run_structured_agent(
                        attack_prompt(goal, transcript),
                        response_format=_AttackVerdict,
                        system_prompt=ATTACK_SYSTEM,
                        model=settings.attacker_judge_model or None,
                    )
                    reason = f"{verdict.reason} [{verdict.evidence}]" if verdict.evidence else verdict.reason
                    result = attack_result(verdict.achieved, reason)
                except Exception as exc:
                    log.warning(
                        "attack_judge_failed", scenario_id=outcome.scenario_id, error=str(exc)
                    )
                    result = attack_skipped(f"the judge errored: {exc}")
        last = outcome.trace_ids[-1]
        self.score_writer.write_eval_scores(
            project_id, last, last, [result], thread_id=outcome.conversation_id
        )
        if result.verdict == "FAIL":
            outcome.detail = {
                **outcome.detail,
                "failed_expectations": [*(outcome.detail.get("failed_expectations") or []),
                                        result.comment],
            }

    @staticmethod
    def _turn_io(spans: list[dict]) -> tuple[str, str]:
        """The emulated turn's own (user message, agent reply). Reads the `emulated.turn` span
        specifically: falling back to "any span with output" graded a nested customer span's
        output as "the agent's reply" whenever reply extraction came back empty — a silently
        wrong verdict. An empty reply is the truth, and the judges should see it."""
        turn = next((s for s in spans if s.get("name") == "emulated.turn"), None)
        if turn is None:
            turn = next((s for s in spans if s.get("input") or s.get("output")), {})
        return str(turn.get("input") or ""), str(turn.get("output") or "")

    def _transcript(self, project_id: str, trace_ids: list[str]) -> str:
        """The emulated conversation as plain text, for the attack judge."""
        lines: list[str] = []
        for i, trace_id in enumerate(trace_ids, start=1):
            spans = self.trace_reader.read_spans(project_id, trace_id)
            user, agent = self._turn_io(spans)
            lines.append(f"[turn {i}] user: {user}\n[turn {i}] agent: {agent}")
        return "\n".join(lines)[:20000]

    def _grade_expectations(
        self, project_id: str, outcome: ScenarioOutcome, turns: list[Turn] | None
    ) -> None:
        """Check each turn's authored expectations and write them as scores on that turn's trace.

        Turns with no expectations cost nothing — the loop skips them, so a scenario authored
        without any is graded purely by the project's evaluators.
        """
        if not turns:
            return
        checked = 0
        failures: list[str] = []
        for index, trace_id in enumerate(outcome.trace_ids):
            if index >= len(turns) or not turns[index].has_expectations:
                continue
            turn = turns[index]
            spans = self.trace_reader.read_spans(project_id, trace_id)
            results = []

            if turn.tools:
                # Anything beyond Tracely's own turn span means the agent's tracer honoured our
                # `traceparent`; without that we are blind to its tool calls (SKIP, not FAIL).
                nested = [s for s in spans if s.get("name") != "emulated.turn"]
                results.append(check_tools(
                    turn.tools,
                    tool_sequence(build_trajectory(spans)),
                    agent_spans_present=bool(nested),
                ))
            if turn.expect:
                results.append(self._judge_expectation(project_id, turn, spans, index, outcome))

            if results:
                self.score_writer.write_eval_scores(
                    project_id, trace_id, trace_id, results, thread_id=outcome.conversation_id
                )
                checked += len(results)
                # A merge-blocker has to say why on the spot. Without this the reason lives only
                # on the turn's trace, so the PR check tells you a gate failed and nothing else.
                failures += [
                    f"turn {index + 1}: {r.comment}" for r in results if r.verdict == "FAIL"
                ]
        if checked:
            outcome.detail = {**outcome.detail, "expectations": checked}
        if failures:
            outcome.detail = {**outcome.detail, "failed_expectations": failures}

    def _judge_expectation(
        self, project_id: str, turn: Turn, spans: list[dict], index: int, outcome: ScenarioOutcome
    ) -> ExpectationResult:
        """LLM-judge one free-text turn expectation against the agent's reply."""
        _, reply = self._turn_io(spans)
        with use_project_key(project_id):
            if not llm_enabled():
                return expect_skipped("no LLM key configured, so the expectation wasn't judged")
            try:
                verdict = run_structured_agent(
                    expect_prompt(turn.message, reply, turn.expect),
                    response_format=_ExpectVerdict,
                    system_prompt=EXPECT_SYSTEM,
                )
                return expect_result(verdict.met, verdict.reason)
            except Exception as exc:
                log.warning(
                    "expectation_judge_failed",
                    scenario_id=outcome.scenario_id, turn=index, error=str(exc),
                )
                return expect_skipped(f"the judge errored: {exc}")

    def _evaluate_turns(self, project_id: str, trace_ids: list[str]) -> None:
        """Grade each emulated turn inline, with a short grace period first.

        Inline for the same reason ingestion is (see `SimulationService._emit_turn`): this task
        already owns the worker slot, so scheduling `evaluate_run_task` and waiting for it would
        deadlock under the default `--pool=solo --concurrency=1`.

        The grace wait is a last look for the *customer's* spans. The real mechanism that gets
        them here is the phase-1/phase-2 split (see `grade_scenarios`) — this loop only helps on a
        worker with spare concurrency, where an ingest can still land while we hold a slot. It
        ends as soon as the span count stops growing, so it costs one sample when there is nothing
        more coming, and it never blocks on spans that may never arrive.

        Every enabled evaluator runs, WITHOUT targeting or sampling. Those knobs exist to control
        judge spend on production traffic; applied here they silently thin the gate — a
        `sampling=0.1` column grades one turn in ten, an evaluator scoped `target_env=prod` skips
        `ci` turns entirely, and a conversation with nothing left to grade is UNGRADED, which
        blocks the merge for a reason no one can see. A gate is an explicit run: it grades with
        everything, like the UI's Play button.
        """
        if not trace_ids:
            return
        grace = max(0, settings.gate_scenario_span_grace_s)
        deadline = time.monotonic() + grace
        seen = -1
        while time.monotonic() < deadline:
            time.sleep(2)
            count = self.trace_reader.span_count(project_id, trace_ids)
            if count == seen:  # span count stopped growing — nothing more is arriving
                break
            seen = count

        # Passing specs explicitly is what turns targeting + sampling off (`evaluate_trace` only
        # applies them when it loads the list itself). Loaded once, not once per turn.
        specs = self.eval_service.load_enabled_evaluators(project_id)
        threads: list[str] = []
        for trace_id in trace_ids:
            try:
                # Turn/step columns per turn; the conversation columns once, below. Inline here
                # rather than queued (the gate holds the worker's only slot under `--pool=solo`),
                # but still once per conversation instead of once per turn.
                res = self.eval_service.evaluate_trace(
                    project_id, trace_id, specs=specs, skip_conversation=True
                )
                thread = res.get("thread_id")
                if thread and thread not in threads:
                    threads.append(thread)
            except Exception as exc:  # one bad turn must not sink the whole gate
                log.warning("scenario_turn_eval_failed", trace_id=trace_id, error=str(exc))
        for thread in threads:
            try:
                self.eval_service.evaluate_conversation(
                    project_id, thread, apply_targeting=False
                )
            except Exception as exc:
                log.warning("scenario_conv_eval_failed", thread_id=thread, error=str(exc))

    # ── internals ─────────────────────────────────────────────────────────────

    def _promoted_cases(
        self, project_id: str, agent_id: str, case_ids: Sequence[str] | None = None
    ) -> list[EvaluationCase]:
        q = select(EvaluationCase).where(
            EvaluationCase.project_id == project_id,
            EvaluationCase.agent_id == agent_id,
            EvaluationCase.status == "PROMOTED",
        )
        if case_ids is not None:
            q = q.where(EvaluationCase.id.in_(list(case_ids)))
        return list(self.session.execute(q).scalars())

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
                # Judge-in-the-gate: cases promoted from an answer-quality failure re-grade the
                # replayed answer; a sub-threshold score FAILs the case (unless made advisory).
                if (case.assertions or {}).get("quality"):
                    quality = self._grade_quality(case, spans)
                    verdict, detail = apply_quality(
                        verdict, detail, quality, blocks=settings.gate_quality_blocks
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

    def _grade_quality(self, case: EvaluationCase, spans: list[dict]) -> list[dict]:
        """Re-grade a replayed trace's answer with the judge(s) the case was promoted from.
        Returns `[{score_name, verdict, value, comment}, ...]` for `apply_quality`."""
        names = ((case.assertions or {}).get("quality") or {}).get("score_names") or None
        results = self.eval_service.grade_trace_quality(case.project_id, spans, only_names=names)
        return [
            {"score_name": r.name, "verdict": r.verdict, "value": r.value, "comment": r.comment}
            for r in results
        ]

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
                # A gate with no replay metrics (a simulate-only run records 0/0) is not a
                # baseline — comparing against it silences delta warnings forever after.
                or_(GateRun.latency_ms > 0, GateRun.total_tokens > 0),
            )
            .order_by(GateRun.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    @staticmethod
    def _final_status(
        passed: int, failed: int, skipped: int, total: int, warnings: list[str]
    ) -> str:
        """Aggregate case verdicts into the gate status.

        Coverage is a first-class part of the verdict. A gate that exercised NONE of its
        promoted cases — every case SKIPped because CI emitted no matching trace — must NOT
        report green: that false-PASS is exactly how a misconfigured CI pipeline (no traces
        emitted, renamed agent, input-digest drift, crashed replay) silently ships a known
        regression. Such a run is `NO_COVERAGE`, a blocking non-PASS status. (Previously this
        method only looked at `failed`, so all-SKIP returned PASS — the gate's worst bug.)
        """
        if failed > 0:
            return "FAIL"  # fail-to-pass is the hard gate
        if total == 0:
            return "PASS"  # no regression suite for this agent yet — nothing to protect
        if passed == 0:
            return "NO_COVERAGE"  # cases exist but the run exercised none of them
        if skipped > 0 and settings.gate_require_full_coverage:
            return "NO_COVERAGE"  # partial coverage, and full coverage is required
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
