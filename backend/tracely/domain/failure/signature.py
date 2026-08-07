"""Cheap structural failure signature — the ingest-time clustering key.

Drain3-flavored: failed-evaluator set + masked failure text (ids/numbers/quoted strings
redacted) → sha256 → stable cluster_key. Two failures with the same masked signature group
into the same `FailureCluster`. The semantic embedding pass (`services.failure_intel_service`)
replaces these later, but the cheap signature is what the worker computes on every failing
trace so the cluster appears immediately.

Exact hashing alone splits LLM-judge prose into one cluster per trace ("the response is not
helpful" vs "the answer is not a helpful reply"). So the key is only the FIRST lookup: the
clusterer falls back to a token-overlap match (`matches` below). Near-identical text always
merges — the failed-evaluator set only separates clusters whose text is genuinely different.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_MASK_PATTERNS = [
    (re.compile(r"\b[0-9a-f]{8,}\b", re.I), "<id>"),  # hex/uuids
    (re.compile(r"\b\d+(\.\d+)?\b"), "<n>"),  # numbers
    (re.compile(r"'[^']*'|\"[^\"]*\""), "<*>"),  # quoted strings
]
_WS = re.compile(r"\s+")

# Above this text similarity, two failures are the same issue no matter which evaluators
# tripped — a pydantic error captured by the outcome check on one trace and by a judge on the
# next must not become two clusters. Below it, a disjoint failed-evaluator set keeps genuinely
# different failure modes apart even when their wording overlaps.
_TEXT_MATCH_OVERRIDE = 0.9

# Dropped before comparing two failure texts: grammar glue plus the words every judge comment
# repeats ("the agent response ..."). Negations are deliberately KEPT — "helpful" and "not
# helpful" must not look alike. Whatever survives is the distinguishing content.
_BOILERPLATE = frozenset(
    """a an the this that these those it its is are was were be been being do does did doing
    of to for and or as in on at by with from into about there here which who whom what when
    have has had only just any some such
    agent response responses answer answers reply replies output outputs result results user
    users assistant model llm trace run turn span message messages provide provides provided
    """.split()
)
_WORD = re.compile(r"[a-z]+")

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
    """Strip volatile bits so failures with the same shape but different ids/values collapse.
    Whitespace is collapsed too — a traceback rendered with `\\n` vs spaces is the same failure."""
    out = text
    for pat, repl in _MASK_PATTERNS:
        out = pat.sub(repl, out)
    return _WS.sub(" ", out).strip()


def tokens(text: str) -> frozenset[str]:
    """Content words of a failure text — lowercased, boilerplate and 1-char noise removed."""
    return frozenset(w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _BOILERPLATE)


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard overlap of two token sets. Jaccard (not containment) on purpose: containment
    merges any short failure into a longer unrelated one that happens to include its words."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def eval_part(signature: str) -> str:
    """The failed-evaluator half of a signature string — the merge gate for dissimilar text."""
    return signature.split(" ## ", 1)[0]


def eval_names(signature: str) -> frozenset[str]:
    """The failed-evaluator names of a signature, as a set. Empty for signatures that carry no
    evaluator half (the synthesized ones on embedding clusters)."""
    return frozenset(n for n in eval_part(signature).split(" || ") if n)


def text_part(signature: str) -> str:
    """The failure-text half of a signature string — what gets compared for similarity."""
    return signature.split(" ## ", 1)[-1]


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

    def matches(self, other_signature: str, threshold: float) -> bool:
        """True if an existing cluster's signature describes the same failure.

        Near-identical failure text (>= _TEXT_MATCH_OVERRIDE) is the same issue regardless of
        which evaluators tripped — the evaluator set flaps (advisory judges, sampling, per-mode
        eval passes) while the underlying error text does not, and gating on set equality is
        exactly what duplicated clusters in production. Below the override, disjoint evaluator
        sets keep different failure modes apart; overlapping (or absent) sets fall through to
        the ordinary similarity threshold."""
        sim = similarity(tokens(text_part(self.signature)), tokens(text_part(other_signature)))
        if sim >= _TEXT_MATCH_OVERRIDE:
            return True
        mine, theirs = eval_names(self.signature), eval_names(other_signature)
        if mine and theirs and mine.isdisjoint(theirs):
            return False
        return sim >= threshold

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
