"""Shared machinery for the non-patching drop-ins (`tracely_sdk.openai`, `tracely_sdk.anthropic`).

`wrap_method(resource, name, capture)` replaces `resource.<name>` with a version that opens a
GENERATION span around the call — on the *instance* only, so nothing is patched globally. The
provider-specific `capture(span, response)` records output/usage/tool-calls. Sync + async; idempotent
(re-wrapping is a no-op); streaming calls are passed through (the request is still recorded)."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from . import llm, set_io


def wrap_method(resource: Any, name: str, capture: Callable[[Any, Any], None]) -> None:
    original = getattr(resource, name)
    # our own sentinel — NOT __wrapped__, which providers' own decorators (e.g. openai's
    # @required_args) already set, which would make us think it's already traced.
    if getattr(original, "_tracely_wrapped", False):
        return

    def _open(kwargs: dict) -> Any:
        cm = llm(kwargs.get("model", "") or "")
        span = cm.__enter__()
        if kwargs.get("messages") is not None:
            set_io(span, input=kwargs["messages"])
        return cm, span

    if inspect.iscoroutinefunction(original):

        @functools.wraps(original)
        async def traced(*args: Any, **kwargs: Any) -> Any:
            cm, span = _open(kwargs)
            try:
                resp = await original(*args, **kwargs)
            except BaseException as e:
                cm.__exit__(type(e), e, e.__traceback__)
                raise
            if not kwargs.get("stream"):
                capture(span, resp)
            cm.__exit__(None, None, None)
            return resp
    else:

        @functools.wraps(original)
        def traced(*args: Any, **kwargs: Any) -> Any:
            cm, span = _open(kwargs)
            try:
                resp = original(*args, **kwargs)
            except BaseException as e:
                cm.__exit__(type(e), e, e.__traceback__)
                raise
            if not kwargs.get("stream"):
                capture(span, resp)
            cm.__exit__(None, None, None)
            return resp

    traced._tracely_wrapped = True  # type: ignore[attr-defined]
    setattr(resource, name, traced)
