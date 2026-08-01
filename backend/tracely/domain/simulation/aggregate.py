"""Rolling emulated-conversation outcomes up into one gate verdict.

Two levels, and only the second one is a new policy:

**turns → conversation.** Already decided. `domain/evaluation/verdict.py` is the one roll-up
policy in the system: a run fails iff it has a `FAIL` on a non-advisory evaluator. A conversation
is just its turns' scores pooled, so this reuses `rollup_verdict` verbatim rather than inventing
a second rule that could drift from the trace badge and the threads dot.

**conversations → gate.** One knob: `min_pass_rate`. At the default `1.0` a suite behaves like a
test suite — any failing conversation blocks. Adversarial suites want it lower: an attack suite
of 50 probes will always land a few, and a gate that demands zero successful attacks forever is
a gate people mute. Expressing both as a single float keeps one code path.

`UNGRADED` is the load-bearing state. A conversation that ran but produced no scores (no
evaluator matched, no LLM key, judge errored) must never count as a pass — that is the same
false-green that made all-SKIP gates report success. It counts against the pass rate and, when
every conversation is ungraded, the gate is `NO_COVERAGE`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from tracely.domain.evaluation.verdict import rollup_verdict

# Float comparison slack: 9 of 10 conversations passing must satisfy min_pass_rate=0.9 even
# though 9/10 == 0.8999999999999999 in binary floating point.
_EPS = 1e-9


def user_text(recorded_input: str) -> str:
    """The user's actual words from a trace's recorded `input`.

    Traces frequently record the input as an envelope rather than plain text — `{"prompt": "..."}`
    from a bespoke API, `{"messages": [...]}` from a chat one. Importing a thread means replaying
    the user side against a live endpoint, so posting the envelope back verbatim would feed the
    agent a JSON blob it never saw in production. Unwrap the unambiguous shapes; anything else is
    returned untouched (and is editable in the UI).
    """
    text = (recorded_input or "").strip()
    # `"` included: a JSON-encoded string literal is still an envelope. Text that merely opens
    # with a quote (`"hello," she said`) fails to parse below and comes back untouched.
    if not text.startswith(("{", "[", '"')):
        return text
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text
    if isinstance(data, str):
        return data.strip()
    # A BARE message array — `[{"role": "system", …}, {"role": "user", …}]` — is as common as the
    # `{"messages": […]}` wrapper, and missing it imported the system prompt as the user's line.
    if isinstance(data, list):
        return _last_user_message(data) or text
    if isinstance(data, dict):
        messages = data.get("messages")
        if isinstance(messages, list):
            found = _last_user_message(messages)
            if found:
                return found
        for key in ("prompt", "input", "content", "message", "text", "query", "question"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return text


def _last_user_message(messages: list) -> str:
    """The last `role: user` message's text — what the trace was actually responding to.

    Content may be a plain string or the typed-block form (`[{"type": "text", "text": …}]`), so
    the text blocks are joined and non-text blocks (images, files) ignored.
    """
    for m in reversed(messages):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                str(b.get("text") or "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                return joined
    return ""


@dataclass
class ScenarioOutcome:
    """One emulated conversation's result. `trace_ids` are the per-turn traces (oldest first);
    `conversation_id` is the thread handle the UI opens."""

    scenario_id: str
    title: str
    conversation_id: str
    trace_ids: list[str] = field(default_factory=list)
    verdict: str = "SKIP"
    detail: dict = field(default_factory=dict)


def conversation_verdict(scores: Sequence[dict], advisory: Sequence[str]) -> str:
    """PASS / FAIL / UNGRADED for one emulated conversation, from every turn's scores pooled.

    Delegates the PASS/FAIL call to the single roll-up policy, with two additions:

    - "nothing graded this" is its own state rather than a silent pass.
    - `SKIP` scores are dropped *before* the roll-up. `rollup_verdict` reads any score at all as
      evidence the run was graded, so a conversation whose only scores were skipped expectations
      (no LLM key, or tool checks blind because the agent's spans never arrived) would come back
      PASS having checked nothing. Dropping them first makes that case UNGRADED, which counts
      against the pass rate instead of quietly clearing the gate.
    """
    graded = [s for s in scores if s.get("verdict") != "SKIP"]
    return rollup_verdict(graded, advisory) or "UNGRADED"


def gate_verdict(
    outcomes: Sequence[ScenarioOutcome], min_pass_rate: float = 1.0
) -> tuple[str, dict]:
    """Aggregate scenario outcomes into `(status, summary)`.

    Statuses mirror the existing gate vocabulary so the PR comment, commit status and CLI exit
    code need no new branches:

    - `PASS`        — pass rate met (or there are no scenarios configured yet).
    - `FAIL`        — pass rate missed.
    - `NO_COVERAGE` — scenarios exist but none produced a graded conversation. Blocking: a gate
      that tested nothing is not a green gate.
    """
    ran = [o for o in outcomes if o.verdict != "SKIP"]
    passed = sum(o.verdict == "PASS" for o in ran)
    failed = sum(o.verdict == "FAIL" for o in ran)
    ungraded = sum(o.verdict == "UNGRADED" for o in ran)
    rate = (passed / len(ran)) if ran else 0.0

    summary = {
        "total": len(outcomes),
        "ran": len(ran),
        "passed": passed,
        "failed": failed,
        "ungraded": ungraded,
        "skipped": len(outcomes) - len(ran),
        "pass_rate": round(rate, 4),
        "min_pass_rate": min_pass_rate,
    }

    if not outcomes:
        return "PASS", summary  # no scenarios for this agent yet — nothing to protect
    if not ran or ungraded == len(ran):
        return "NO_COVERAGE", summary
    return ("PASS" if rate >= min_pass_rate - _EPS else "FAIL"), summary
