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
    # In the static table — should return its known values.
    pin, pout = provider.model_pricing("openai/gpt-5.4-nano")
    assert pin == 0.10 and pout == 0.40


def test_model_pricing_unknown_returns_none(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    assert provider.model_pricing("vendor/imaginary-model-9000") == (None, None)


def test_model_pricing_normalizes_bare_id_to_openai_prefix(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    # `gpt-5.4-nano` (bare) is the OpenAI direct-endpoint form — normalize to `openai/gpt-5.4-nano`.
    pin, pout = provider.model_pricing("gpt-5.4-nano")
    assert pin == 0.10 and pout == 0.40


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


def test_estimate_cost_for_known_model_rounds_to_cents(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    # gpt-5.4-nano: $0.10 / Mtok input, $0.40 / Mtok output
    # 1M input + 1M output = $0.10 + $0.40 = $0.50 = 50¢
    assert provider.estimate_cost_usd_cents("openai/gpt-5.4-nano", 1_000_000, 1_000_000) == 50


def test_estimate_cost_typical_judge_call(monkeypatch):
    monkeypatch.setattr(provider, "_openrouter_models", lambda: {})
    # 543 in + 73 out on gpt-5.4-nano: (543*0.10 + 73*0.40)/1M $ ≈ $0.0000835 → 0¢ (rounds down)
    assert provider.estimate_cost_usd_cents("openai/gpt-5.4-nano", 543, 73) == 0
    # A heavy judge: 50k in + 5k out on opus → (50000*15 + 5000*75)/1M $ = $1.125 → 112¢
    # (Python's `round` uses banker's rounding: 112.5 → 112, not 113. Document that here so
    # nobody "fixes" it back to 113.)
    assert provider.estimate_cost_usd_cents("anthropic/claude-opus-4.6", 50_000, 5_000) == 112


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
