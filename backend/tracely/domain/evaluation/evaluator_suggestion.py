"""Suggest a starting-point evaluator that would catch a given failure cluster's mechanism.

Pure data → code: the output matches the real evaluator interface, so the suggestion is a
usable draft (not just illustrative). Used by the cluster detail view to show "if you want to
prevent this from happening again, paste this in".
"""

from __future__ import annotations

import re
from typing import Any


def _name_from_label(label: str) -> str:
    """Slugify a cluster label into an evaluator identifier (lowercase, underscores)."""
    base = re.sub(r"[^a-z0-9]+", "_", (label or "detected_failure").lower()).strip("_")
    return (base or "detected_failure")[:48]


def suggest_evaluator(cluster_label: str, taxonomy: str) -> dict[str, Any]:
    """Return a dict shaped `{name, language, code}` — drop-in for the Evaluator editor.

    Three buckets:
    - "not executed" / "consistency" mechanisms -> a Python check that flags requested-but-not-
      executed tools (the silent-failure case).
    - "error" mechanisms -> a Python check that flags any TOOL span with `level=ERROR`.
    - Anything else (wrong output / hallucination) -> an LLM-judge rubric.
    """
    name = _name_from_label(cluster_label)
    tax = (taxonomy or "").lower()
    if "not executed" in tax or "consistency" in tax:
        code = (
            "def evaluate(ctx):\n"
            '    """Catch runs where a tool was requested by the model but never executed."""\n'
            "    requested = {t for s in ctx.spans for t in (s.get('tool_call_names') or [])}\n"
            "    executed = {s.get('name') for s in ctx.spans if s.get('type') == 'TOOL'}\n"
            "    missing = sorted(requested - executed)\n"
            f"    return {{'name': '{name}', 'verdict': 'FAIL' if missing else 'PASS',\n"
            "            'comment': f'requested but not executed: {missing}' if missing else ''}"
        )
        return {"name": name, "language": "python", "code": code}
    if "error" in tax:
        code = (
            "def evaluate(ctx):\n"
            '    """Catch runs where a tool call errored."""\n'
            "    errs = [s.get('name') for s in ctx.spans if s.get('type') == 'TOOL' and s.get('level') == 'ERROR']\n"
            f"    return {{'name': '{name}', 'verdict': 'FAIL' if errs else 'PASS',\n"
            "            'comment': f'tool error: {errs}' if errs else ''}"
        )
        return {"name": name, "language": "python", "code": code}
    prompt = (
        "You are checking whether the agent's final answer is faithful to its tool results and not "
        "fabricated.\nReturn strict JSON {\"score\": 0..1, \"reason\": \"...\"}.\n\n"
        "User request:\n{{input}}\n\nTool results:\n{{tool_outputs}}\n\nAgent answer:\n{{output}}\n\n"
        "Score LOW if the answer contradicts, ignores, or invents detail beyond the tool results."
    )
    return {"name": name, "language": "prompt", "code": prompt}
