"""Emulated conversations: OTLP emission, reply extraction, and gate aggregation."""

from __future__ import annotations

import json
import os
from contextlib import nullcontext

import httpx
import pytest

from tracely.domain.simulation import (
    ATTACK_SCORE,
    EXPECT_SCORE,
    TOOLS_SCORE,
    ScenarioOutcome,
    attack_result,
    attack_skipped,
    Turn,
    check_tools,
    conversation_verdict,
    gate_verdict,
    normalize_turns,
    serialize_turns,
    turn_payload,
    user_text,
)
from tracely.otel import parse_otlp_traces_json
from tracely.services.simulation_service import SimulationService


# ── emission ──────────────────────────────────────────────────────────────────


def _payload(**over):
    kw = dict(
        trace_id=os.urandom(16),
        span_id=os.urandom(8),
        agent_slug="planner",
        conversation_id="conv1",
        turn_index=0,
        user_message="where is my order?",
        agent_reply="let me check",
        env="ci",
        start_ns=1_000,
        end_ns=2_000,
    )
    kw.update(over)
    return kw


def test_turn_payload_ids_survive_the_json_parser():
    """The whole correlation design rests on the trace id we mint being the id the trace lands
    under. protobuf's JSON mapping decodes `bytes` as base64 and does NOT reject hex — it would
    silently produce a 24-byte id nothing can look up — so this pins the round-trip."""
    kw = _payload()
    events = parse_otlp_traces_json(json.dumps(turn_payload(**kw)).encode(), "p1")

    assert len(events) == 1
    assert events[0]["trace_id"] == kw["trace_id"].hex()
    assert events[0]["span_id"] == kw["span_id"].hex()


def test_turn_payload_carries_the_gating_attributes():
    ev = parse_otlp_traces_json(json.dumps(turn_payload(**_payload(turn_index=3))).encode(), "p1")[0]

    assert ev["env"] == "ci"  # the gating axis
    assert ev["agent_slug"] == "planner"
    assert ev["conversation_id"] == "conv1"
    assert ev["turn_index"] == 3
    assert ev["is_app_root"] is True
    assert ev["input"] == "where is my order?"
    assert ev["output"] == "let me check"
    assert ev["level"] == "DEFAULT"


def test_turn_payload_marks_a_failed_call_as_an_error_span():
    """A dead endpoint has to become a graded ERROR turn, not a missing conversation."""
    ev = parse_otlp_traces_json(
        json.dumps(turn_payload(**_payload(agent_reply="", error="HTTP 500: boom"))).encode(), "p1"
    )[0]

    assert ev["level"] == "ERROR"
    assert "boom" in ev["status_message"]


# ── reply extraction ──────────────────────────────────────────────────────────


def _resp(payload, text=None):
    if text is not None:
        return httpx.Response(200, text=text)
    return httpx.Response(200, json=payload)


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"choices": [{"message": {"content": "hi"}}]}, "hi"),  # OpenAI-compatible
        ({"reply": "hi"}, "hi"),
        ({"response": "hi"}, "hi"),
        ({"output": "hi"}, "hi"),
        ("hi", "hi"),  # bare JSON string
    ],
)
def test_extract_reply_handles_common_shapes_without_config(body, expected):
    assert SimulationService._extract_reply(_resp(body), "") == expected


def test_extract_reply_honours_an_explicit_path():
    body = {"data": {"turns": [{"text": "first"}, {"text": "second"}]}}
    assert SimulationService._extract_reply(_resp(body), "data.turns.1.text") == "second"


def test_extract_reply_falls_back_to_plain_text():
    assert SimulationService._extract_reply(_resp(None, text="just words"), "") == "just words"


def test_extract_reply_is_empty_when_an_explicit_path_misses():
    """An explicit path that misses must not silently fall through to some other key — the
    operator said where the reply lives, and a wrong reply grades the wrong thing."""
    assert SimulationService._extract_reply(_resp({"reply": "hi"}), "data.text") == ""


# ── driving a conversation ────────────────────────────────────────────────────


class _FakeScenario:
    id, kind, title, goal, max_turns = "sc1", "SCRIPTED", "Refund flow", "", 6
    turns = [
        {"message": "hi", "expect": "", "tools": []},
        {"message": "where is my refund?", "expect": "offers a refund", "tools": ["issue_refund"]},
        {"message": "thanks", "expect": "", "tools": []},
    ]


class _FakeEndpoint:
    url = "https://agent.example.com/chat"
    auth_header, auth_scheme, token_encrypted = "Authorization", "Bearer", ""
    extra_headers, extra_body, reply_path = {}, {}, ""
    session_key, timeout_s = "conversation_id", 30


def _drive(monkeypatch, handler):
    """Run a scripted scenario against `handler`, capturing what would be ingested.

    Patches the blob write and the inline ingest — the turn is persisted blob-first and mapped
    into ClickHouse in-process (NOT via Celery), because the gate task already owns the worker's
    only slot under `--pool=solo`.
    """
    emitted: list[dict] = []
    monkeypatch.setattr(
        "tracely.services.simulation_service.blobstore.put_blob",
        lambda key, raw, content_type: emitted.append({"key": key, "payload": json.loads(raw)}),
    )
    monkeypatch.setattr(
        "tracely.services.simulation_service.IngestionService.process_blob",
        lambda self, pid, key, ct: {"events": 1},
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = SimulationService(client=client).run_scenario(
        "p1", "planner", _FakeScenario(), _FakeEndpoint(), env="ci"
    )
    return result, emitted


def test_driving_a_scripted_conversation_emits_one_trace_per_turn(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"reply": f"answer {len(seen)}"})

    result, emitted = _drive(monkeypatch, handler)

    assert len(seen) == 3  # one POST per scripted turn
    assert len(emitted) == 3
    assert [t["output"] for t in result["turns"]] == ["answer 1", "answer 2", "answer 3"]
    # Every turn shares the conversation, so the turns land as one thread.
    convs = {
        a["value"]["stringValue"]
        for e in emitted
        for a in e["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
        if a["key"] == "tracely.conversation.id"
    }
    assert convs == {result["conversation_id"]}
    assert len(set(result["trace_ids"])) == 3


def test_turns_are_ingested_inline_before_the_driver_returns(monkeypatch):
    """The gate task holds the worker's only slot under `--pool=solo --concurrency=1`. If turns
    were ingested by enqueuing a Celery task, that task could not run until the gate returned,
    while the gate waited for it — a hard deadlock. Every turn must be mapped in-process."""
    ingested: list[str] = []
    monkeypatch.setattr(
        "tracely.services.simulation_service.blobstore.put_blob", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "tracely.services.simulation_service.IngestionService.process_blob",
        lambda self, pid, key, ct: ingested.append(key),
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))
    )

    result = SimulationService(client=client).run_scenario(
        "p1", "planner", _FakeScenario(), _FakeEndpoint(), env="ci"
    )

    assert len(ingested) == len(result["trace_ids"]) == 3


def test_each_turn_sends_the_trace_id_it_will_be_stored_under(monkeypatch):
    """The correlation contract: the `traceparent` we send must name the same trace the turn is
    ingested as, or the customer's own spans nest under a trace nobody is grading."""
    seen: list[httpx.Request] = []
    result, _ = _drive(
        monkeypatch,
        lambda r: (seen.append(r), httpx.Response(200, json={"reply": "ok"}))[1],
    )

    sent = [r.headers["traceparent"].split("-")[1] for r in seen]
    assert sent == result["trace_ids"]


def test_conversation_history_accumulates_across_turns(monkeypatch):
    bodies: list[dict] = []
    _drive(
        monkeypatch,
        lambda r: (
            bodies.append(json.loads(r.content)),
            httpx.Response(200, json={"reply": "ok"}),
        )[1],
    )

    # turn 1 sends 1 message, turn 2 sends user+assistant+user, turn 3 sends five.
    assert [len(b["messages"]) for b in bodies] == [1, 3, 5]
    assert bodies[-1]["messages"][-1] == {"role": "user", "content": "thanks"}
    assert {b["conversation_id"] for b in bodies} == {bodies[0]["conversation_id"]}


def test_a_failing_endpoint_stops_the_conversation_and_records_an_error(monkeypatch):
    """A 500 on turn 1 shouldn't spend three turns talking to a broken service — but it must
    still emit the turn, so the run is a graded failure rather than a missing conversation."""
    result, emitted = _drive(monkeypatch, lambda r: httpx.Response(500, text="boom"))

    assert len(emitted) == 1
    assert "HTTP 500" in result["error"]
    span = emitted[0]["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["status"]["code"] == 2


def test_a_transport_error_is_a_graded_turn_not_a_crash(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route to host")

    result, emitted = _drive(monkeypatch, handler)

    assert len(emitted) == 1
    assert "ConnectError" in result["error"]


# ── conversation verdict ──────────────────────────────────────────────────────


def test_conversation_fails_if_any_turn_fails():
    pooled = [{"name": "correctness", "verdict": "PASS"}, {"name": "correctness", "verdict": "FAIL"}]
    assert conversation_verdict(pooled, advisory=[]) == "FAIL"


def test_advisory_fail_does_not_sink_the_conversation():
    pooled = [{"name": "tracely.run.quality", "verdict": "FAIL"}]
    assert conversation_verdict(pooled, advisory=["tracely.run.quality"]) == "PASS"


def test_ungraded_conversation_is_not_a_pass():
    assert conversation_verdict([], advisory=[]) == "UNGRADED"


# ── turn shapes + expectations ────────────────────────────────────────────────


def test_legacy_string_turns_still_parse():
    """Scenarios authored before expectations existed are plain strings on a JSON column. They
    must keep working with no data migration."""
    turns = normalize_turns(["hi", "where is my refund?"])

    assert [t.message for t in turns] == ["hi", "where is my refund?"]
    assert all(not t.has_expectations for t in turns)


def test_turns_with_expectations_parse():
    turns = normalize_turns([
        {"message": "refund me", "expect": "offers a refund", "tools": ["issue_refund", ""]},
        {"message": "thanks"},
    ])

    assert turns[0].tools == ("issue_refund",)  # blank tool names dropped
    assert turns[0].has_expectations
    assert not turns[1].has_expectations


def test_malformed_turns_are_skipped_not_raised():
    """This parses user-authored JSON off a JSON column — one bad entry must not take down a
    whole gate run."""
    assert normalize_turns(["ok", "", {"expect": "no message"}, 42, None]) == [Turn(message="ok")]
    assert normalize_turns("not a list") == []


def test_turns_round_trip_through_serialization():
    turns = normalize_turns(["hi"])
    assert normalize_turns(serialize_turns(turns)) == turns


def test_tool_expectation_passes_when_the_tool_was_called():
    r = check_tools(("issue_refund",), ["lookup_order", "issue_refund"], agent_spans_present=True)
    assert r.verdict == "PASS"


def test_tool_expectation_fails_with_the_missing_tool_named():
    r = check_tools(("issue_refund",), ["lookup_order"], agent_spans_present=True)
    assert r.verdict == "FAIL"
    assert "issue_refund" in r.comment


def test_tool_expectation_skips_when_the_agents_spans_never_arrived():
    """Without the customer's spans we are structurally blind to tool calls. FAIL would blame the
    author for something they can't fix; SKIP is the only true answer."""
    r = check_tools(("issue_refund",), [], agent_spans_present=False)
    assert r.verdict == "SKIP"
    assert "traceparent" in r.comment


def test_a_successful_attack_is_a_gate_failure():
    """Inverted polarity, and the reason it exists: an ADVERSARIAL scenario has no authored turns,
    so before this its `goal` only generated the attack and nothing judged the outcome. Verified
    live — an agent that leaked its system prompt on every turn reported PASS."""
    r = attack_result(True, "the agent pasted its full system prompt including the override code")

    assert r.name == ATTACK_SCORE
    assert r.verdict == "FAIL"
    assert "attack succeeded" in r.comment


def test_a_defended_agent_passes():
    r = attack_result(False, "the agent refused every framing")
    assert r.verdict == "PASS"
    assert "agent held" in r.comment


def test_an_unjudged_attack_is_skipped_not_passed():
    """No LLM key must not read as 'the agent defended itself'."""
    assert attack_skipped("no LLM key configured").verdict == "SKIP"


def test_an_attack_score_sinks_the_conversation():
    pooled = [{"name": "correctness", "verdict": "PASS"}, {"name": ATTACK_SCORE, "verdict": "FAIL"}]
    assert conversation_verdict(pooled, advisory=[]) == "FAIL"


def test_the_gate_drives_and_grades_in_two_separate_tasks():
    """The agent's own spans arrive as ordinary OTLP, so their ingest is a Celery task — and under
    `--pool=solo --concurrency=1` those cannot run while the gate holds the only slot. Driving and
    grading therefore MUST be separate tasks, or every tool expectation SKIPs on a trace that only
    contains Tracely's own turn spans (verified live: the agent's spans landed 5s after grading).
    """
    from tracely.workers import tasks

    assert hasattr(tasks, "run_scenario_gate_task")
    assert hasattr(tasks, "grade_scenario_gate_task")
    assert tasks.run_scenario_gate_task.name != tasks.grade_scenario_gate_task.name


def test_a_conversation_whose_only_scores_are_skips_is_ungraded():
    """The trap this guards: `rollup_verdict` reads any score as evidence of grading, so skipped
    expectations alone would have come back PASS having checked nothing."""
    skips = [
        {"name": TOOLS_SCORE, "verdict": "SKIP"},
        {"name": EXPECT_SCORE, "verdict": "SKIP"},
    ]
    assert conversation_verdict(skips, advisory=[]) == "UNGRADED"


def test_a_skip_alongside_a_real_pass_still_passes():
    mixed = [{"name": TOOLS_SCORE, "verdict": "SKIP"}, {"name": "correctness", "verdict": "PASS"}]
    assert conversation_verdict(mixed, advisory=[]) == "PASS"


def test_a_failing_expectation_sinks_the_conversation():
    mixed = [{"name": "correctness", "verdict": "PASS"}, {"name": EXPECT_SCORE, "verdict": "FAIL"}]
    assert conversation_verdict(mixed, advisory=[]) == "FAIL"


def test_extra_body_is_merged_but_cannot_clobber_the_conversation(monkeypatch):
    """`extra_body` carries tenant_id / locale / channel. It must not be able to overwrite
    `messages` or the session key and break the conversation."""
    bodies: list[dict] = []

    class _EpWithBody(_FakeEndpoint):
        extra_body = {"tenant_id": "acme", "locale": "fr", "messages": "hijacked"}

    monkeypatch.setattr(
        "tracely.services.simulation_service.blobstore.put_blob", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "tracely.services.simulation_service.IngestionService.process_blob",
        lambda self, pid, key, ct: None,
    )
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: (
                bodies.append(json.loads(r.content)),
                httpx.Response(200, json={"reply": "ok"}),
            )[1]
        )
    )

    SimulationService(client=client).run_scenario(
        "p1", "planner", _FakeScenario(), _EpWithBody(), env="ci"
    )

    assert bodies[0]["tenant_id"] == "acme"
    assert bodies[0]["locale"] == "fr"
    assert isinstance(bodies[0]["messages"], list)  # not "hijacked"
    assert bodies[0]["conversation_id"]


# ── importing a real thread ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "recorded,expected",
    [
        ("where is my refund?", "where is my refund?"),  # already plain
        ('{"prompt": "where is my refund?"}', "where is my refund?"),
        ('{"input": "hi"}', "hi"),
        ('{"query": "hi"}', "hi"),
        ('"just a json string"', "just a json string"),
        # a chat envelope replays the LAST user turn — that's what this trace answered
        ('{"messages": [{"role":"user","content":"a"},{"role":"assistant","content":"b"},'
         '{"role":"user","content":"c"}]}', "c"),
    ],
)
def test_user_text_unwraps_recorded_envelopes(recorded, expected):
    assert user_text(recorded) == expected


def test_user_text_leaves_unrecognised_json_alone():
    """Better to import something the operator can edit than to guess wrong and silently replay
    the wrong message."""
    blob = '{"a": 1, "b": 2}'
    assert user_text(blob) == blob
    assert user_text("{not json at all") == "{not json at all"


# ── gate aggregation ──────────────────────────────────────────────────────────


def _outcome(verdict: str, n: int = 1) -> list[ScenarioOutcome]:
    return [
        ScenarioOutcome(
            scenario_id=f"s{i}", title=f"s{i}", conversation_id=f"c{i}",
            trace_ids=["t"], verdict=verdict,
        )
        for i in range(n)
    ]


def test_all_pass_is_green():
    status, summary = gate_verdict(_outcome("PASS", 3))
    assert status == "PASS"
    assert summary["pass_rate"] == 1.0


def test_one_failure_blocks_at_the_default_rate():
    assert gate_verdict(_outcome("PASS", 3) + _outcome("FAIL"))[0] == "FAIL"


def test_a_lower_threshold_tolerates_some_failures():
    """Adversarial suites land a few probes by design; 9/10 must clear min_pass_rate=0.9 despite
    9/10 being 0.8999999999999999 in binary floating point."""
    outcomes = _outcome("PASS", 9) + _outcome("FAIL")
    assert gate_verdict(outcomes, min_pass_rate=0.9)[0] == "PASS"
    assert gate_verdict(outcomes, min_pass_rate=0.95)[0] == "FAIL"


def test_ungraded_counts_against_the_rate_and_never_passes():
    assert gate_verdict(_outcome("PASS", 1) + _outcome("UNGRADED", 1))[0] == "FAIL"


def test_all_ungraded_is_no_coverage_not_pass():
    """The false-green trap: conversations ran, nothing scored them. Must block."""
    status, summary = gate_verdict(_outcome("UNGRADED", 3))
    assert status == "NO_COVERAGE"
    assert summary["ungraded"] == 3


def test_all_skipped_is_no_coverage():
    assert gate_verdict(_outcome("SKIP", 2))[0] == "NO_COVERAGE"


def test_no_scenarios_configured_is_not_a_failure():
    """A project that only uses replay-style gating must not be blocked by an empty suite."""
    assert gate_verdict([])[0] == "PASS"


# ── the no-LLM path ───────────────────────────────────────────────────────────


class _StubTurn:
    """Minimal Turn stand-in — a turn whose only expectation is free-text, so grading it needs
    the judge and nothing else."""

    def __init__(self, message="where is my refund?", expect="offers a refund"):
        self.message, self.expect, self.tools = message, expect, ()
        self.has_expectations = True


def _gate_service():
    from tracely.services.gate_service import GateService

    return GateService.__new__(GateService)  # no DB/ClickHouse — only _judge_expectation is used


def test_expectation_without_an_llm_key_is_skipped_never_passed(monkeypatch):
    """The false-green class that has already bitten twice here. With no LLM configured the judge
    cannot run, and an unjudgeable expectation must NOT read as a met one — it has to be SKIP, so
    the conversation lands UNGRADED and counts against the pass rate."""
    monkeypatch.setattr("tracely.services.gate_service.llm_enabled", lambda: False)
    monkeypatch.setattr(
        "tracely.services.gate_service.use_project_key", lambda _pid: nullcontext()
    )

    result = _gate_service()._judge_expectation(
        "p1", _StubTurn(), [{"output": "no idea, sorry"}], 0, _outcome("SKIP")[0]
    )

    assert result.verdict == "SKIP"
    assert result.verdict != "PASS"
    assert "llm" in result.comment.lower()
    assert result.value is None, "a skipped expectation must not contribute a numeric score"


def test_a_judge_that_errors_is_skipped_not_passed(monkeypatch):
    """Same invariant for a judge that blows up mid-call — a transport error is not a pass."""
    monkeypatch.setattr("tracely.services.gate_service.llm_enabled", lambda: True)
    monkeypatch.setattr(
        "tracely.services.gate_service.use_project_key", lambda _pid: nullcontext()
    )

    def boom(*a, **k):
        raise RuntimeError("judge exploded")

    monkeypatch.setattr("tracely.services.gate_service.run_structured_agent", boom)

    result = _gate_service()._judge_expectation(
        "p1", _StubTurn(), [{"output": "hello"}], 0, _outcome("SKIP")[0]
    )

    assert result.verdict == "SKIP"
    assert "judge exploded" in result.comment


def test_a_skipped_expectation_leaves_the_conversation_ungraded():
    """End of the chain: a SKIP score is not a PASS score, so pooling only SKIPs yields UNGRADED,
    which `gate_verdict` then refuses to call green."""
    pooled = [{"name": "tracely.scenario.expect", "verdict": "SKIP"}]
    assert conversation_verdict(pooled, advisory=[]) == "UNGRADED"
    assert gate_verdict(_outcome("UNGRADED", 1))[0] == "NO_COVERAGE"


# ── naming what failed ────────────────────────────────────────────────────────


def test_failing_evaluator_names_are_collected_for_the_gate_detail():
    """A conversation can fail purely on the project's evaluators. Without these names the gate
    row and the PR comment show a red verdict and no cause at all."""
    from tracely.services.gate_service import _failing_score_names

    pooled = [
        {"name": "correctness", "verdict": "FAIL", "comment": "invented a refund policy"},
        {"name": "tone", "verdict": "PASS", "comment": ""},
    ]
    assert _failing_score_names(pooled, advisory=[]) == [
        "correctness: invented a refund policy"
    ]


def test_advisory_failures_are_not_listed_as_the_cause():
    """An advisory FAIL doesn't flip the verdict, so naming it sends people chasing the wrong
    thing."""
    from tracely.services.gate_service import _failing_score_names

    pooled = [{"name": "tracely.run.quality", "verdict": "FAIL", "comment": "meh"}]
    assert _failing_score_names(pooled, advisory=["tracely.run.quality"]) == []


def test_the_same_evaluator_failing_on_many_turns_is_listed_once():
    from tracely.services.gate_service import _failing_score_names

    pooled = [{"name": "correctness", "verdict": "FAIL", "comment": "wrong"}] * 4
    assert len(_failing_score_names(pooled, advisory=[])) == 1


def test_authored_expectations_are_not_repeated_as_evaluator_failures():
    """`failed_expectations` already reports these, with the turn number. Listing them again as
    generic evaluator failures made the PR comment print every tool failure twice."""
    from tracely.services.gate_service import _failing_score_names

    pooled = [
        {"name": TOOLS_SCORE, "verdict": "FAIL", "comment": "expected escalate_to_human"},
        {"name": EXPECT_SCORE, "verdict": "FAIL", "comment": "no refund offered"},
        {"name": "correctness", "verdict": "FAIL", "comment": "wrong total"},
    ]
    assert _failing_score_names(pooled, advisory=[]) == ["correctness: wrong total"]


# ── misconfiguration must block ───────────────────────────────────────────────


class _StubSession:
    """Minimal session: `execute(...).first()` answers "are there enabled scenarios", `get`
    answers "is there an endpoint"."""

    def __init__(self, has_scenarios: bool, has_endpoint: bool):
        self._has_scenarios, self._has_endpoint = has_scenarios, has_endpoint

    def execute(self, _stmt):
        has = self._has_scenarios
        return type("R", (), {"first": staticmethod(lambda: ("sc1",) if has else None)})()

    def get(self, _model, _pk):
        return object() if self._has_endpoint else None


@pytest.mark.parametrize(
    "has_scenarios,has_endpoint,blocked",
    [
        (True, False, True),    # the bug: an enabled suite with nowhere to send it
        (True, True, False),    # normal
        (False, False, False),  # not using scenarios at all — must NOT be blocked
        (False, True, False),
    ],
)
def test_enabled_scenarios_without_an_endpoint_are_a_blocking_misconfiguration(
    has_scenarios, has_endpoint, blocked
):
    """Shipped green once: an enabled scenario plus a missing endpoint drove zero conversations
    and the gate reported PASS — a merge sailing through having tested nothing, which is the exact
    failure this feature exists to prevent. An agent with NO scenarios is a different thing and
    must still pass."""
    from tracely.services.gate_service import GateService

    svc = GateService.__new__(GateService)
    svc.session = _StubSession(has_scenarios, has_endpoint)

    assert svc._endpoint_missing_for_enabled_scenarios("p1", "a1") is blocked
