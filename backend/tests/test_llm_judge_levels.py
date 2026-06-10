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

    def fake(prompt, *, response_format, system_prompt=None, model=None, temperature=0.0):
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
        _span(span_id="chain-1", type="CHAIN", parent_span_id="root"),  # not in default span_types
    ]
    results = _judge(SPAN).run(_ctx(spans), {"prompt": "Grade the step."})
    assert [r.target_span_id for r in results] == ["tool-1", "gen-1"]
    assert all(r.level == SPAN for r in results)
    assert "Step 1 of 2" in prompts[0]

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


def test_json_output_with_score_and_threshold(monkeypatch):
    payload = {"score": 0.9, "issues": [], "reason": "clean"}
    monkeypatch.setattr(
        provider, "run_text_agent",
        lambda prompt, *, system_prompt=None, model=None, temperature=0.0:
            "```json\n" + json.dumps(payload) + "\n```",
    )
    r = _judge(RUN).run(_ctx([_span()]), {"output_type": "json", "threshold": 0.5})[0]
    assert r.verdict == "PASS"
    assert json.loads(r.string_value) == payload


def test_no_key_skips_entirely(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "llm_judge_api_key", "")
    assert _judge(RUN).run(_ctx([_span()]), {}) == []


def test_transport_error_skips(monkeypatch):
    def boom(prompt, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(provider, "run_structured_agent", boom)
    assert _judge(RUN).run(_ctx([_span()]), {}) == []
