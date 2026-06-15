"""Suggest a ready-to-create evaluator for a failure cluster's mechanism.

The output is shaped like an `/evaluators/generate` draft (`{name, description, kind, level,
config, rationale}`) — NOT a code snippet — so the cluster detail view can open it straight in
the Add Column editor (built-in structural check or LLM-judge rubric). There is no user-supplied-
Python evaluator kind, so a `def evaluate(ctx)` snippet had nowhere to go; these drafts map onto
checks the product can actually create.
"""

from __future__ import annotations

from typing import Any


def suggest_evaluator(cluster_label: str, taxonomy: str) -> dict[str, Any]:
    """Return a creatable evaluator draft for the cluster's failure mechanism.

    Three buckets, each mapping to an evaluator the product can create:
    - "not executed" / "consistency" -> the built-in `tool_consistency` structural check (flags a
      tool the model requested but never executed — the silent-failure case).
    - "error" -> the built-in `tool_success` structural check (flags any TOOL span at level=ERROR).
    - anything else (wrong output / hallucination) -> an LLM-judge faithfulness rubric (the basic
      judge auto-injects request / answer / tool results, so the rubric carries no placeholders).
    """
    tax = (taxonomy or "").lower()
    if "not executed" in tax or "consistency" in tax:
        return {
            "name": "Tool consistency",
            "description": "Fails when the model requested a tool that never executed.",
            "kind": "structural",
            "level": "AGENT_RUN",
            "config": {"check": "tool_consistency"},
            "rationale": (
                "This cluster is a silent tool failure — the model asked for a tool that never "
                "ran. The built-in Tool consistency check catches it on every run."
            ),
        }
    if "error" in tax:
        return {
            "name": "Tool success",
            "description": "Fails any step where a tool call errored.",
            "kind": "structural",
            "level": "TOOL",
            "config": {"check": "tool_success"},
            "rationale": (
                "This cluster is driven by tool calls erroring. The built-in Tool success check "
                "flags any errored tool step automatically."
            ),
        }
    return {
        "name": "Answer faithfulness",
        "description": "Flags answers that contradict, ignore, or fabricate beyond the tool results.",
        "kind": "llm_judge",
        "level": "AGENT_RUN",
        "config": {
            "prompt": (
                "You are checking whether the agent's final answer is faithful to its tool results "
                "and not fabricated. Give a LOW score when the answer contradicts, ignores, or "
                "invents detail beyond what the tool results support; give a HIGH score when every "
                "claim is grounded in the tool results or the user's own message."
            ),
            "output_type": "score",
            "threshold": 0.6,
        },
        "rationale": (
            "This cluster looks like wrong or unfaithful output. An LLM-judge faithfulness check "
            "scores each answer against its tool grounding."
        ),
    }
