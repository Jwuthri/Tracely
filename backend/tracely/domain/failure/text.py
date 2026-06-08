"""Failure-text helpers for the semantic (embedding) clustering stage.

`embedding_text` produces a TERSE mechanism-focused string for the clusterer — user input /
domain are intentionally excluded so runs group by failure MECHANISM, not by topic.

`summarize_failure` produces a FULL-CONTEXT block for the LLM analysis agent + UI display.
"""

from __future__ import annotations

from tracely.domain.traces.spans import FailureFacts, failure_facts


def embedding_text(spans: list[dict]) -> str:
    """Terse mechanism-focused text for the embedding clusterer. The user input / domain is
    deliberately omitted so two unrelated questions hitting the same bug land in the same cluster,
    and the same question failing two different ways does NOT. Error messages stay in so the
    embedder can sub-group error classes (e.g. 'upstream timeout' near 'gateway timed out')."""
    f = failure_facts(spans)
    return _embedding_text_from_facts(f)


def _embedding_text_from_facts(f: FailureFacts) -> str:
    lines = []
    if f.error_messages:
        lines.append("tool execution error: " + "; ".join(f.error_messages))
    if f.missing_tools:
        lines.append("requested but not executed: " + ", ".join(f.missing_tools))
    if not lines:
        lines.append("incorrect or low-quality answer: " + (f.agent_answer or "")[:160])
    return " | ".join(lines)


def summarize_failure(
    spans: list[dict], reasons: list[tuple[str, str]] | None = None
) -> str:
    """Full-context block for the ANALYSIS agent + UI display. Leads with the normalized failure
    mode, then the evaluator verdicts that flagged it (ground truth for *why* it failed), the
    tool results, and finally the input/answer context."""
    f = failure_facts(spans)
    tool_results = [
        f"{s.get('name')} -> {s.get('output')}"
        for s in spans
        if s.get("type") == "TOOL" and s.get("output")
    ]
    modes = []
    if f.error_messages:
        modes.append("tool execution error")
    if f.missing_tools:
        modes.append("requested tool never executed")
    if not modes:
        modes.append("incorrect or low-quality output")

    parts = ["FAILURE MODE: " + "; ".join(modes)]
    if reasons:
        parts.append("Detected by: " + "; ".join(f"{n}: {c}" if c else n for n, c in reasons))
    if f.error_messages:
        parts.append("Errors: " + "; ".join(f.error_messages))
    if f.missing_tools:
        parts.append(f"Requested but never executed: {f.missing_tools}")
    if tool_results:
        parts.append("Tool results: " + " | ".join(tool_results))
    parts += [
        f"Tools requested: {f.tools_requested} | executed: {f.tools_executed}",
        f"User input: {f.user_input}",
        f"Agent answer: {f.agent_answer}",
    ]
    return "\n".join(parts)[:3000]
