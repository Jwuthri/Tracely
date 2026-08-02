"""The multi-level / multi-output-type LLM judge, with the LangChain agent layer stubbed.

The judge calls `provider.run_structured_agent` (create_agent + response_format) for typed
outputs and `provider.run_text_agent` for the free-form `json` output type — tests patch those
two provider functions and exercise everything above them.
"""

from __future__ import annotations

import json

import pytest

from tracely.config import settings
from tracely.domain.evaluation.evaluators.base import CONVERSATION, RUN, SPAN
from tracely.domain.evaluation.evaluators.llm_judge import LLMJudgeEvaluator
from tracely.domain.evaluation.results import RunContext
from tracely.domain.traces.spans import root_span
from tracely.infrastructure.llm import provider


def _span(**kw) -> dict:
    base = {
        "span_id": "s1", "parent_span_id": "", "type": "GENERATION", "name": "llm",
        "level": "DEFAULT", "status_message": "", "start_time": None, "end_time": None,
        "agent_id": "agent", "agent_run_id": "run-1", "turn_id": "", "step_id": "",
        "model_id": "m", "input": "hi", "output": "hello", "tool_call_names": [],
        "trace_id": "t1", "is_app_root": 1, "conversation_id": "",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def judge_key(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")


def _judge(level: str) -> LLMJudgeEvaluator:
    ev = LLMJudgeEvaluator()
    ev.level = level
    return ev


def _ctx(spans: list[dict], thread_id: str = "") -> RunContext:
    from tracely.domain.traces.spans import root_span

    return RunContext("p", "t1", "run-1", spans, root_span(spans), thread_id=thread_id)


def _stub_structured(monkeypatch, fields: dict, prompts: list | None = None, systems: list | None = None):
    """Patch run_structured_agent to build the requested response_format with canned fields."""

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0, on_usage=None):
        if prompts is not None:
            prompts.append(prompt)
        if systems is not None:
            systems.append(system_prompt)
        return response_format(**fields)

    monkeypatch.setattr(provider, "run_structured_agent", fake)


def test_trace_level_score_threshold(monkeypatch):
    systems: list = []
    _stub_structured(monkeypatch, {"score": 0.4, "reason": "meh"}, systems=systems)
    results = _judge(RUN).run(_ctx([_span()]), {"prompt": "Grade.", "threshold": 0.6})
    assert len(results) == 1
    r = results[0]
    assert (r.verdict, r.data_type, r.value, r.comment) == ("FAIL", "NUMERIC", 0.4, "meh")
    # the rubric rides as the agent's system prompt
    assert systems == ["Grade."]

    _stub_structured(monkeypatch, {"score": 0.9, "reason": "good"})
    assert _judge(RUN).run(_ctx([_span()]), {"threshold": 0.6})[0].verdict == "PASS"


def test_boolean_output(monkeypatch):
    _stub_structured(monkeypatch, {"passed": False, "reason": "leaked"})
    r = _judge(RUN).run(_ctx([_span()]), {"prompt": "PII?", "output_type": "boolean"})[0]
    assert (r.verdict, r.data_type, r.value) == ("FAIL", "BOOLEAN", 0.0)


def test_category_output(monkeypatch):
    _stub_structured(monkeypatch, {"category": "complaint", "reason": "angry"})
    config = {"output_type": "category", "categories": ["question", "complaint"]}
    r = _judge(RUN).run(_ctx([_span()]), config)[0]
    assert (r.data_type, r.string_value, r.verdict) == ("CATEGORICAL", "complaint", "")
    # with fail_categories configured the verdict kicks in
    r2 = _judge(RUN).run(_ctx([_span()]), {**config, "fail_categories": ["complaint"]})[0]
    assert r2.verdict == "FAIL"


def test_category_schema_rejects_unknown_label(monkeypatch):
    """The dynamic Literal schema only admits the configured categories — a stray label is a
    validation error, which the judge swallows as a skipped grade."""
    _stub_structured(monkeypatch, {"category": "nonsense", "reason": ""})
    config = {"output_type": "category", "categories": ["question", "complaint"]}
    assert _judge(RUN).run(_ctx([_span()]), config) == []


def test_text_output(monkeypatch):
    _stub_structured(monkeypatch, {"text": "concise summary"})
    r = _judge(RUN).run(_ctx([_span()]), {"output_type": "text"})[0]
    assert (r.data_type, r.string_value, r.verdict) == ("TEXT", "concise summary", "")


def test_span_level_grades_each_step(monkeypatch):
    prompts: list[str] = []
    _stub_structured(monkeypatch, {"score": 1.0, "reason": "fine"}, prompts=prompts)
    spans = [
        _span(span_id="root", type="AGENT"),
        _span(span_id="tool-1", type="TOOL", name="lookup", parent_span_id="root"),
        _span(span_id="gen-1", type="GENERATION", parent_span_id="root"),
        _span(span_id="chain-1", type="CHAIN", parent_span_id="root"),
    ]
    results = _judge(SPAN).run(_ctx(spans), {"prompt": "Grade the step."})
    # a step is every event INSIDE the message — the message root is the message, not a step
    assert [r.target_span_id for r in results] == ["tool-1", "gen-1", "chain-1"]
    assert all(r.level == SPAN for r in results)
    assert "Step 1 of 3" in prompts[0]

    # span_types narrows the candidates
    only_tools = _judge(SPAN).run(_ctx(spans), {"span_types": ["TOOL"]})
    assert [r.target_span_id for r in only_tools] == ["tool-1"]


def test_conversation_level_builds_transcript(monkeypatch):
    prompts: list[str] = []
    _stub_structured(monkeypatch, {"score": 0.2, "reason": "goal missed"}, prompts=prompts)
    spans = [
        _span(trace_id="t1", span_id="a", input="book a flight", output="which date?", conversation_id="th-9"),
        _span(trace_id="t2", span_id="b", input="tomorrow", output="booked!", conversation_id="th-9"),
    ]
    results = _judge(CONVERSATION).run(_ctx(spans, thread_id="th-9"), {"threshold": 0.6})
    assert len(results) == 1
    assert results[0].level == CONVERSATION
    assert results[0].verdict == "FAIL"
    assert "Turn 1 — user: book a flight" in prompts[0]
    assert "Turn 2 — agent: booked!" in prompts[0]
    assert "2 turns" in prompts[0]


def test_number_output(monkeypatch):
    _stub_structured(monkeypatch, {"value": 42.5, "reason": "counted"})
    r = _judge(RUN).run(_ctx([_span()]), {"output_type": "number"})[0]
    assert (r.data_type, r.value, r.verdict, r.comment) == ("NUMERIC", 42.5, "", "counted")
    # threshold turns it into a pass/fail check
    r2 = _judge(RUN).run(_ctx([_span()]), {"output_type": "number", "threshold": 50})[0]
    assert r2.verdict == "FAIL"


def test_json_without_schema_falls_back_to_freeform(monkeypatch):
    payload = {"score": 0.9, "issues": [], "reason": "clean"}
    monkeypatch.setattr(
        provider, "run_text_agent",
        lambda prompt, *, system_prompt=None, model=None, temperature=0.0, on_usage=None:
            "```json\n" + json.dumps(payload) + "\n```",
    )
    r = _judge(RUN).run(_ctx([_span()]), {"output_type": "json", "threshold": 0.5})[0]
    assert r.verdict == "PASS"
    assert json.loads(r.string_value) == payload


def test_json_with_schema_enforces_user_contract(monkeypatch):
    """The schema builder's stored JSON Schema compiles to the structured-output contract with
    EXACTLY the user's fields — nothing appended. Enum fields are Literal-enforced; a user-defined
    numeric `score` drives value/verdict and a `reasoning` field becomes the comment, while every
    field (score included) stays in string_value."""
    seen: dict = {}

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0, on_usage=None):
        seen["fields"] = dict(response_format.model_fields)
        return response_format(intent="complaint", score=0.2, reasoning="the user is upset")

    monkeypatch.setattr(provider, "run_structured_agent", fake)
    config = {
        "output_type": "json",
        "threshold": 0.5,
        "output_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string", "enum": ["question", "complaint", "other"]},
                "score": {"type": "number"},
                "reasoning": {"type": "string"},
            },
            "required": ["intent", "score", "reasoning"],
        },
    }
    r = _judge(RUN).run(_ctx([_span()]), config)[0]
    # the contract carried only the user's fields — no envelope
    assert set(seen["fields"]) == {"intent", "score", "reasoning"}
    # the user-defined score drove value/verdict; reasoning became the comment; all fields kept
    assert (r.value, r.verdict, r.data_type) == (0.2, "FAIL", "TEXT")
    assert json.loads(r.string_value) == {"intent": "complaint", "score": 0.2, "reasoning": "the user is upset"}
    assert r.comment == "the user is upset"


def test_sequential_steps_chain_previous_result(monkeypatch):
    """execution_mode=sequential: step i+1 sees what step i DID (the run so far) and how it was
    graded. Batch grades each step alone — that is the whole difference between the modes."""
    prompts: list[str] = []

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0, on_usage=None):
        prompts.append(prompt)
        return response_format(score=0.4, reason=f"grade {len(prompts)}")

    monkeypatch.setattr(provider, "run_structured_agent", fake)
    spans = [
        _span(span_id="root", type="AGENT"),
        _span(span_id="tool-1", type="TOOL", name="lookup", parent_span_id="root",
              output="found order 42"),
        _span(span_id="tool-2", type="TOOL", name="update", parent_span_id="root"),
    ]
    results = _judge(SPAN).run(
        _ctx(spans), {"execution_mode": "sequential", "span_types": ["TOOL"], "threshold": 0.6}
    )
    assert len(results) == 2
    assert "Previous result of this metric" not in prompts[0]  # first item has no chain context
    assert "Steps already taken" not in prompts[0]
    assert "Previous result of this metric" in prompts[1]
    assert "grade 1" in prompts[1]  # the first grade's reason rode along
    # …and the step itself, not just its verdict: what the agent actually did before this one
    assert "Steps already taken" in prompts[1]
    assert "found order 42" in prompts[1]
    # batch mode never chains
    prompts.clear()
    _judge(SPAN).run(_ctx(spans), {"span_types": ["TOOL"]})
    assert all("Previous result of this metric" not in p for p in prompts)
    assert all("Steps already taken" not in p for p in prompts)


def test_trace_level_previous_result_seed(monkeypatch):
    """Thread runs seed cross-turn chaining via config.__previous_result__."""
    prompts: list[str] = []

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0, on_usage=None):
        prompts.append(prompt)
        return response_format(score=1.0, reason="ok")

    monkeypatch.setattr(provider, "run_structured_agent", fake)
    config = {"execution_mode": "sequential", "__previous_result__": {"value": 0.3, "verdict": "FAIL"}}
    _judge(RUN).run(_ctx([_span()]), config)
    assert "Previous result of this metric" in prompts[0]
    assert '"verdict": "FAIL"' in prompts[0]


def test_sequential_message_sees_the_earlier_turns(monkeypatch):
    """A sequential message judge grades turn N in the light of turns 1..N-1 — the conversation
    that led here, not just the previous verdict. Batch grades the message on its own."""
    prompts: list[str] = []

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0, on_usage=None):
        prompts.append(prompt)
        return response_format(score=1.0, reason="ok")

    monkeypatch.setattr(provider, "run_structured_agent", fake)
    thread = [
        _span(trace_id="t0", span_id="r0", input="where is my order?", output="order 42 shipped"),
        _span(trace_id="t1", span_id="r1", input="when does it arrive?", output="tomorrow"),
    ]
    ctx = RunContext(
        "p", "t1", "run-1", [thread[1]], thread[1], thread_id="c1", thread_spans=thread
    )
    _judge(RUN).run(ctx, {"execution_mode": "sequential"})
    assert "Conversation so far" in prompts[0]
    assert "where is my order?" in prompts[0]
    assert "when does it arrive?" not in prompts[0].split("User request:")[0]  # not the turn itself

    prompts.clear()
    _judge(RUN).run(ctx, {})
    assert "Conversation so far" not in prompts[0]


def test_the_graded_request_is_the_last_user_message(monkeypatch):
    """A span's input is the whole message array the model was called with — system prompt, every
    earlier turn, then the new one. Taking its FIRST readable text graded this message's answer
    against the system prompt (or turn 1), which is how a correct answer scored 0.05."""
    prompts: list[str] = []
    _stub_structured(monkeypatch, {"score": 1.0, "reason": "ok"}, prompts=prompts)
    messages = json.dumps([
        {"role": "system", "content": "You are a returns specialist."},
        {"role": "user", "content": "where is my order?"},
        {"role": "assistant", "content": "it shipped"},
        {"role": "user", "content": [{"type": "text", "text": "refund the duplicate charge"}]},
    ])
    spans = [
        _span(span_id="root", type="AGENT", input=None, output="Refund started."),
        _span(span_id="gen-1", type="GENERATION", parent_span_id="root", input=messages),
    ]
    _judge(RUN).run(_ctx(spans), {})
    assert "User request:\nrefund the duplicate charge" in prompts[0]
    assert "You are a returns specialist." not in prompts[0].split("Agent answer:")[0]


def test_no_key_skips_entirely(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "llm_judge_api_key", "")
    assert _judge(RUN).run(_ctx([_span()]), {}) == []


def test_transport_error_skips(monkeypatch):
    def boom(prompt, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(provider, "run_structured_agent", boom)
    assert _judge(RUN).run(_ctx([_span()]), {}) == []


# ── token-usage capture (per-evaluator cost) ─────────────────────────────────
def test_judge_attaches_token_usage(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0, on_usage=None):
        if on_usage:
            on_usage({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "model": "openai/gpt-5.4-nano"})
        return response_format(score=0.9, reason="ok")

    monkeypatch.setattr(provider, "run_structured_agent", fake)
    r = _judge(RUN).run(_ctx([_span()]), {"output_type": "score", "threshold": 0.5})[0]
    assert r.usage and r.usage["total_tokens"] == 120 and r.usage["model"] == "openai/gpt-5.4-nano"


def test_usage_metadata_maps_to_strings():
    from tracely.infrastructure.clickhouse.score_writer import _usage_metadata

    assert _usage_metadata(None) == {}
    m = _usage_metadata({"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "model": "x"})
    assert m == {
        "eval.input_tokens": "100", "eval.output_tokens": "20",
        "eval.total_tokens": "120", "eval.model": "x",
    }


# ── advanced (template) mode ─────────────────────────────────────────────────


def test_advanced_sends_the_resolved_template_as_the_human_message(monkeypatch):
    """is_advanced=True: the resolved `@VARIABLE` prompt IS the prompt — carried ONCE, as the human
    message, with NO auto-injected trace context and a fixed system preamble."""
    from tracely.domain.evaluation.evaluators.llm_judge import ADVANCED_SYSTEM

    systems: list = []
    prompts: list = []
    _stub_structured(monkeypatch, {"score": 0.9, "reason": "ok"}, prompts=prompts, systems=systems)
    config = {
        "is_advanced": True,
        "prompt": "Grade: @CURRENT_MESSAGE.output (asked: @CURRENT_MESSAGE.input)",
        "threshold": 0.6,
    }
    results = _judge(RUN).run(_ctx([_span(input="ping", output="pong")]), config)
    assert len(results) == 1 and results[0].verdict == "PASS"
    assert prompts == ["Grade: pong (asked: ping)"]
    assert systems == [ADVANCED_SYSTEM]


def test_advanced_history_uses_full_thread_spans(monkeypatch):
    """At message level @HISTORY is the WHOLE conversation — the service feeds `thread_spans` even
    though `ctx.spans` is only the current turn."""
    prompts: list = []
    _stub_structured(monkeypatch, {"score": 1.0, "reason": "ok"}, prompts=prompts)
    cur = [_span(trace_id="t2", span_id="b", input="tomorrow", output="booked!")]
    thread = [
        _span(trace_id="t1", span_id="a", input="book a flight", output="which date?"),
        _span(trace_id="t2", span_id="b", input="tomorrow", output="booked!"),
    ]
    ctx = RunContext("p", "t2", "run-1", cur, root_span(cur), thread_id="th-9", thread_spans=thread)
    _judge(RUN).run(ctx, {"is_advanced": True, "prompt": "@HISTORY"})
    assert "book a flight" in prompts[0] and "booked!" in prompts[0]


def test_advanced_step_grades_each_candidate_with_step_vars(monkeypatch):
    prompts: list = []
    _stub_structured(monkeypatch, {"score": 1.0, "reason": "fine"}, prompts=prompts)
    spans = [
        _span(span_id="root", type="AGENT", input="q", output="a"),
        _span(span_id="tool-1", type="TOOL", name="lookup", parent_span_id="root", is_app_root=0,
              input="x", output="result-1"),
        _span(span_id="tool-2", type="TOOL", name="update", parent_span_id="root", is_app_root=0,
              input="y", output="result-2"),
    ]
    config = {"is_advanced": True, "span_types": ["TOOL"],
              "prompt": "step @STEP_NUMBER: @CURRENT_STEP.tool_result"}
    results = _judge(SPAN).run(_ctx(spans), config)
    assert [r.target_span_id for r in results] == ["tool-1", "tool-2"]
    assert "step 1: result-1" in prompts[0]
    assert "step 2: result-2" in prompts[1]


def test_needs_thread_context_gates_on_conversation_scoped_vars():
    from tracely.services.evaluation_service import _needs_thread_context

    step_local = {"kind": "llm_judge", "config": {"is_advanced": True, "template_variables": ["CURRENT_STEP.tool_call"]}}
    convo = {"kind": "llm_judge", "config": {"is_advanced": True, "template_variables": ["HISTORY"]}}
    basic = {"kind": "llm_judge", "config": {"prompt": "grade it"}}
    assert _needs_thread_context([step_local]) is False  # step-local pays nothing
    assert _needs_thread_context([basic]) is False
    assert _needs_thread_context([convo]) is True


# ── an unanswered run is graded, not skipped ──────────────────────────────────


def test_a_run_with_no_answer_is_still_graded(monkeypatch):
    """It used to return no result at all, so the worst outcome there is — the agent crashed,
    timed out, or replied with nothing — produced no score and the cell read "not graded yet"."""
    prompts: list = []
    _stub_structured(monkeypatch, {"score": 0.0, "reason": "no answer"}, prompts=prompts)
    spans = [_span(output="", input="where is my refund?")]
    results = _judge(RUN).run(_ctx(spans), {"prompt": "Grade.", "threshold": 0.6})
    assert [r.verdict for r in results] == ["FAIL"]
    assert "(the agent produced no answer)" in prompts[0]


def test_a_run_with_neither_request_nor_answer_is_skipped(monkeypatch):
    """Nothing to grade is not the same as a failure — don't spend a judge call on it."""
    _stub_structured(monkeypatch, {"score": 1.0, "reason": "x"})
    assert _judge(RUN).run(_ctx([_span(input="", output="")]), {"prompt": "Grade."}) == []


# ── the advanced template is sent once, not twice ─────────────────────────────


def test_the_advanced_template_is_not_sent_as_both_system_and_message(monkeypatch):
    """It used to ride in both slots: double the input tokens on every advanced grade, and a
    rubric repeated verbatim measurably degrades instruction-following."""
    from tracely.domain.evaluation.evaluators.llm_judge import ADVANCED_SYSTEM

    prompts: list = []
    systems: list = []
    _stub_structured(monkeypatch, {"score": 0.9, "reason": "ok"}, prompts=prompts, systems=systems)
    config = {"is_advanced": True, "prompt": "Grade @CURRENT_MESSAGE.output", "threshold": 0.6}
    _judge(RUN).run(_ctx([_span()]), config)
    assert systems == [ADVANCED_SYSTEM]
    assert prompts[0] != ADVANCED_SYSTEM and "Grade" in prompts[0]
