"""Drop-in xAI (Grok) tracing.

xAI's API is OpenAI-compatible — the only difference from a vanilla OpenAI client is the
`base_url`. So this module is a thin convenience preset around `tracely_sdk.openai`: pass your
xAI key, get a traced client pointed at `https://api.x.ai/v1`.

    from tracely_sdk.xai import Grok                          # a pre-wrapped, base-url-preset client
    client = Grok(api_key=...)
    client.chat.completions.create(model="grok-3-latest", messages=[...])

    # or wrap an OpenAI() you already built — anything sent to `https://api.x.ai/v1`:
    from tracely_sdk.openai import wrap_openai
    from openai import OpenAI
    client = wrap_openai(OpenAI(api_key=..., base_url="https://api.x.ai/v1"))
"""

from __future__ import annotations

from typing import Any

from .openai import wrap_openai

try:
    import openai as _openai
except ImportError as e:  # pragma: no cover
    raise ImportError("tracely_sdk.xai requires the OpenAI SDK — pip install openai") from e

DEFAULT_BASE_URL = "https://api.x.ai/v1"


def Grok(*args: Any, **kwargs: Any) -> Any:
    """A traced `openai.OpenAI(...)` pre-pointed at xAI's API (Grok)."""
    kwargs.setdefault("base_url", DEFAULT_BASE_URL)
    return wrap_openai(_openai.OpenAI(*args, **kwargs))


def AsyncGrok(*args: Any, **kwargs: Any) -> Any:
    """A traced `openai.AsyncOpenAI(...)` pre-pointed at xAI's API (Grok)."""
    kwargs.setdefault("base_url", DEFAULT_BASE_URL)
    return wrap_openai(_openai.AsyncOpenAI(*args, **kwargs))


# Aliases — `XAI` reads cleaner in some codebases than `Grok`.
XAI = Grok
AsyncXAI = AsyncGrok
