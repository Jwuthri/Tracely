"""Drop-in Google GenAI (Gemini) tracing — the non-patching alternative to
`init(instrument=["google"])` (R13). Mirrors `tracely_sdk.openai` / `tracely_sdk.anthropic`:
wrap a client *instance*, no global patching.

    from tracely_sdk.google import Client                 # a pre-wrapped client
    client = Client(api_key=...)
    client.models.generate_content(model="gemini-2.0-flash", contents="hi")

    # or wrap one you already built:
    from tracely_sdk.google import wrap_google
    from google import genai
    client = wrap_google(genai.Client(api_key=...))

    # async path (client.aio.models.generate_content) is wrapped too.

Captures model · contents · output (text + function_calls) · token usage (incl. reasoning) ·
tool calls for non-streaming sync + async calls; emits the same attributes as the manual `llm()`
helper. Streaming methods (`generate_content_stream`) are intentionally left to the auto-
instrumentor path — install `openinference-instrumentation-google-genai` and call
`tracely.init()` if you need streaming capture."""

from __future__ import annotations

from typing import Any

from . import set_io, set_usage
from ._wrap import wrap_method

try:  # the real google-genai SDK is an optional dependency of this drop-in
    from google import genai as _genai
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "tracely_sdk.google requires the google-genai SDK — pip install google-genai"
    ) from e


def _capture(span: Any, resp: Any) -> None:
    """Best-effort capture of a (non-streaming) GenerateContentResponse onto the span."""
    try:
        blocks: list[dict[str, Any]] = []
        tool_names: list[str] = []
        # The new SDK exposes `response.text` (joined text) and `response.candidates[*].content.parts`.
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            cand = candidates[0]
            content = getattr(cand, "content", None)
            for p in getattr(content, "parts", None) or []:
                # parts can hold text, function_call, function_response, inline_data, …
                text = getattr(p, "text", None)
                fc = getattr(p, "function_call", None)
                if text:
                    blocks.append({"type": "text", "text": text})
                elif fc is not None:
                    name = getattr(fc, "name", None)
                    args = getattr(fc, "args", None)
                    if name:
                        tool_names.append(name)
                    blocks.append(
                        {"type": "function_call", "name": name, "args": _to_plain(args)}
                    )
                else:
                    blocks.append({"type": "unknown"})
            finish = getattr(cand, "finish_reason", None)
        else:
            text = getattr(resp, "text", None)
            if text:
                blocks.append({"type": "text", "text": text})
            finish = None
        # Also surface convenience `response.function_calls` if present and we missed it above.
        if not tool_names:
            for fc in getattr(resp, "function_calls", None) or []:
                name = getattr(fc, "name", None)
                if name:
                    tool_names.append(name)
        out: dict[str, Any] = {"role": "model", "content": blocks}
        if finish is not None:
            out["finish_reason"] = str(finish)
        set_io(span, output=out)
        if tool_names:
            span.set_attribute("tracely.tool_calls", tool_names)
        usage = getattr(resp, "usage_metadata", None)
        if usage:
            set_usage(
                span,
                input_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
                thinking_tokens=getattr(usage, "thoughts_token_count", None),
            )
    except Exception:  # never let trace capture break the caller's call
        pass


def _to_plain(v: Any) -> Any:
    """`function_call.args` is sometimes a proto MapComposite; coerce to a plain dict for JSON-safety."""
    try:
        return dict(v) if v is not None else None
    except Exception:
        return v


def _extract_contents(kwargs: dict) -> Any:
    return kwargs.get("contents")


def wrap_google(client: Any) -> Any:
    """Trace a google-genai `Client` *instance* by wrapping its `models.generate_content` (and the
    async `aio.models.generate_content`) on the instance only. Returns the same client. Idempotent."""
    models = getattr(client, "models", None)
    if models is not None:
        wrap_method(models, "generate_content", _capture, input_extractor=_extract_contents)
    aio = getattr(client, "aio", None)
    if aio is not None:
        aio_models = getattr(aio, "models", None)
        if aio_models is not None:
            wrap_method(
                aio_models, "generate_content", _capture, input_extractor=_extract_contents
            )
    return client


def Client(*args: Any, **kwargs: Any) -> Any:
    """`google.genai.Client(...)`, pre-wrapped for tracing."""
    return wrap_google(_genai.Client(*args, **kwargs))


class _GoogleGenaiProxy:
    """Mirrors the `google.genai` module but hands back traced clients."""

    Client = staticmethod(Client)

    def __getattr__(self, name: str) -> Any:
        return getattr(_genai, name)


genai = _GoogleGenaiProxy()
