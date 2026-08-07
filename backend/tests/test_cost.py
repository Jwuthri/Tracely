"""Span cost: token counts x the published per-model rate.

Rates are OpenRouter's catalog, not a list we maintain — these tests stub the catalog and pin the
two things that are ours: how a tracer-reported model id resolves to a catalog entry, and the
arithmetic. Before any of this existed `cost_details` was never written, so every server-side cost
figure (Trends, analytics, gate spend deltas) summed an empty map to a hard zero.
"""

from __future__ import annotations

import pytest

from tracely.domain.cost import cost_details
from tracely.infrastructure.llm import provider
from tracely.services.ingestion_service import IngestionService

# `{id: {prompt_per_mtok, completion_per_mtok}}` — the shape `_openrouter_models()` returns.
_CATALOG = {
    "openai/gpt-4o": {"name": "GPT-4o", "prompt_per_mtok": 2.5, "completion_per_mtok": 10.0},
    "openai/gpt-4o-mini": {"name": "mini", "prompt_per_mtok": 0.15, "completion_per_mtok": 0.6},
    # Dotted, the way OpenRouter spells it — Anthropic's own API says `claude-sonnet-4-5-…`.
    "anthropic/claude-sonnet-4.5": {"name": "s", "prompt_per_mtok": 3.0, "completion_per_mtok": 15.0},
}


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    """Serve a fixed catalog and reset the derived price index between tests."""
    monkeypatch.setattr(provider, "_openrouter_models", lambda: _CATALOG)
    monkeypatch.setattr(provider, "_models_cache", {"ts": 1.0, "by_id": _CATALOG})
    monkeypatch.setattr(provider, "_price_index_cache", {"stamp": None, "idx": None})
    yield


# ── resolving a tracer-reported model id ─────────────────────────────────────


def test_full_openrouter_id_resolves():
    assert provider.resolve_rate("openai/gpt-4o") == (2.5, 10.0)


def test_bare_id_resolves_without_assuming_openai():
    """`model_pricing` prefixes bare ids with `openai/` — fine for a judge model we picked, wrong
    at ingest, where an Anthropic instrumentor reports a bare id and would price at zero."""
    assert provider.resolve_rate("claude-sonnet-4.5") == (3.0, 15.0)
    assert provider.resolve_rate("gpt-4o") == (2.5, 10.0)


def test_dot_and_dash_spellings_are_the_same_model():
    """OpenRouter lists `anthropic/claude-sonnet-4.5`; Anthropic's API — and so its instrumentor —
    reports `claude-sonnet-4-5-20250929`. Without folding the separator, no Anthropic span prices."""
    assert provider.resolve_rate("claude-sonnet-4-5-20250929") == (3.0, 15.0)
    assert provider.resolve_rate("claude-sonnet-4-5") == (3.0, 15.0)


def test_a_dated_snapshot_falls_back_to_its_base_model():
    """Providers stamp dated snapshots; `gpt-4o-2024-11-20` is priced as `gpt-4o`."""
    assert provider.resolve_rate("gpt-4o-2024-11-20") == (2.5, 10.0)
    assert provider.resolve_rate("openai/gpt-4o-2024-11-20") == (2.5, 10.0)


def test_an_openrouter_variant_tag_is_stripped():
    assert provider.resolve_rate("anthropic/claude-sonnet-4.5:batch") == (3.0, 15.0)


def test_a_more_specific_model_is_not_swallowed_by_its_prefix():
    """The classic price-table bug: `gpt-4o-mini` must not resolve to full `gpt-4o` rates."""
    assert provider.resolve_rate("gpt-4o-mini") == (0.15, 0.6)


def test_an_unknown_model_has_no_rate():
    assert provider.resolve_rate("some-local-llama-thing") is None
    assert provider.resolve_rate("") is None


# ── the arithmetic ───────────────────────────────────────────────────────────


def test_cost_is_tokens_times_rate():
    assert cost_details((2.5, 10.0), {"input": 1_000_000, "output": 100_000}) == {
        "input": 2.5,
        "output": 1.0,
    }


def test_an_unpriced_model_yields_no_cost_not_zero():
    """A 0.0 would read as 'this run was free' and silently under-report a project's spend."""
    assert cost_details(None, {"input": 1000, "output": 10}) == {}


def test_no_tokens_no_cost():
    assert cost_details((2.5, 10.0), {}) == {}
    assert cost_details((2.5, 10.0), None) == {}


def test_a_total_only_span_is_priced_at_the_input_rate():
    assert cost_details((2.5, 10.0), {"total": 1_000_000}) == {"total": 2.5}


# ── the ingest hop ───────────────────────────────────────────────────────────


def test_ingest_attaches_cost_to_generation_spans():
    events = [
        {"model_id": "gpt-4o", "usage_details": {"input": 1_000_000, "output": 1_000_000}},
        {"model_id": "gpt-4o-mini", "usage_details": {"input": 1_000_000}},
    ]
    IngestionService._attach_costs(events)
    assert events[0]["cost_details"] == {"input": 2.5, "output": 10.0}
    assert events[1]["cost_details"] == {"input": 0.15}


def test_ingest_leaves_non_llm_and_unpriced_spans_alone():
    events = [
        {"model_id": "", "usage_details": {}},                       # a TOOL span
        {"model_id": "mystery-model", "usage_details": {"input": 5}},  # not in the catalog
    ]
    IngestionService._attach_costs(events)
    assert not events[0].get("cost_details")
    assert not events[1].get("cost_details")


def test_ingest_never_overwrites_a_cost_that_was_already_reported():
    events = [{"model_id": "gpt-4o", "usage_details": {"input": 10}, "cost_details": {"input": 9.9}}]
    IngestionService._attach_costs(events)
    assert events[0]["cost_details"] == {"input": 9.9}
