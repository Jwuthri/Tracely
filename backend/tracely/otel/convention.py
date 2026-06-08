"""Detect which message convention a span used. Recorded in metadata for drift tracking
(R14/D4) — `gen_ai.*` is experimental and migrating from legacy flat to structured."""

from __future__ import annotations

from typing import Any


def _convention(attrs: dict[str, Any]) -> str:
    def pre(*prefixes: str) -> bool:
        return any(k.startswith(prefixes) for k in attrs)

    if "gen_ai.input.messages" in attrs or "gen_ai.output.messages" in attrs:
        return "gen_ai/structured"
    if pre("gen_ai.prompt", "gen_ai.completion"):  # bare legacy string or .<i> indexed
        return "gen_ai/legacy"
    if (
        pre("llm.input_messages.", "llm.output_messages.")
        or "llm.model_name" in attrs
        or "openinference.span.kind" in attrs
    ):
        return "openinference"
    if pre("gen_ai."):  # gen_ai.* present but no recognizable message shape
        return "gen_ai/other"
    if pre("tracely.input", "tracely.output", "tracely.observation.type"):
        return "tracely/manual"
    return "unknown"
