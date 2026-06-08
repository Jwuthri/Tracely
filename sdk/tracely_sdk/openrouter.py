"""Drop-in OpenRouter tracing.

OpenRouter exposes an OpenAI-compatible chat-completions API at `https://openrouter.ai/api/v1`,
so this module is a thin convenience preset around `tracely_sdk.openai`: pass your OpenRouter key,
get a traced client pointed at the right base URL.

    from tracely_sdk.openrouter import OpenRouter            # a pre-wrapped, base-url-preset client
    client = OpenRouter(api_key=...)
    client.chat.completions.create(
        model="anthropic/claude-3.5-sonnet",
        messages=[...],
        extra_headers={"HTTP-Referer": "https://your.app", "X-Title": "Your App"},
    )

The `model` you pass is recorded verbatim (e.g. `anthropic/claude-3.5-sonnet`), so the backend can
attribute usage to the underlying provider for free.
"""

from __future__ import annotations

from typing import Any

from .openai import wrap_openai

try:
    import openai as _openai
except ImportError as e:  # pragma: no cover
    raise ImportError("tracely_sdk.openrouter requires the OpenAI SDK — pip install openai") from e

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def OpenRouter(*args: Any, **kwargs: Any) -> Any:
    """A traced `openai.OpenAI(...)` pre-pointed at OpenRouter."""
    kwargs.setdefault("base_url", DEFAULT_BASE_URL)
    return wrap_openai(_openai.OpenAI(*args, **kwargs))


def AsyncOpenRouter(*args: Any, **kwargs: Any) -> Any:
    """A traced `openai.AsyncOpenAI(...)` pre-pointed at OpenRouter."""
    kwargs.setdefault("base_url", DEFAULT_BASE_URL)
    return wrap_openai(_openai.AsyncOpenAI(*args, **kwargs))
