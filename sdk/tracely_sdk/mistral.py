"""Drop-in Mistral tracing — the non-patching alternative to `init(instrument=["mistral"])` (R13).
Mirrors `tracely_sdk.openai` / `tracely_sdk.anthropic`: wrap a client *instance*, no global patching.

    from tracely_sdk.mistral import Mistral               # a pre-wrapped client
    client = Mistral(api_key=...)
    client.chat.complete(model="mistral-large-latest", messages=[...])

    # or wrap one you already built / the module import:
    from tracely_sdk.mistral import wrap_mistral, mistralai
    from mistralai import Mistral as _Mistral
    client = wrap_mistral(_Mistral(api_key=...))
    mistralai.Mistral(api_key=...).chat.complete(...)

Captures model · messages · output (text + tool_calls) · token usage for non-streaming sync + async
calls; emits the same attributes as the manual `llm()` helper. The Mistral 1.x SDK exposes a single
`Mistral` class with both sync (`chat.complete`) and async (`chat.complete_async`) methods — both
are wrapped on the same instance."""

from __future__ import annotations

from typing import Any

from . import set_io, set_usage
from ._wrap import wrap_method

try:  # the real mistralai SDK is an optional dependency of this drop-in
    import mistralai as _mistralai
    # mistralai 1.x exposes `Mistral` at the package root; 2.x moved it to `mistralai.client`.
    try:
        from mistralai import Mistral as _Mistral  # 1.x
    except ImportError:
        from mistralai.client import Mistral as _Mistral  # 2.x
except ImportError as e:  # pragma: no cover
    raise ImportError("tracely_sdk.mistral requires the Mistral SDK — pip install mistralai") from e


def _capture(span: Any, resp: Any) -> None:
    """Best-effort capture of a (non-streaming) ChatCompletionResponse onto the span."""
    try:
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return
        choice = choices[0]
        msg = getattr(choice, "message", None)
        out: dict[str, Any] = {"role": getattr(msg, "role", "assistant"), "content": getattr(msg, "content", None)}
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            dumped = []
            tool_names: list[str] = []
            for tc in tool_calls:
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", None) if fn else None
                arguments = getattr(fn, "arguments", None) if fn else None
                if name:
                    tool_names.append(name)
                dumped.append(
                    {
                        "id": getattr(tc, "id", None),
                        "type": getattr(tc, "type", "function"),
                        "function": {"name": name, "arguments": arguments},
                    }
                )
            out["tool_calls"] = dumped
            if tool_names:
                span.set_attribute("tracely.tool_calls", tool_names)
        finish = getattr(choice, "finish_reason", None)
        if finish:
            out["finish_reason"] = str(finish)
        set_io(span, output=out)
        usage = getattr(resp, "usage", None)
        if usage:
            set_usage(
                span,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            )
    except Exception:  # never let trace capture break the caller's call
        pass


def wrap_mistral(client: Any) -> Any:
    """Trace a `mistralai.Mistral` *instance* by wrapping its `chat.complete` and `chat.complete_async`
    on the instance only (no global patching). Returns the same client. Idempotent."""
    chat = getattr(client, "chat", None)
    if chat is None:
        return client
    for method in ("complete", "complete_async"):
        if hasattr(chat, method):
            wrap_method(chat, method, _capture)
    return client


def Mistral(*args: Any, **kwargs: Any) -> Any:
    """`mistralai.Mistral(...)`, pre-wrapped for tracing."""
    return wrap_mistral(_Mistral(*args, **kwargs))


class _MistralProxy:
    """Mirrors the `mistralai` module but hands back traced clients."""

    Mistral = staticmethod(Mistral)

    def __getattr__(self, name: str) -> Any:
        return getattr(_mistralai, name)


mistralai = _MistralProxy()
