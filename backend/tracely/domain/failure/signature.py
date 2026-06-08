"""Cheap structural failure signature — the ingest-time clustering key.

Drain3-flavored: failed-evaluator set + masked failure text (ids/numbers/quoted strings
redacted) → sha256 → stable cluster_key. Two failures with the same masked signature group
into the same `FailureCluster`. The semantic embedding pass (`services.failure_intel_service`)
replaces these later, but the cheap signature is what the worker computes on every failing
trace so the cluster appears immediately.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_MASK_PATTERNS = [
    (re.compile(r"\b[0-9a-f]{8,}\b", re.I), "<id>"),  # hex/uuids
    (re.compile(r"\b\d+(\.\d+)?\b"), "<n>"),           # numbers
    (re.compile(r"'[^']*'|\"[^\"]*\""), "<*>"),        # quoted strings
]

# Recognized evaluator score names -> human-readable taxonomy. Anything else falls back to
# the generic "execution: error" bucket.
_TAXONOMY = {
    "tracely.run.tool_consistency": "execution: tool not executed",
    "tracely.tool.success": "execution: tool error",
    "tracely.run.quality": "output: low quality",
    "tracely.run.latency_ms": "performance: latency",
    "tracely.run.outcome": "execution: error",
}


def mask(text: str) -> str:
    """Strip volatile bits so failures with the same shape but different ids/values collapse."""
    out = text
    for pat, repl in _MASK_PATTERNS:
        out = pat.sub(repl, out)
    return out.strip()


@dataclass(frozen=True, slots=True)
class FailureSignature:
    """The computed signature for a failing trace.

    `signature` is the raw masked text (a serialization of failed-eval names + masked errors).
    `key` is its sha256 prefix — the stable cluster_key. `label` is a short human-readable
    summary of the failure mode. `taxonomy` is the high-level bucket the UI groups by.
    """

    signature: str
    key: str
    label: str
    taxonomy: str

    @classmethod
    def compute(cls, eval_failures, spans: list[dict]) -> "FailureSignature":
        """Build a signature from the eval failures and the trace's spans.

        `eval_failures` is a list of objects with `.name` and `.comment` (EvalResult-shaped).
        """
        failed = sorted({f.name for f in eval_failures})
        comments = {mask(f.comment) for f in eval_failures if f.comment}
        for s in spans:
            if s.get("level") == "ERROR" and s.get("status_message"):
                comments.add(mask(s["status_message"]))
        comment_list = sorted(c for c in comments if c)

        sig = " || ".join(failed) + " ## " + " || ".join(comment_list)
        label = (comment_list[0] if comment_list else (failed[0] if failed else "failure"))[:200]
        taxonomy = next((_TAXONOMY[n] for n in failed if n in _TAXONOMY), "execution: error")
        key = hashlib.sha256(sig.encode()).hexdigest()[:16]
        return cls(signature=sig, key=key, label=label, taxonomy=taxonomy)
