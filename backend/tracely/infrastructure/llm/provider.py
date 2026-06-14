"""The one LLM gateway: every chat-model call in Tracely goes through LangChain's
`create_agent` against OpenRouter.

- `get_chat_model()`  → a `ChatOpenAI` pointed at OpenRouter (`OPENROUTER_API_KEY`); model ids
  are OpenRouter-style `provider/model` (bare ids get an `openai/` prefix). When only the
  legacy `LLM_JUDGE_API_KEY`/`LLM_JUDGE_BASE_URL` are configured we keep honoring them (still
  through LangChain) so existing deployments don't lose the judge until they switch keys.
- `run_structured_agent()` → one-shot `create_agent(..., tools=[], response_format=Model)`
  call returning the validated structured response. This is THE primitive the judge, the
  metric generator, and the failure-intelligence agents build on.

Heavy imports are lazy so the worker/API start even when the LLM stack isn't exercised.
"""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

import structlog

from tracely.config import settings

log = structlog.get_logger()

T = TypeVar("T")

# Optional sink invoked with `{input_tokens, output_tokens, total_tokens, model}` after a call,
# so callers (the judge) can attribute LLM-eval token spend per evaluator.
UsageSink = Callable[[dict], None]


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

# The judge-model choices offered in the column UI. Curated (a 300-model dropdown is not a
# selector) and verified against the live OpenRouter catalog when a key is configured —
# unavailable ids are dropped, labels upgraded to OpenRouter's display names.
_CURATED_MODELS: list[tuple[str, str]] = [
    ("openai/gpt-5.4-nano", "GPT-5.4 Nano — fast & cheap"),
    ("openai/gpt-5.4-mini", "GPT-5.4 Mini"),
    ("openai/gpt-5.1", "GPT-5.1"),
    ("openai/gpt-5-mini", "GPT-5 Mini"),
    ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5"),
    ("anthropic/claude-fable-5", "Claude Fable 5"),
    ("anthropic/claude-opus-4.6", "Claude Opus 4.6"),
    ("google/gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro"),
    ("meta-llama/llama-4-maverick", "Llama 4 Maverick"),
    ("mistralai/mistral-large-2512", "Mistral Large 3"),
]
_MODELS_TTL_S = 3600
_models_cache: dict[str, Any] = {"ts": 0.0, "by_id": None}


def llm_enabled() -> bool:
    """Whether any judge/agent LLM credential is configured."""
    return bool(settings.openrouter_api_key or settings.llm_judge_api_key)


def _normalize_model(model: str) -> str:
    """OpenRouter ids are `provider/model`; bare OpenAI-style ids get the `openai/` prefix."""
    return model if "/" in model else f"openai/{model}"


def default_model_id() -> str:
    """The judge model used when an evaluator doesn't pick one (normalized OpenRouter id)."""
    return _normalize_model(settings.llm_judge_model.strip())


def _openrouter_model_names() -> dict[str, str]:
    """`{model_id: display_name}` from OpenRouter's /models, cached for an hour. On a failed
    refresh the last-known catalog keeps serving (with a 60s retry cooldown so outages don't
    stack 10s-timeout fetches on every modal open). Empty when no key is configured — callers
    fall back to the static curated labels."""
    now = time.monotonic()
    if _models_cache["by_id"] is not None and now - _models_cache["ts"] < _MODELS_TTL_S:
        return _models_cache["by_id"]
    if not settings.openrouter_api_key:
        return {}
    try:
        import httpx

        resp = httpx.get(
            f"{settings.openrouter_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        by_id = {
            str(m.get("id")): str(m.get("name") or m.get("id"))
            for m in resp.json().get("data", [])
            if m.get("id")
        }
        _models_cache.update(ts=now, by_id=by_id)
        return by_id
    except Exception as exc:
        log.warning("openrouter_models_fetch_failed", error=str(exc))
        # serve stale (or nothing) and retry in 60s instead of on every request
        _models_cache["ts"] = now - _MODELS_TTL_S + 60
        return _models_cache["by_id"] or {}


def list_models() -> list[dict[str, str]]:
    """The curated judge-model choices for the evaluator UI: `[{id, label}, …]`. Verified
    against the live OpenRouter catalog when reachable; the static list otherwise — narrowed to
    `openai/*` when only the legacy direct OpenAI-compatible endpoint is configured (other
    providers' ids can't be served there)."""
    curated = _CURATED_MODELS
    if not settings.openrouter_api_key:
        curated = [(mid, label) for mid, label in curated if mid.startswith("openai/")]
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
    if settings.openrouter_api_key:
        return ChatOpenAI(
            model=_normalize_model(name),
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            temperature=temperature,
        )
    # Legacy direct endpoint: OpenAI-style bare model ids (strip an OpenRouter-style prefix).
    return ChatOpenAI(
        model=name.removeprefix("openai/"),
        api_key=settings.llm_judge_api_key,
        base_url=settings.llm_judge_base_url,
        temperature=temperature,
    )


def run_structured_agent(
    prompt: str,
    *,
    response_format: type[T],
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    on_usage: UsageSink | None = None,
) -> T:
    """One `create_agent` invocation with a structured response schema. Returns the validated
    pydantic instance; raises on transport/validation errors (callers decide whether a failed
    grade is skipped or surfaced). `on_usage` (optional) receives this call's token usage."""
    from langchain.agents import create_agent

    agent = create_agent(
        get_chat_model(model, temperature),
        tools=[],
        system_prompt=system_prompt,
        response_format=response_format,
    )
    result: dict[str, Any] = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    if on_usage is not None:
        on_usage(_extract_usage(result, model))
    return result["structured_response"]


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
    result: dict[str, Any] = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    if on_usage is not None:
        on_usage(_extract_usage(result, model))
    content = result["messages"][-1].content
    if isinstance(content, str):
        return content
    # content blocks ([{type:"text", text}, …]) — join the text parts
    return "".join(
        part.get("text", "") for part in content if isinstance(part, dict)
    )
