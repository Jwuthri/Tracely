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

from typing import Any, TypeVar

from tracely.config import settings

T = TypeVar("T")


def llm_enabled() -> bool:
    """Whether any judge/agent LLM credential is configured."""
    return bool(settings.openrouter_api_key or settings.llm_judge_api_key)


def _normalize_model(model: str) -> str:
    """OpenRouter ids are `provider/model`; bare OpenAI-style ids get the `openai/` prefix."""
    return model if "/" in model else f"openai/{model}"


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
) -> T:
    """One `create_agent` invocation with a structured response schema. Returns the validated
    pydantic instance; raises on transport/validation errors (callers decide whether a failed
    grade is skipped or surfaced)."""
    from langchain.agents import create_agent

    agent = create_agent(
        get_chat_model(model, temperature),
        tools=[],
        system_prompt=system_prompt,
        response_format=response_format,
    )
    result: dict[str, Any] = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return result["structured_response"]


def run_text_agent(
    prompt: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    temperature: float = 0.0,
) -> str:
    """One `create_agent` invocation returning the final message text — for free-form outputs
    (the `json` evaluator output type, where the rubric defines the object shape)."""
    from langchain.agents import create_agent

    agent = create_agent(
        get_chat_model(model, temperature), tools=[], system_prompt=system_prompt
    )
    result: dict[str, Any] = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    content = result["messages"][-1].content
    if isinstance(content, str):
        return content
    # content blocks ([{type:"text", text}, …]) — join the text parts
    return "".join(
        part.get("text", "") for part in content if isinstance(part, dict)
    )
