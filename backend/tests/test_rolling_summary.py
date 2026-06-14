"""Rolling summary: span decomposition, item construction (verbatim + tool linkage), @HISTORY,
and the 20k-budget recursive compaction."""

from __future__ import annotations

from unittest.mock import patch

from tracely.domain.evaluation.rolling_summary import (
    components_token_total,
    format_summary_as_history,
    items_from_components,
    step_components,
    summary_token_total,
    user_input_component,
)
from tracely.services import rolling_summary_service as rss
from tracely.services.rolling_summary_service import RollingSummaryService


def test_thinking_span_component():
    comps = step_components({"type": "THINKING", "output": "I should call the weather tool."})
    assert len(comps) == 1
    assert (comps[0].role, comps[0].type) == ("assistant", "thinking")


def test_tool_span_yields_call_and_result():
    comps = step_components(
        {"type": "TOOL", "name": "get_weather", "input": '{"city":"Paris"}', "output": '{"temp_c":18}'}
    )
    assert [(c.role, c.type) for c in comps] == [
        ("assistant", "tool_call"),
        ("tool", "tool_result"),
    ]
    assert comps[0].tool_name == "get_weather"
    assert "Paris" in comps[0].content


def test_generation_structured_vs_text():
    structured = step_components({"type": "GENERATION", "output": {"answer": "yes"}})
    assert structured[0].type == "output_structured"
    text = step_components({"type": "GENERATION", "output": "It is sunny."})
    assert text[0].type == "output_content"


def test_items_link_tool_call_to_result():
    comps = step_components(
        {"type": "TOOL", "name": "get_weather", "input": "{}", "output": "sunny"}
    )
    items = items_from_components(comps)
    call, result = items
    assert call.tool_call_id and call.tool_call_id == result.tool_call_id


def test_verbatim_under_budget_keeps_content():
    comps = step_components({"type": "GENERATION", "output": "It is 18C and sunny in Paris."})
    assert components_token_total(comps) < 512
    items = items_from_components(comps)  # no summaries → verbatim
    assert items[0].content == "It is 18C and sunny in Paris."


def test_llm_summaries_replace_content_but_keep_structure():
    comps = step_components(
        {"type": "TOOL", "name": "search", "input": "{}", "output": "x" * 50}
    )
    items = items_from_components(comps, summaries=["searched", "found x"])
    assert items[0].type == "tool_call" and items[0].content == "searched"
    assert items[1].type == "tool_result" and items[1].content == "found x"


def test_user_input_component():
    uc = user_input_component({"input": "What is the weather?"})
    assert uc is not None and uc.role == "user"
    assert user_input_component({"input": ""}) is None


def test_history_render_format():
    comps = [
        user_input_component({"input": "Weather in Paris?"}),
        *step_components({"type": "GENERATION", "output": "18C and sunny."}),
    ]
    items = [it.model_dump() for it in items_from_components([c for c in comps if c])]
    history = format_summary_as_history(items)
    assert "[user]: Weather in Paris?" in history
    assert "[assistant]: 18C and sunny." in history


def test_format_history_full_vs_clipped():
    items = [{"role": "assistant", "type": "output_content", "content": "x" * 1000}]
    assert len(format_summary_as_history(items, max_chars=0)) > 900  # full (no clip)
    assert len(format_summary_as_history(items, max_chars=100)) <= 100  # clipped


def _big_items(n: int, tokens_each: int = 3000):
    chars = tokens_each * 4
    return [
        {
            "role": "assistant",
            "type": "output_content",
            "content": "x" * chars,
            "tool_call_id": None,
            "tool_name": None,
            "tool_arguments": None,
        }
        for _ in range(n)
    ]


def test_summary_token_total():
    items = _big_items(3, tokens_each=100)  # 400 chars ≈ 100 tokens each
    assert summary_token_total(items) == 300


def test_compaction_keeps_last_two_and_drops_under_budget():
    svc = RollingSummaryService.__new__(RollingSummaryService)  # skip TraceReader init
    running = _big_items(10, tokens_each=3000)  # 30k tokens, over the 20k budget
    with patch.object(rss.provider, "llm_enabled", return_value=False):
        out, n = svc._compact_to_budget(list(running))
    assert n >= 1
    assert summary_token_total(out) <= 20000  # under budget
    assert out[0]["type"] == "summary"  # head folded into one compacted block
    assert out[-1]["content"] == running[-1]["content"]  # last 2 kept verbatim
    assert out[-2]["content"] == running[-2]["content"]


def test_compaction_noop_under_budget():
    svc = RollingSummaryService.__new__(RollingSummaryService)
    running = _big_items(3, tokens_each=1000)  # 3k tokens, well under budget
    with patch.object(rss.provider, "llm_enabled", return_value=False):
        out, n = svc._compact_to_budget(list(running))
    assert n == 0
    assert out == running  # untouched
