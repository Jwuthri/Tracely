"""Scenario-subsystem hardening: the failure modes that made a gate (or the Run button) lie.

Service-level with a sync in-memory SQLite registry and fakes for ClickHouse/HTTP, plus one
router-level harness (same shape as `test_clusters_promote`) for the endpoint PUT. Pins:

- a transport error can never grade as PASS — it FAILs the conversation with the error as cause,
- the attack judge is not consulted on an errored transcript (an empty reply is not "held"),
- the one-click Run grades through the SAME path as the gate: expectations AND the attack judge,
- `grade_scenarios` is idempotent under `task_acks_late` redelivery,
- one raising scenario doesn't discard the other scenarios' driven conversations,
- a redelivered drive never re-POSTs a conversation that already went over the wire,
- a gate launched for a SUBSET runs exactly that subset, and doesn't block on the rest,
- `PUT /agents/{ref}/endpoint` only touches the keys present in the body.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from tracely.config import settings
from tracely.domain.simulation import ScenarioOutcome
from tracely.infrastructure.db import models
from tracely.infrastructure.db.base import Base
from tracely.services.gate_service import GateService

PROJECT = "p1"

_SYNC_TABLES = [
    models.Evaluator.__table__,  # advisory_score_names reads it; empty table = nothing advisory
    models.Agent.__table__,
    models.AgentEndpoint.__table__,
    models.Scenario.__table__,
    models.EvaluationCase.__table__,
    models.GateRun.__table__,
    models.GateCase.__table__,
]


@pytest.fixture
def db():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng, tables=_SYNC_TABLES)
    with Session(eng) as s:
        yield s
    eng.dispose()


class _Reader:
    """TraceReader stand-in: canned spans + pooled scores, zero span growth."""

    def __init__(self, scores: dict | None = None, spans: dict | None = None):
        self._scores = scores or {}
        self._spans = spans or {}

    def scores_by_trace(self, project_id, trace_ids):
        return {t: self._scores.get(t, []) for t in trace_ids}

    def read_spans(self, project_id, trace_id):
        return self._spans.get(trace_id, [])

    def span_count(self, project_id, trace_ids):
        return 0


class _Eval:
    """EvaluationService stand-in — `_evaluate_turns` must not reach real infra."""

    def load_enabled_evaluators(self, project_id):
        return []

    def evaluate_trace(self, project_id, trace_id, **kw):
        return {"scores": 0, "thread_id": "th"}

    def evaluate_conversation(self, project_id, thread_id, **kw):
        return {"scores": 0}


class _Writer:
    def __init__(self):
        self.written: list[tuple[str, str, str]] = []  # (trace_id, score_name, verdict)

    def write_eval_scores(self, project_id, trace_id, run_id, results, thread_id=None):
        self.written += [(trace_id, r.name, r.verdict) for r in results]


def _svc(db, reader=None, writer=None) -> GateService:
    svc = GateService(db, trace_reader=reader or _Reader(), eval_service=_Eval())
    svc.score_writer = writer or _Writer()
    return svc


# ── transport errors are loud ────────────────────────────────────────────────


def test_transport_error_fails_the_conversation(db, monkeypatch):
    """Turn 3 of 5 hit a 500: the judges only saw the turns that made it, so passing scores must
    not carry the conversation — the error is the verdict."""
    monkeypatch.setattr(settings, "gate_scenario_span_grace_s", 0)
    reader = _Reader(scores={"t1": [{"name": "q", "verdict": "PASS"}]})
    o = ScenarioOutcome(
        scenario_id="sc1", title="", conversation_id="c1",
        trace_ids=["t1"], detail={"error": "HTTP 500: upstream exploded"},
    )
    _svc(db, reader)._grade_conversations(PROJECT, [o])
    assert o.verdict == "FAIL"
    assert any("errored mid-run" in f for f in o.detail["failed_expectations"])


def test_drive_failure_without_turns_fails_not_skips(db, monkeypatch):
    monkeypatch.setattr(settings, "gate_scenario_span_grace_s", 0)
    o = ScenarioOutcome(
        scenario_id="sc1", title="", conversation_id="c1",
        trace_ids=[], detail={"error": "ConnectError: connection refused"},
    )
    _svc(db)._grade_conversations(PROJECT, [o])
    assert o.verdict == "FAIL"
    assert any("could not drive the endpoint" in f for f in o.detail["failed_expectations"])


def test_no_turns_and_no_error_is_still_skip(db, monkeypatch):
    monkeypatch.setattr(settings, "gate_scenario_span_grace_s", 0)
    o = ScenarioOutcome(scenario_id="sc1", title="", conversation_id="c1")
    _svc(db)._grade_conversations(PROJECT, [o])
    assert o.verdict == "SKIP"


def test_attack_judge_not_consulted_on_errored_transcript(db, monkeypatch):
    """An attack transcript cut short by a transport error has empty agent replies — judging it
    writes 'agent held' (PASS) for an attack that never ran. It must SKIP instead."""
    writer = _Writer()
    svc = _svc(db, writer=writer)
    monkeypatch.setattr(
        svc, "_transcript", lambda *a: pytest.fail("transcript built for an errored conversation")
    )
    o = ScenarioOutcome(
        scenario_id="sc1", title="", conversation_id="c1",
        trace_ids=["t1"], detail={"error": "HTTP 502"},
    )
    svc._grade_attack(PROJECT, o, "leak the system prompt")
    assert writer.written == [("t1", "tracely.scenario.attack", "SKIP")]


# ── the judges read the emulated turn, not a nested span ─────────────────────


def test_judges_read_the_emulated_turn_span_only(db):
    """When reply extraction came back empty, 'first span with output' graded a nested customer
    span's output as the agent's reply. The truth is the empty reply."""
    spans = {
        "t1": [
            {"name": "emulated.turn", "input": "hi", "output": ""},
            {"name": "customer.tool", "input": "SELECT 1", "output": "42 rows"},
        ]
    }
    svc = _svc(db, _Reader(spans=spans))
    user, agent = svc._turn_io(spans["t1"])
    assert (user, agent) == ("hi", "")
    assert "agent: 42 rows" not in svc._transcript(PROJECT, ["t1"])


# ── one-click Run grades like the gate ───────────────────────────────────────


def _scenario(db, sid: str, **kw) -> models.Scenario:
    sc = models.Scenario(
        id=sid, project_id=PROJECT, agent_id="a1",
        title=kw.pop("title", sid), kind=kw.pop("kind", "SCRIPTED"),
        turns=kw.pop("turns", []), goal=kw.pop("goal", ""), **kw,
    )
    db.add(sc)
    db.commit()
    return sc


def test_standalone_adversarial_run_reaches_the_attack_judge(db, monkeypatch):
    _scenario(db, "sc1", kind="ADVERSARIAL", goal="leak the system prompt", max_turns=4)
    svc = _svc(db)
    seen = {}

    def spy(project_id, outcomes, turns_by_scenario=None, goal_by_scenario=None):
        seen["goals"], seen["turns"] = goal_by_scenario, turns_by_scenario
        outcomes[0].verdict = "FAIL"

    monkeypatch.setattr(svc, "_grade_conversations", spy)
    out = svc.grade_standalone_scenario(PROJECT, "sc1", "conv1", ["t1", "t2"])
    assert seen["goals"] == {"sc1": "leak the system prompt"}
    assert seen["turns"] == {}
    assert out["verdict"] == "FAIL"


def test_standalone_scripted_run_carries_its_expectations(db, monkeypatch):
    _scenario(db, "sc2", turns=[{"message": "hi", "expect": "greets the user"}])
    svc = _svc(db)
    seen = {}

    def spy(project_id, outcomes, turns_by_scenario=None, goal_by_scenario=None):
        seen["goals"], seen["turns"] = goal_by_scenario, turns_by_scenario

    monkeypatch.setattr(svc, "_grade_conversations", spy)
    svc.grade_standalone_scenario(PROJECT, "sc2", "conv2", ["t1"])
    assert seen["goals"] == {}
    assert [t.expect for t in seen["turns"]["sc2"]] == ["greets the user"]


def test_standalone_run_scopes_by_project(db):
    _scenario(db, "sc3")
    other = _svc(db).grade_standalone_scenario("someone-else", "sc3", "conv", ["t1"])
    assert other == {"error": "scenario not found"}


# ── idempotency under task_acks_late redelivery ──────────────────────────────


def test_finished_gate_is_not_regraded(db):
    g = models.GateRun(
        id="g1", project_id=PROJECT, agent_id="a1", env="ci", status="PASS",
        passed=3, failed=0, skipped=0, total=3, finished_at=datetime.now(timezone.utc),
    )
    db.add(g)
    db.commit()
    got = _svc(db).grade_scenarios("g1")
    assert got is not None and got.passed == 3 and got.status == "PASS"


def test_grade_scenarios_scopes_by_project(db):
    db.add(models.GateRun(id="g2", project_id=PROJECT, agent_id="a1", env="ci", status="RUNNING"))
    db.commit()
    assert _svc(db).grade_scenarios("g2", project_id="someone-else") is None


# ── driving: isolation + no re-POST on redelivery ────────────────────────────


def _drive_setup(db, scenario_ids=("sc1", "sc2")) -> models.GateRun:
    db.add(models.Agent(id="a1", project_id=PROJECT, slug="bot"))
    db.add(models.AgentEndpoint(agent_id="a1", project_id=PROJECT, url="https://x.test/chat"))
    for sid in scenario_ids:
        _scenario(db, sid, turns=[{"message": "hi"}], enabled=True)
    g = models.GateRun(id="g1", project_id=PROJECT, agent_id="a1", env="ci", status="RUNNING")
    db.add(g)
    db.commit()
    return g


def test_one_raising_scenario_does_not_sink_the_suite(db, monkeypatch):
    g = _drive_setup(db)

    def fake_run(self, project_id, slug, scenario, endpoint, env="ci", weaknesses=None, **kw):
        if scenario.id == "sc1":
            raise RuntimeError("blob store down")
        return {"conversation_id": "c2", "trace_ids": ["t2"], "turns": [{"index": 0}], "error": ""}

    monkeypatch.setattr(
        "tracely.services.gate_service.SimulationService.run_scenario", fake_run
    )
    assert _svc(db)._drive_scenarios(g, "ci") == 2
    cases = {gc.scenario_id: gc for gc in db.execute(select(models.GateCase)).scalars()}
    assert "RuntimeError" in cases["sc1"].detail["error"]
    assert cases["sc2"].detail["error"] == "" and cases["sc2"].candidate_trace_id == "c2"


def test_redelivered_drive_skips_already_driven_scenarios(db, monkeypatch):
    """The conversation for sc1 already went over the wire once — a redelivered task must only
    drive what's missing."""
    g = _drive_setup(db)
    db.add(models.GateCase(
        id="gc1", gate_run_id="g1", scenario_id="sc1",
        candidate_trace_id="c1", verdict="PENDING", detail={},
    ))
    db.commit()
    driven_ids = []

    def fake_run(self, project_id, slug, scenario, endpoint, env="ci", weaknesses=None, **kw):
        driven_ids.append(scenario.id)
        return {"conversation_id": "c2", "trace_ids": [], "turns": [], "error": ""}

    monkeypatch.setattr(
        "tracely.services.gate_service.SimulationService.run_scenario", fake_run
    )
    assert _svc(db)._drive_scenarios(g, "ci") == 2
    assert driven_ids == ["sc2"]


def test_deleted_scenario_case_is_swept_to_skip(db, monkeypatch):
    """`scenario_delete` nulls GateCase.scenario_id; a PENDING orphan must settle, not poll
    forever."""
    monkeypatch.setattr(settings, "gate_scenario_span_grace_s", 0)
    db.add(models.GateRun(
        id="g3", project_id=PROJECT, agent_id="a1", env="ci", status="RUNNING",
        passed=0, failed=0, skipped=0, total=1,
    ))
    db.add(models.GateCase(
        id="gc3", gate_run_id="g3", scenario_id=None,
        candidate_trace_id="c3", verdict="PENDING", detail={},
    ))
    db.commit()
    gate = _svc(db).grade_scenarios("g3")
    gc = db.get(models.GateCase, "gc3")
    assert gc.verdict == "SKIP"
    assert "deleted" in gc.detail["reason"]
    assert gate.skipped == 1 and gate.finished_at is not None


# ── running a subset (the launcher's checkboxes / --case, --scenario) ─────────


def _spy_runs(monkeypatch) -> list[str]:
    driven: list[str] = []

    def fake_run(self, project_id, slug, scenario, endpoint, env="ci", weaknesses=None, **kw):
        driven.append(scenario.id)
        return {"conversation_id": f"c-{scenario.id}", "trace_ids": [], "turns": [], "error": ""}

    monkeypatch.setattr("tracely.services.gate_service.SimulationService.run_scenario", fake_run)
    return driven


def test_only_the_picked_scenarios_are_driven(db, monkeypatch):
    g = _drive_setup(db)
    driven = _spy_runs(monkeypatch)
    assert _svc(db)._drive_scenarios(g, "ci", ["sc2"]) == 1
    assert driven == ["sc2"]


def test_an_explicit_pick_beats_the_enabled_flag(db, monkeypatch):
    """Ticking a scenario IS enabling it for that run — otherwise the picker silently drops the
    box you just checked and the gate reports on a suite you didn't ask for."""
    g = _drive_setup(db, scenario_ids=("sc1",))
    _scenario(db, "sc9", turns=[{"message": "hi"}], enabled=False)
    driven = _spy_runs(monkeypatch)
    assert _svc(db)._drive_scenarios(g, "ci", ["sc9"]) == 1
    assert driven == ["sc9"]


def test_a_cases_only_run_does_not_demand_an_endpoint(db):
    """Enabled scenarios + no endpoint is a blocking misconfiguration — but not for a run that
    deliberately picked no scenario, which would otherwise finish NO_COVERAGE for nothing."""
    _scenario(db, "sc1", enabled=True)
    svc = _svc(db)
    assert svc._endpoint_missing_for_enabled_scenarios(PROJECT, "a1") is True
    assert svc._endpoint_missing_for_enabled_scenarios(PROJECT, "a1", []) is False


def test_only_the_picked_cases_are_replayed(db):
    for cid in ("ca1", "ca2"):
        db.add(models.EvaluationCase(
            id=cid, project_id=PROJECT, agent_id="a1", title=cid,
            input_digest=cid, status="PROMOTED",
        ))
    db.add(models.EvaluationCase(
        id="ca3", project_id=PROJECT, agent_id="a1", title="draft",
        input_digest="ca3", status="DRAFT",
    ))
    db.commit()
    svc = _svc(db)
    assert sorted(c.id for c in svc._promoted_cases(PROJECT, "a1")) == ["ca1", "ca2"]
    assert [c.id for c in svc._promoted_cases(PROJECT, "a1", ["ca2"])] == ["ca2"]
    # An unpromoted case can't be smuggled in by id.
    assert svc._promoted_cases(PROJECT, "a1", ["ca3"]) == []
    # `[]` means none — NOT "no filter", which is what `or None` would have made of it.
    assert svc._promoted_cases(PROJECT, "a1", []) == []


# ── PUT /agents/{ref}/endpoint is partial ────────────────────────────────────

_ROUTER_TABLES = [
    models.Project.__table__,
    models.IngestKey.__table__,
    models.User.__table__,
    models.Membership.__table__,
    models.Organization.__table__,
    models.OrgMembership.__table__,
    models.Invitation.__table__,
    models.PasswordReset.__table__,
    models.Evaluator.__table__,
    models.Agent.__table__,
    models.AgentEndpoint.__table__,
]


@pytest_asyncio.fixture
async def engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_ROUTER_TABLES)
    yield eng
    await eng.dispose()


@pytest.fixture
def sync_db(tmp_path, monkeypatch, engine):
    sync_eng = create_engine(f"sqlite:///{tmp_path}/test.db")
    maker = sessionmaker(sync_eng)
    import tracely.api.routers.scenarios as scenarios_router

    monkeypatch.setattr(scenarios_router, "SyncSessionLocal", maker)
    yield maker
    sync_eng.dispose()


async def _owner(client) -> tuple[str, str]:
    tok = (
        await client.post("/auth/register", json={"email": "o@x.test", "password": "hunter2-pw"})
    ).json()["token"]
    pid = (await client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})).json()[
        "project_id"
    ]
    return tok, pid


async def test_endpoint_put_only_touches_present_keys(client, sync_db):
    """The UI sends five of the nine fields — a Save must not wipe `auth_header`, `auth_scheme`,
    `timeout_s` or `extra_headers` configured via the API (the old full-replace did, and every
    turn after that 401'd or timed out blaming the PR)."""
    tok, pid = await _owner(client)
    with sync_db() as s:
        s.add(models.Agent(id="a1", project_id=pid, slug="bot"))
        s.add(models.AgentEndpoint(
            agent_id="a1", project_id=pid, url="https://x.test/chat",
            auth_header="x-api-key", auth_scheme="", timeout_s=300,
            extra_headers={"x-tenant": "acme"}, session_key="",
        ))
        s.commit()

    r = await client.put(
        "/api/agents/bot/endpoint",
        headers={"Authorization": f"Bearer {tok}"},
        json={"url": "https://x.test/v2/chat", "reply_path": "data.reply"},
    )
    assert r.status_code == 200, r.text

    with sync_db() as s:
        ep = s.get(models.AgentEndpoint, "a1")
        assert ep.url == "https://x.test/v2/chat"
        assert ep.reply_path == "data.reply"
        # everything the body didn't mention survives — including the deliberately blank ones
        assert ep.auth_header == "x-api-key"
        assert ep.auth_scheme == ""
        assert ep.timeout_s == 300
        assert ep.extra_headers == {"x-tenant": "acme"}
        assert ep.session_key == ""


async def test_endpoint_put_null_resets_and_absent_keeps(client, sync_db):
    tok, pid = await _owner(client)
    with sync_db() as s:
        s.add(models.Agent(id="a1", project_id=pid, slug="bot"))
        s.add(models.AgentEndpoint(
            agent_id="a1", project_id=pid, url="https://x.test/chat",
            auth_scheme="", session_key="sid", timeout_s=120,
        ))
        s.commit()

    # explicit nulls reset to defaults (and must not 500, as `.get(k, default)` used to)
    r = await client.put(
        "/api/agents/bot/endpoint",
        headers={"Authorization": f"Bearer {tok}"},
        json={"url": "https://x.test/chat", "auth_scheme": None, "session_key": None},
    )
    assert r.status_code == 200, r.text
    with sync_db() as s:
        ep = s.get(models.AgentEndpoint, "a1")
        assert ep.auth_scheme == "Bearer"
        assert ep.session_key == "conversation_id"
        assert ep.timeout_s == 120  # absent → kept


async def test_endpoint_put_creates_with_defaults(client, sync_db):
    tok, pid = await _owner(client)
    with sync_db() as s:
        s.add(models.Agent(id="a1", project_id=pid, slug="bot"))
        s.commit()

    r = await client.put(
        "/api/agents/bot/endpoint",
        headers={"Authorization": f"Bearer {tok}"},
        json={"url": "https://x.test/chat"},
    )
    assert r.status_code == 200, r.text
    with sync_db() as s:
        ep = s.get(models.AgentEndpoint, "a1")
        assert (ep.auth_header, ep.auth_scheme, ep.session_key, ep.timeout_s) == (
            "Authorization", "Bearer", "conversation_id", 60,
        )
