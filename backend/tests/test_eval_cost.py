"""Per-evaluator LLM-judge cost math — pure tests, no LLM, no DB.

Locks down the (model_id × tokens → USD cents) pricing pipeline that backs `/api/evaluators/cost`
and the Trends cost view. The actual OpenRouter `/models` fetch is mocked so tests stay offline.
"""

from __future__ import annotations

from pytest import approx

from tracely.infrastructure.llm import provider


# ── _per_mtok: OpenRouter publishes $/token strings; we store $/Mtok ──────────
def test_per_mtok_converts_dollars_per_token():
    # Float arithmetic drift on 1e-N * 1e6 → approx, not strict equality.
    assert provider._per_mtok("0.0000005") == approx(0.5)     # $0.50 / Mtok
    assert provider._per_mtok("0.000003") == approx(3.0)
    assert provider._per_mtok("1e-7") == approx(0.1)


def test_per_mtok_handles_missing_and_zero():
    # Free models / missing fields stay distinct from "$0.00/Mtok" so the UI can show "—".
    assert provider._per_mtok(None) is None
    assert provider._per_mtok("") is None
    assert provider._per_mtok("not-a-number") is None
    assert provider._per_mtok("0") is None       # free-tier model: don't pretend it's priced
    assert provider._per_mtok("0.0") is None


# ── model_pricing: live → fallback → unknown ─────────────────────────────────
def test_model_pricing_prefers_live_openrouter(monkeypatch):
    monkeypatch.setattr(
        provider,
        "_openrouter_models",
        lambda: {
            "openai/gpt-5.4-nano": {
                "name": "GPT-5.4 Nano",
                "prompt_per_mtok": 0.05,        # overrides the static $0.10
                "completion_per_mtok": 0.20,
            }
        },
    )
    pin, pout = provider.model_pricing("openai/gpt-5.4-nano")
    assert (pin, pout) == (0.05, 0.20)


def test_model_pricing_falls_back_to_static_table_when_offline(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    # Asserts the *behavior* (offline → consult the static table), not a literal price: the table
    # is refreshed from OpenRouter whenever the catalog moves, and that must not break this test.
    expected = provider._FALLBACK_PRICING_USD_PER_MTOK["openai/gpt-5.4-nano"]
    assert provider.model_pricing("openai/gpt-5.4-nano") == expected


def test_model_pricing_unknown_returns_none(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    assert provider.model_pricing("vendor/imaginary-model-9000") == (None, None)


def test_model_pricing_normalizes_bare_id_to_openai_prefix(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    # `gpt-5.4-nano` (bare) is the OpenAI direct-endpoint form — normalize to `openai/gpt-5.4-nano`.
    expected = provider._FALLBACK_PRICING_USD_PER_MTOK["openai/gpt-5.4-nano"]
    assert provider.model_pricing("gpt-5.4-nano") == expected


def test_model_pricing_empty_id_is_unknown(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    assert provider.model_pricing("") == (None, None)
    assert provider.model_pricing(None) == (None, None)  # type: ignore[arg-type]


# ── estimate_cost_usd_cents: the math ────────────────────────────────────────
def test_estimate_cost_unknown_model_is_zero_not_error(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    # Unknown model → 0 cents (not an exception). UI is responsible for distinguishing
    # "no price available" from "really $0" — keep this side numeric.
    assert provider.estimate_cost_usd_cents("vendor/unknown", 1_000_000, 1_000_000) == 0


def _priced(monkeypatch, prompt_per_mtok: float, completion_per_mtok: float) -> str:
    """Pin a synthetic model at an exact price so the arithmetic below is locked independently of
    whatever the real catalog charges this month."""
    monkeypatch.setattr(
        provider, "_openrouter_models",
        lambda: {"test/judge": {"name": "T", "prompt_per_mtok": prompt_per_mtok,
                                "completion_per_mtok": completion_per_mtok}},
    )
    return "test/judge"


def test_estimate_cost_for_known_model_rounds_to_cents(monkeypatch):
    mid = _priced(monkeypatch, 0.10, 0.40)
    # 1M input + 1M output = $0.10 + $0.40 = $0.50 = 50¢
    assert provider.estimate_cost_usd_cents(mid, 1_000_000, 1_000_000) == 50


def test_estimate_cost_sub_cent_call_floors_to_zero(monkeypatch):
    mid = _priced(monkeypatch, 0.10, 0.40)
    # 543 in + 73 out: (543*0.10 + 73*0.40)/1M $ ≈ $0.0000835 → 0¢
    assert provider.estimate_cost_usd_cents(mid, 543, 73) == 0


def test_estimate_cost_uses_bankers_rounding_on_exact_half_cent(monkeypatch):
    mid = _priced(monkeypatch, 15.0, 75.0)
    # 50k in + 5k out → (50000*15 + 5000*75)/1M $ = $1.125 → exactly 112.5¢.
    # Python's `round` uses banker's rounding: 112.5 → 112, not 113. Documented here so nobody
    # "fixes" it back to 113.
    assert provider.estimate_cost_usd_cents(mid, 50_000, 5_000) == 112


def test_estimate_cost_zero_tokens_is_zero(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    assert provider.estimate_cost_usd_cents("openai/gpt-5.4-nano", 0, 0) == 0


def test_estimate_cost_handles_half_priced_models(monkeypatch):
    # Model with prompt price but no completion price → only the prompt half is billed.
    monkeypatch.setattr(
        provider,
        "_openrouter_models",
        lambda: {"vendor/half": {"name": "Half", "prompt_per_mtok": 10.0, "completion_per_mtok": None}},
    )
    # 1M input * $10 = $10 = 1000¢; output contributes 0
    assert provider.estimate_cost_usd_cents("vendor/half", 1_000_000, 5_000_000) == 1_000


# ── _openrouter_models: parses the catalog response shape ────────────────────
def test_openrouter_models_parses_pricing_from_catalog(monkeypatch):
    class _Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [
                {"id": "openai/gpt-5.4-nano", "name": "GPT-5.4 Nano",
                 "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}},
                {"id": "free/model", "name": "Free",
                 "pricing": {"prompt": "0", "completion": "0"}},  # free → None, distinct from $0
                {"id": "weird/missing-pricing", "name": "No pricing"},
            ]}

    class _Httpx:
        def get(self, *a, **kw): return _Resp()

    import sys
    import types

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.get = _Httpx().get  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setattr(provider.settings, "openrouter_api_key", "test-key")
    provider._models_cache["by_id"] = None  # force refresh
    provider._models_cache["ts"] = 0.0

    out = provider._openrouter_models()
    assert out["openai/gpt-5.4-nano"]["prompt_per_mtok"] == approx(0.1)
    assert out["openai/gpt-5.4-nano"]["completion_per_mtok"] == approx(0.4)
    assert out["free/model"]["prompt_per_mtok"] is None       # zero → unknown
    assert out["weird/missing-pricing"]["prompt_per_mtok"] is None

    # Back-compat shim still returns name-only.
    names = provider._openrouter_model_names()
    assert names["openai/gpt-5.4-nano"] == "GPT-5.4 Nano"


# ── the curated dropdown vs the pricing table ────────────────────────────────
def test_every_curated_model_has_a_fallback_price():
    """Adding a model to the dropdown without a fallback price is silent: the column works, but
    with OpenRouter unreachable its cost renders $0.00 and quietly under-reports judge spend."""
    missing = [mid for mid, _ in provider._CURATED_MODELS
               if mid not in provider._FALLBACK_PRICING_USD_PER_MTOK]
    assert missing == [], f"curated models with no fallback price: {missing}"


def test_config_default_models_are_priced():
    """The judge / meta-analysis / rolling-summary defaults never appear in the dropdown, but they
    DO get stamped onto scores — so they need prices too, or their spend reads as free."""
    from tracely.config import settings

    defaults = {settings.llm_judge_model, settings.meta_analysis_model,
                settings.rolling_summary_model}
    missing = [m for m in defaults
               if provider._normalize_model(m) not in provider._FALLBACK_PRICING_USD_PER_MTOK]
    assert missing == [], f"config default models with no fallback price: {missing}"


def test_curated_models_have_no_duplicates():
    ids = [mid for mid, _ in provider._CURATED_MODELS]
    assert len(ids) == len(set(ids))
