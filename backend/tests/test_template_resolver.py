"""The `@VARIABLE` template engine: extraction, the per-level catalog, context building from
span dicts, and soft-miss resolution. Pure (no DB / LLM) — mirrors the data the run path feeds in.
"""

from __future__ import annotations

from tracely.domain.evaluation.template_resolver import (
    build_context,
    catalog_level,
    extract_template_variables,
    references_conversation_scope,
    template_resolver,
    variables_for_level,
)


def _span(**kw) -> dict:
    base = {
        "trace_id": "t1", "span_id": "s1", "parent_span_id": "", "is_app_root": 1,
        "type": "GENERATION", "name": "", "input": "", "output": "",
        "tool_calls": [], "tool_call_names": [], "agent_id": "agent-a", "conversation_id": "th-1",
    }
    base.update(kw)
    return base


def _resolve(template, ctx):
    return template_resolver.resolve(template, ctx)


# ── extraction + catalog ─────────────────────────────────────────────────────


def test_extract_dedupes_and_keeps_props():
    refs = extract_template_variables("a @HISTORY b @CURRENT_STEP.tool_call c @HISTORY @GOAL")
    assert refs == ["HISTORY", "CURRENT_STEP.tool_call", "GOAL"]


def test_extract_ignores_non_variables():
    # an email and lowercase `@names` are NOT variables (regex requires an UPPERCASE name)
    assert extract_template_variables("mail me at a@x.com or @foo or @lower_case") == []


def test_catalog_level_maps_evaluator_levels():
    assert catalog_level("CONVERSATION") == "conversation"
    assert catalog_level("AGENT_RUN") == "message"
    assert catalog_level("SPAN") == catalog_level("TOOL") == "step"


def test_conversation_level_exposes_nine_variables():
    names = {v.name for v in variables_for_level("CONVERSATION")}
    # 3 common + 6 conversation-only (matches the editor's "Available variables: 9")
    assert len(names) == 9
    assert "HISTORY" in names and "FIRST_USER_MSG" in names
    # step-only vars are NOT offered at conversation level
    assert "CURRENT_STEP" not in names and "STEP_NUMBER" not in names


def test_step_level_inherits_message_and_common():
    names = {v.name for v in variables_for_level("SPAN")}
    assert {"HISTORY", "CURRENT_MESSAGE", "CURRENT_STEP", "STEP_NUMBER", "METRIC_PREVIOUS_RESULT"} <= names
    # conversation-only vars are not at step level
    assert "MESSAGES" not in names


def test_references_conversation_scope():
    assert references_conversation_scope(["HISTORY"]) is True
    assert references_conversation_scope(["PREVIOUS_USER_MSG"]) is True
    # purely step-local refs do NOT need the whole thread fetched
    assert references_conversation_scope(["CURRENT_STEP.tool_call", "METRIC_PREVIOUS_RESULT"]) is False
    assert references_conversation_scope(None) is False


# ── soft miss ────────────────────────────────────────────────────────────────


def test_missing_variable_is_soft():
    ctx = build_context("CONVERSATION", thread_spans=[])
    out = _resolve("history: @HISTORY end", ctx)
    assert out.resolved_text == "history: [No HISTORY available] end"
    assert out.variables_missing == ["HISTORY"]
    assert out.variables_used == []


def test_unknown_variable_soft_misses():
    ctx = build_context("CONVERSATION", thread_spans=[_span(input="hi", output="yo")])
    out = _resolve("@HISTROY", ctx)  # typo → unknown → soft miss, not a crash
    assert out.resolved_text == "[No HISTROY available]"


# ── conversation level ───────────────────────────────────────────────────────


def _thread():
    return [
        _span(trace_id="t1", span_id="a", input="book a flight", output="which date?"),
        _span(trace_id="t2", span_id="b", input="tomorrow", output="booked!"),
    ]


def test_conversation_history_and_messages():
    ctx = build_context("CONVERSATION", thread_spans=_thread())
    out = _resolve("@HISTORY", ctx)
    assert "[user]: book a flight" in out.resolved_text
    assert "[assistant]: booked!" in out.resolved_text
    assert out.variables_used == ["HISTORY"]


def test_conversation_goal_is_first_user_request():
    ctx = build_context("CONVERSATION", thread_spans=_thread())
    assert _resolve("@GOAL", ctx).resolved_text == "book a flight"
    assert _resolve("@FIRST_USER_MSG", ctx).resolved_text == "book a flight"
    assert _resolve("@LAST_ASSISTANT_MSG", ctx).resolved_text == "booked!"


def test_list_agent_lists_agents_and_tools():
    spans = [
        _span(trace_id="t1", span_id="root", type="AGENT", agent_id="planner", input="go"),
        _span(trace_id="t1", span_id="tool", type="TOOL", name="search", agent_id="planner",
              parent_span_id="root", is_app_root=0, output="results"),
    ]
    out = _resolve("@LIST_AGENT", ctx=build_context("CONVERSATION", thread_spans=spans))
    assert "planner" in out.resolved_text and "search" in out.resolved_text


# ── message level ────────────────────────────────────────────────────────────


def test_message_current_and_previous():
    ctx = build_context("AGENT_RUN", thread_spans=_thread(), current_trace_id="t2")
    assert _resolve("@CURRENT_MESSAGE.output", ctx).resolved_text == "booked!"
    assert _resolve("@CURRENT_MESSAGE.input", ctx).resolved_text == "tomorrow"
    assert _resolve("@CURRENT_MESSAGE.role", ctx).resolved_text == "assistant"
    assert _resolve("@PREVIOUS_USER_MSG", ctx).resolved_text == "book a flight"
    assert _resolve("@PREVIOUS_ASSISTANT_MSG", ctx).resolved_text == "which date?"


def test_message_history_is_full_thread_not_just_current_turn():
    # at message level @HISTORY must still be the WHOLE conversation (the service feeds thread_spans)
    ctx = build_context("AGENT_RUN", thread_spans=_thread(), current_trace_id="t2")
    assert "book a flight" in _resolve("@HISTORY", ctx).resolved_text


def test_first_turn_previous_is_soft_miss():
    ctx = build_context("AGENT_RUN", thread_spans=_thread(), current_trace_id="t1")
    assert _resolve("@PREVIOUS_USER_MSG", ctx).resolved_text == "[No PREVIOUS_USER_MSG available]"


# ── step level ───────────────────────────────────────────────────────────────


def _trace_with_steps():
    return [
        _span(trace_id="t1", span_id="root", type="AGENT", input="weather?", output="it's sunny"),
        _span(trace_id="t1", span_id="tool-1", type="TOOL", name="get_weather", parent_span_id="root",
              is_app_root=0, input="SF", output="sunny, 70F",
              tool_calls=[{"name": "get_weather", "args": {"city": "SF"}}]),
        _span(trace_id="t1", span_id="gen-1", type="GENERATION", parent_span_id="root",
              is_app_root=0, input="...", output="it's sunny"),
    ]


def test_step_tool_call_and_result():
    ctx = build_context("SPAN", thread_spans=_trace_with_steps(), current_trace_id="t1", current_span_id="tool-1")
    assert "get_weather" in _resolve("@CURRENT_STEP.tool_call", ctx).resolved_text
    assert _resolve("@CURRENT_STEP.tool_result", ctx).resolved_text == "sunny, 70F"
    assert _resolve("@CURRENT_STEP.output_content", ctx).resolved_text == "sunny, 70F"


def test_step_number_excludes_root_wrapper():
    # the agent-root is not a "step": the first tool is step 1, and it has no previous step
    ctx = build_context("SPAN", thread_spans=_trace_with_steps(), current_trace_id="t1", current_span_id="tool-1")
    assert _resolve("@STEP_NUMBER", ctx).resolved_text == "1"
    assert _resolve("@PREVIOUS_STEP.tool_result", ctx).resolved_text == "[No PREVIOUS_STEP.tool_result available]"
    assert _resolve("@CURRENT_STEPS_COUNT", ctx).resolved_text == "2"
    # the gen step is step 2 and its previous step is the tool
    ctx2 = build_context("SPAN", thread_spans=_trace_with_steps(), current_trace_id="t1", current_span_id="gen-1")
    assert _resolve("@STEP_NUMBER", ctx2).resolved_text == "2"
    assert "get_weather" in _resolve("@PREVIOUS_STEP.tool_call", ctx2).resolved_text


def test_bare_current_step_dumps_fields():
    ctx = build_context("SPAN", thread_spans=_trace_with_steps(), current_trace_id="t1", current_span_id="tool-1")
    text = _resolve("@CURRENT_STEP", ctx).resolved_text
    assert "Tool call:" in text and "get_weather" in text and "Tool result: sunny, 70F" in text


def test_thinking_only_for_thinking_spans():
    spans = [
        _span(trace_id="t1", span_id="root", type="AGENT", input="q", output="a"),
        _span(trace_id="t1", span_id="think-1", type="THINKING", parent_span_id="root", is_app_root=0,
              output="let me reason about this"),
    ]
    ctx = build_context("SPAN", thread_spans=spans, current_trace_id="t1", current_span_id="think-1")
    assert _resolve("@CURRENT_STEP.thinking", ctx).resolved_text == "let me reason about this"
    # a TOOL step has no thinking → soft miss
    tool_ctx = build_context("SPAN", thread_spans=_trace_with_steps(), current_trace_id="t1", current_span_id="tool-1")
    assert _resolve("@CURRENT_STEP.thinking", tool_ctx).resolved_text == "[No CURRENT_STEP.thinking available]"


# ── sequential ───────────────────────────────────────────────────────────────


def test_metric_previous_result_only_when_present():
    spans = _trace_with_steps()
    ctx = build_context("SPAN", thread_spans=spans, current_trace_id="t1", current_span_id="tool-1",
                        metric_previous_result={"value": 0.4, "verdict": "FAIL"})
    out = _resolve("prev: @METRIC_PREVIOUS_RESULT", ctx)
    assert '"verdict": "FAIL"' in out.resolved_text
    # absent → soft miss
    ctx2 = build_context("SPAN", thread_spans=spans, current_trace_id="t1", current_span_id="tool-1")
    assert _resolve("@METRIC_PREVIOUS_RESULT", ctx2).resolved_text == "[No METRIC_PREVIOUS_RESULT available]"


# ── lazy materialization ─────────────────────────────────────────────────────


def test_wanted_vars_skips_unreferenced():
    # only @CURRENT_STEP wanted → @HISTORY is not materialized (and resolves to a soft miss)
    ctx = build_context("SPAN", thread_spans=_trace_with_steps(), current_trace_id="t1",
                        current_span_id="tool-1", wanted_vars=["CURRENT_STEP.tool_call"])
    assert ctx.history is None
    assert _resolve("@HISTORY", ctx).resolved_text == "[No HISTORY available]"
    assert "get_weather" in _resolve("@CURRENT_STEP.tool_call", ctx).resolved_text
