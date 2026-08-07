"""The one LLM gateway: every chat-model call in Tracely goes through LangChain's
`create_agent` against OpenRouter.

- `get_chat_model()`  → a `ChatOpenAI` pointed at OpenRouter (`OPENROUTER_API_KEY`); model ids
  are OpenRouter-style `provider/model` (bare ids get an `openai/` prefix). When only the
  legacy `LLM_JUDGE_API_KEY`/`LLM_JUDGE_BASE_URL` are configured we keep honoring them (still
  through LangChain) so existing deployments don't lose the judge until they switch keys.
- `run_structured_agent()` → one-shot `create_agent(..., tools=[], response_format=Model)`
  call returning the validated structured response. This is THE primitive the judge, the
  metric generator, and the failure-intelligence agents build on.
- `use_project_key(project_id)` → a workspace can set its own OpenRouter key (Settings -> LLM
  key) so its eval spend bills to its own account instead of ours. Every project-scoped entry
  point (EvaluationService, FailureIntelService, MetaAnalysisService, RollingSummaryService, the
  evaluator-generation/model-list/cost routers) wraps its work in this; everything above —
  `get_chat_model`, `llm_enabled`, `list_models` — picks it up automatically via
  `effective_openrouter_key()`, so no call site below the wrap needs to know about it.

Heavy imports are lazy so the worker/API start even when the LLM stack isn't exercised.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import time
from typing import Any, Callable, Iterator, TypeVar

import structlog

from tracely.config import settings

log = structlog.get_logger()

T = TypeVar("T")

# Optional sink invoked with `{input_tokens, output_tokens, total_tokens, model}` after a call,
# so callers (the judge) can attribute LLM-eval token spend per evaluator.
UsageSink = Callable[[dict], None]

# The current request/task's project OpenRouter key, when `use_project_key()` is active — a
# per-request/per-task ambient override (same safety property `structlog.contextvars` already
# relies on here: each Celery task and each FastAPI request runs in its own copied Context, so
# concurrent projects never see each other's key).
_project_key_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tracely_project_openrouter_key", default=None
)

# Redis cache of the per-project key, so the eval hot path (one `use_project_key` per trace on
# ingest) doesn't hit Postgres every time. We cache the CIPHERTEXT, never the decrypted key:
# Redis here is the Celery broker, not a secrets store, so a Redis compromise alone must not
# hand over customers' OpenRouter keys — you'd still need SECRETS_ENCRYPTION_KEY. Fernet decrypt
# is microseconds; the Postgres round-trip was the actual cost.
_KEY_CACHE = "tracely:llm:key:{project}"
_KEY_CACHE_TTL_S = 300
_redis_client: Any = None


def _extract_usage(result: dict, model: str | None) -> dict:
    """Sum LangChain `usage_metadata` across the agent's AI messages → a token-usage dict.
    Zeros when a provider doesn't report usage (graceful — spend just shows as 0)."""
    inp = out = 0
    for m in result.get("messages", []) or []:
        um = getattr(m, "usage_metadata", None) or {}
        inp += int(um.get("input_tokens") or 0)
        out += int(um.get("output_tokens") or 0)
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "model": _normalize_model((model or settings.llm_judge_model).strip()),
    }

# The judge-model choices offered in the column UI. Curated (a 367-model dropdown is not a
# selector) and verified against the live OpenRouter catalog when a key is configured —
# unavailable ids are dropped, labels upgraded to OpenRouter's display names (so these labels are
# only what you see when the catalog is unreachable). Ordered cheap/fast → expensive within each
# provider, since a judge runs per trace and cost/latency is the real selection axis.
_CURATED_MODELS: list[tuple[str, str]] = [
    # OpenAI
    ("openai/gpt-5.6-luna", "OpenAI GPT-5.6 Luna"),
    ("openai/gpt-5.4-nano", "OpenAI GPT-5.4 Nano"),
    ("openai/gpt-5.4-mini", "OpenAI GPT-5.4 Mini"),
    ("openai/gpt-5.6-terra", "OpenAI GPT-5.6 Terra"),
    ("openai/gpt-5.4", "OpenAI GPT-5.4"),
    ("openai/gpt-5.6-sol", "OpenAI GPT-5.6 Sol"),
    # Google
    ("google/gemini-3.5-flash-lite", "Google Gemini 3.5 Flash Lite"),
    ("google/gemini-3.6-flash", "Google Gemini 3.6 Flash"),
    ("google/gemini-3.1-pro-preview", "Google Gemini 3.1 Pro"),
    # Anthropic
    ("anthropic/claude-haiku-4.5", "Anthropic Claude Haiku 4.5"),
    ("anthropic/claude-sonnet-5", "Anthropic Claude Sonnet 5"),
    ("anthropic/claude-opus-4.8", "Anthropic Claude Opus 4.8"),
    # xAI
    ("x-ai/grok-4.3", "xAI Grok 4.3"),
    ("x-ai/grok-4.5", "xAI Grok 4.5"),
    # Open-weights / low cost
    ("inclusionai/ling-3.0-flash:free", "Ling 3.0 Flash (free)"),
    ("openai/gpt-oss-120b", "OpenAI GPT-OSS 120B"),
    ("qwen/qwen3-32b", "Qwen3 32B"),
    ("minimax/minimax-m2.7", "MiniMax M2.7"),
]
# Deliberately NOT offered, despite being live on OpenRouter — both fail 100% of the time on the
# structured-output call every judge output type except schema-less `json` uses, so listing them
# would just yield columns that silently produce no scores (the judge swallows the error per
# evaluator). Verified against the live API on 2026-07-30:
#   qwen/qwen3.7-flash   — `structured_outputs: false`; Alibaba downgrades json_schema to
#                          json_object, which then 400s with "'messages' must contain the word
#                          'json' ... to use 'response_format' of type 'json_object'".
#   meta/muse-spark-1.1  — 400 "only `auto` is supported for `tool_choice`"; LangChain's
#                          `response_format` path pins a named/required tool to force the schema.
# Both DO work through `run_text_agent`, so revisit if a free-text-only judge path ever exists.
_STRUCTURED_OUTPUT_INCOMPATIBLE = ("qwen/qwen3.7-flash", "meta/muse-spark-1.1")
# Fallback prices in USD per 1M tokens, used when OpenRouter isn't reachable (or the model id
# isn't in OpenRouter's catalog) so the cost view doesn't read $0.00 in disconnected demos / dev.
# Live pricing always wins when the catalog is reachable. Generated from OpenRouter's catalog on
# 2026-07-30 — exact at that date, so re-pull rather than hand-editing when it drifts.
_FALLBACK_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "openai/gpt-5.6-luna":             (0.10,  0.60),
    "openai/gpt-5.4-nano":             (0.20,  1.25),
    "openai/gpt-5.4-mini":             (0.75,  4.50),
    "openai/gpt-5.6-terra":            (1.00,  6.00),
    "openai/gpt-5.4":                  (2.50, 15.00),
    "openai/gpt-5.6-sol":              (5.00, 30.00),
    "openai/gpt-oss-120b":             (0.037, 0.17),
    "google/gemini-3.5-flash-lite":    (0.30,  2.50),
    "google/gemini-3.6-flash":         (1.50,  7.50),
    "google/gemini-3.1-pro-preview":   (2.00, 12.00),
    "anthropic/claude-haiku-4.5":      (1.00,  5.00),
    "anthropic/claude-sonnet-5":       (2.00, 10.00),
    "anthropic/claude-opus-4.8":       (5.00, 25.00),
    "x-ai/grok-4.3":                   (1.25,  2.50),
    "x-ai/grok-4.5":                   (2.00,  6.00),
    "inclusionai/ling-3.0-flash:free": (0.00,  0.00),
    "qwen/qwen3.7-flash":              (0.03,  0.13),
    "qwen/qwen3-32b":                  (0.08,  0.28),
    "minimax/minimax-m2.7":            (0.25,  1.00),
    "meta/muse-spark-1.1":             (1.25,  4.25),
    # Not in the dropdown, but shipped as a `Settings` default (`meta_analysis_model`), so it can
    # show up in a score's recorded model and must still price correctly.
    "openai/gpt-5-mini":               (0.25,  2.00),
}
_MODELS_TTL_S = 3600
# `by_id`: {model_id: {"name": str, "prompt_per_mtok": float|None, "completion_per_mtok": float|None}}.
# Pricing is per 1M tokens (OpenRouter publishes per-token strings; we multiply by 1M on parse so
# every downstream consumer can do `tokens / 1_000_000 * per_mtok` symmetrically).
_models_cache: dict[str, Any] = {"ts": 0.0, "by_id": None}


def _fernet():
    """The Fernet cipher for workspace-secret encryption, keyed off `SECRETS_ENCRYPTION_KEY`
    (any string >=32 chars, SHA256-derived into a valid Fernet key — same UX as SESSION_SECRET,
    no separate keygen step). Raises when unconfigured; callers decide whether that's a hard
    error (saving a key) or a graceful degrade (reading one)."""
    if len(settings.secrets_encryption_key) < 32:
        raise RuntimeError("SECRETS_ENCRYPTION_KEY is not configured on this server (need >=32 chars)")
    from base64 import urlsafe_b64encode
    from hashlib import sha256

    from cryptography.fernet import Fernet

    return Fernet(urlsafe_b64encode(sha256(settings.secrets_encryption_key.encode()).digest()))


def encrypt_secret(plain: str) -> str:
    """Encrypt any workspace-supplied secret for storage. Raises RuntimeError if the server has no
    `SECRETS_ENCRYPTION_KEY` — save endpoints surface that directly rather than storing
    plaintext."""
    return _fernet().encrypt(plain.strip().encode()).decode()


def decrypt_secret(token: str) -> str | None:
    """None on any failure (bad/rotated encryption key, corrupt row) — a broken decrypt must
    degrade to 'no secret configured', never crash the caller."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, RuntimeError, ValueError) as exc:
        log.warning("secret_decrypt_failed", error=str(exc))
        return None


def encrypt_project_key(plain: str) -> str:
    """Encrypt a customer-supplied OpenRouter key for storage
    (`Project.openrouter_api_key_encrypted`)."""
    return encrypt_secret(plain)


def _decrypt_project_key(token: str) -> str | None:
    return decrypt_secret(token)


def effective_openrouter_key() -> str:
    """The OpenRouter key in effect right now.

    Inside `use_project_key()` that is the project's OWN key and nothing else: a workspace with
    no key configured gets `""`, never the server-wide key. Customers pay for their own eval
    spend. Outside any project scope (CLI scripts, health checks) the server key still applies.
    """
    scoped = _project_key_ctx.get()
    return settings.openrouter_api_key if scoped is None else scoped


def _redis():
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(settings.redis_url)
    return _redis_client


def _encrypted_key_for(project_id: str) -> str | None:
    """This project's ENCRYPTED OpenRouter token, or None when it has none.

    Redis-cached, including the negative result — "this workspace has no key of its own" is the
    common case and would otherwise pay a Postgres round-trip per evaluated trace. Any Redis
    error falls straight through to Postgres (cache is an optimization, never a dependency)."""
    cache_key = _KEY_CACHE.format(project=project_id)
    try:
        hit = _redis().get(cache_key)
        if hit is not None:
            return hit.decode() or None  # b"" is the cached "no key configured"
    except Exception:
        pass

    from tracely.infrastructure.db import repositories as repo
    from tracely.infrastructure.db.engine import SyncSessionLocal

    with SyncSessionLocal() as s:
        proj = repo.project_get(s, project_id)
        encrypted = (proj.openrouter_api_key_encrypted if proj else None) or None

    try:
        _redis().setex(cache_key, _KEY_CACHE_TTL_S, encrypted or "")
    except Exception:
        pass
    return encrypted


def invalidate_project_key(project_id: str) -> None:
    """Drop the cached token so a workspace setting/clearing its key takes effect on the next
    evaluation instead of up to `_KEY_CACHE_TTL_S` later. Best-effort: if Redis is unreachable the
    TTL is the backstop, so a missed invalidation self-heals in 5 minutes."""
    try:
        _redis().delete(_KEY_CACHE.format(project=project_id))
    except Exception as exc:
        log.warning("project_key_invalidate_failed", project_id=project_id, error=str(exc))


@contextlib.contextmanager
def use_project_key(project_id: str) -> Iterator[None]:
    """Scope every provider.py call inside the block to `project_id`'s own OpenRouter key when
    one is configured — server-wide key otherwise. Wrap any project-scoped entry point that ends
    up calling get_chat_model/run_structured_agent/run_text_agent/list_models/llm_enabled (the
    judge, failure intelligence, meta-analysis, rolling summary, evaluator generation).

    No key configured (or a failed lookup) means NO LLM for that work — it degrades exactly like
    an unconfigured deployment (`llm_enabled()` false) rather than silently spending our credit.
    """
    key: str | None = None
    try:
        encrypted = _encrypted_key_for(project_id)
        if encrypted:
            key = _decrypt_project_key(encrypted)
    except Exception as exc:  # fail closed: a lookup hiccup must not spend the server key
        log.warning("project_key_lookup_failed", project_id=project_id, error=str(exc))

    token = _project_key_ctx.set(key or "")  # "" = scoped, no key (distinct from None = unscoped)
    try:
        yield
    finally:
        _project_key_ctx.reset(token)


def project_scoped() -> bool:
    """True inside `use_project_key()` — i.e. server-wide credentials do not apply here."""
    return _project_key_ctx.get() is not None


def llm_enabled() -> bool:
    """Whether an LLM credential applies to the work being done right now — the project's own
    OpenRouter key inside `use_project_key()`, the server-wide keys outside it."""
    if project_scoped():
        return bool(effective_openrouter_key())
    return bool(settings.openrouter_api_key or settings.llm_judge_api_key)


def _normalize_model(model: str) -> str:
    """OpenRouter ids are `provider/model`; bare OpenAI-style ids get the `openai/` prefix."""
    return model if "/" in model else f"openai/{model}"


def default_model_id() -> str:
    """The judge model used when an evaluator doesn't pick one (normalized OpenRouter id)."""
    return _normalize_model(settings.llm_judge_model.strip())


def _per_mtok(raw: Any) -> float | None:
    """OpenRouter's `pricing.prompt`/`pricing.completion` are USD-per-token strings (e.g.
    "0.00000015" = $0.15/Mtok). Convert to USD-per-million-tokens (the unit our cost math uses).
    None for free/missing fields so 'unknown price' stays distinct from '$0.00'."""
    try:
        v = float(raw)
        return v * 1_000_000.0 if v > 0 else None
    except (TypeError, ValueError):
        return None


def _openrouter_models() -> dict[str, dict]:
    """`{model_id: {name, prompt_per_mtok, completion_per_mtok}}` from OpenRouter's /models,
    cached for an hour. On a failed refresh the last-known catalog keeps serving (with a 60s
    retry cooldown so outages don't stack 10s-timeout fetches on every modal open). Empty when
    no key is configured — callers fall back to the curated labels + static pricing table."""
    now = time.monotonic()
    if _models_cache["by_id"] is not None and now - _models_cache["ts"] < _MODELS_TTL_S:
        return _models_cache["by_id"]
    key = effective_openrouter_key()
    if not key:
        return {}
    try:
        import httpx

        resp = httpx.get(
            f"{settings.openrouter_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        by_id: dict[str, dict] = {}
        for m in resp.json().get("data", []):
            mid = m.get("id")
            if not mid:
                continue
            pricing = m.get("pricing") or {}
            by_id[str(mid)] = {
                "name": str(m.get("name") or mid),
                "prompt_per_mtok": _per_mtok(pricing.get("prompt")),
                "completion_per_mtok": _per_mtok(pricing.get("completion")),
            }
        _models_cache.update(ts=now, by_id=by_id)
        return by_id
    except Exception as exc:
        log.warning("openrouter_models_fetch_failed", error=str(exc))
        # serve stale (or nothing) and retry in 60s instead of on every request
        _models_cache["ts"] = now - _MODELS_TTL_S + 60
        return _models_cache["by_id"] or {}


def _openrouter_model_names() -> dict[str, str]:
    """Back-compat shim: `{model_id: display_name}` projected from `_openrouter_models()`."""
    return {mid: info["name"] for mid, info in _openrouter_models().items()}


def model_pricing(model_id: str) -> tuple[float | None, float | None]:
    """`(prompt_per_mtok, completion_per_mtok)` in USD per 1M tokens for `model_id`.

    Priority: live OpenRouter catalog → static fallback table → `(None, None)` for unknown
    models. Normalizes bare ids the same way `get_chat_model` does (`openai/` prefix), so callers
    can pass whatever the judge stamped on the score metadata."""
    mid = _normalize_model((model_id or "").strip())
    if not mid:
        return None, None
    live = _openrouter_models().get(mid)
    if live:
        return live.get("prompt_per_mtok"), live.get("completion_per_mtok")
    fb = _FALLBACK_PRICING_USD_PER_MTOK.get(mid)
    if fb:
        return fb
    return None, None


def estimate_cost_usd_cents(model_id: str, input_tokens: int, output_tokens: int) -> int:
    """Per-call cost in **integer USD cents** (no floats stored downstream → no rounding drift).
    Returns 0 when pricing is unknown — caller's responsibility to surface "no price" distinctly."""
    pin, pout = model_pricing(model_id)
    if pin is None and pout is None:
        return 0
    dollars = (input_tokens * (pin or 0.0) + output_tokens * (pout or 0.0)) / 1_000_000.0
    return int(round(dollars * 100))


def list_models() -> list[dict[str, str]]:
    """The curated judge-model choices for the evaluator UI: `[{id, label}, …]`. Verified
    against the live OpenRouter catalog when reachable; the static list otherwise — narrowed to
    `openai/*` when only the legacy direct OpenAI-compatible endpoint is configured (other
    providers' ids can't be served there)."""
    curated = _CURATED_MODELS
    if not effective_openrouter_key():
        # Legacy direct OpenAI-compatible endpoint: only ids api.openai.com actually serves.
        # `openai/gpt-oss-*` is open-weights hosted by third parties — its id starts with
        # `openai/` but offering it here would hand the user a model that 404s at judge time.
        curated = [
            (mid, label)
            for mid, label in curated
            if mid.startswith("openai/") and not mid.startswith("openai/gpt-oss")
        ]
    available = _openrouter_model_names()
    if available:
        out = [
            {"id": mid, "label": available.get(mid, label)}
            for mid, label in curated
            if mid in available
        ]
        if out:
            return out
    return [{"id": mid, "label": label} for mid, label in curated]


def get_chat_model(model: str | None = None, temperature: float = 0.0):
    """A LangChain chat model on OpenRouter (or the legacy OpenAI-compatible fallback)."""
    from langchain_openai import ChatOpenAI

    name = (model or settings.llm_judge_model).strip()
    key = effective_openrouter_key()
    if not key and project_scoped():
        raise RuntimeError(
            "This workspace has no OpenRouter API key. Add one in Settings -> OpenRouter key to "
            "run LLM evaluations, clustering and scenario gates."
        )
    if key:
        return ChatOpenAI(
            model=_normalize_model(name),
            api_key=key,
            base_url=settings.openrouter_base_url,
            temperature=temperature,
            # Always bounded — see `Settings.llm_max_output_tokens`. Without it OpenRouter reserves
            # credit for the provider's default 64k and rejects the call outright.
            max_tokens=settings.llm_max_output_tokens,
        )
    # Legacy direct endpoint: OpenAI-style bare model ids (strip an OpenRouter-style prefix).
    return ChatOpenAI(
        model=name.removeprefix("openai/"),
        api_key=settings.llm_judge_api_key,
        base_url=settings.llm_judge_base_url,
        temperature=temperature,
        max_tokens=settings.llm_max_output_tokens,
    )


def _invoke(agent, prompt: str, thread_id: str | None = None) -> dict[str, Any]:
    """Run the agent, translating one badly-disguised provider failure into a readable error.

    `thread_id` addresses a checkpointed conversation: LangGraph loads that thread's messages,
    appends this one, and persists the result — so we send only the new item and the model sees
    the whole transcript, with a byte-identical prefix the provider can cache.

    OpenRouter reports some failures — credit exhaustion above all — as HTTP **200** with an
    `{"error": …}` body and no `choices`. The OpenAI SDK's parser then trips over `choices=None`
    and raises `TypeError: 'NoneType' object is not iterable`, which tells an operator nothing and
    reads like a Tracely bug. The judge swallows exceptions per-evaluator, so the visible symptom
    is simply "no scores appeared" — worth spending a few lines to name the real cause."""
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None
    try:
        return agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config)
    except TypeError as exc:
        if "NoneType" in str(exc):
            raise RuntimeError(
                "LLM provider returned an error body instead of a completion (no `choices`). "
                "Most often OpenRouter credit exhaustion — check the balance at "
                "https://openrouter.ai/settings/credits. Lowering LLM_MAX_OUTPUT_TOKENS also "
                f"reduces the credit OpenRouter reserves per call. [{exc}]"
            ) from exc
        raise


@contextlib.contextmanager
def _recorded(prompt: str, system_prompt: str | None, model: str | None) -> Iterator[list]:
    """Log this call into the active introspection Recording, if one is open.

    This is the whole reason every LLM call is funnelled through this module: hooking here means
    the judge's prompt, the attacker's reasoning and the grader's verdict are all captured with no
    per-caller wiring. Yields a one-slot list the caller fills with `(text, usage)`; an exception
    is recorded as the step's error and re-raised untouched.
    """
    from tracely.domain import introspection

    rec = introspection.active()
    if rec is None:
        yield []
        return
    start_ns = time.time_ns()
    sink: list = []
    label = model or settings.llm_judge_model
    try:
        yield sink
    except Exception as exc:
        # The error IS this call's output. Recording it only as the span's error status left the
        # OUTPUT cell blank, so a judge failing on every call looked identical to one that simply
        # had nothing to say — a whole eval recording of empty cells and no reason anywhere in it.
        rec.add(label, input=_prompt_text(system_prompt, prompt),
                output=json.dumps({"error": str(exc)[:2000]}, indent=2, ensure_ascii=False),
                error=str(exc)[:500], model=label, start_ns=start_ns)
        raise
    text, usage = (sink[0] if sink else ("", {}))
    rec.add(
        label, input=_prompt_text(system_prompt, prompt), output=str(text)[:20000],
        model=label, tokens=usage or {}, start_ns=start_ns,
    )


def _prompt_text(system_prompt: str | None, prompt: str) -> str:
    """What actually went to the model — system rubric included, because 'why did the judge say
    that' is nearly always answered by the system half."""
    if system_prompt:
        return f"[system]\n{system_prompt}\n\n[user]\n{prompt}"
    return prompt


def run_structured_agent(
    prompt: str,
    *,
    response_format: type[T],
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    on_usage: UsageSink | None = None,
    chat_id: str | None = None,
) -> T:
    """One `create_agent` invocation with a structured response schema. Returns the validated
    pydantic instance; raises on transport/validation errors (callers decide whether a failed
    grade is skipped or surfaced). `on_usage` (optional) receives this call's token usage.

    `chat_id` continues a durable conversation instead of asking a fresh question: the rubric and
    every earlier item→verdict pair are already on that thread, so only `prompt` goes over the
    wire and the cached prefix does the rest. Without a reachable checkpointer it degrades to the
    one-shot call — a lost transcript is worth less than a lost grade."""
    from langchain.agents import create_agent

    checkpointer = _checkpointer_for(chat_id)
    agent = create_agent(
        get_chat_model(model, temperature),
        tools=[],
        system_prompt=system_prompt,
        response_format=response_format,
        **({"checkpointer": checkpointer} if checkpointer else {}),
    )
    with _recorded(prompt, system_prompt, model) as sink:
        result = _invoke(agent, prompt, chat_id if checkpointer else None)
        usage = _extract_usage(result, model)
        structured = result["structured_response"]
        sink.append((_dump(structured), usage))
    if on_usage is not None:
        on_usage(usage)
    return structured


def _checkpointer_for(chat_id: str | None):
    """The Postgres checkpointer when this call belongs to a conversation, else None."""
    if not chat_id:
        return None
    from tracely.infrastructure.llm.checkpointer import get_checkpointer

    return get_checkpointer()


def _dump(value: Any) -> str:
    """A structured response as readable text for the recording."""
    dump = getattr(value, "model_dump_json", None)
    if callable(dump):
        try:
            return dump(indent=2)
        except Exception:
            pass
    return str(value)


def run_text_agent(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    on_usage: UsageSink | None = None,
) -> str:
    """One `create_agent` invocation returning the final message text — for free-form outputs
    (the `json` evaluator output type, where the rubric defines the object shape). `on_usage`
    (optional) receives this call's token usage."""
    from langchain.agents import create_agent

    agent = create_agent(
        get_chat_model(model, temperature), tools=[], system_prompt=system_prompt
    )
    with _recorded(prompt, system_prompt, model) as sink:
        result = _invoke(agent, prompt)
        usage = _extract_usage(result, model)
        content = result["messages"][-1].content
        text = content if isinstance(content, str) else "".join(
            # content blocks ([{type:"text", text}, …]) — join the text parts
            part.get("text", "") for part in content if isinstance(part, dict)
        )
        sink.append((text, usage))
    if on_usage is not None:
        on_usage(usage)
    return text
