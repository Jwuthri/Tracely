"""The single roll-up-verdict policy.

A trace / turn / session / trend counts as **failing** iff it has a `FAIL` on a *non-advisory*
evaluator. "Advisory" evaluators (e.g. the subjective answer-quality judge) still record their
verdict and show their pill, but a FAIL on one does NOT flip the roll-up — that judgment is shown
per-score, not as a structural failure of the run.

This replaces the old `name != 'tracely.run.quality'` magic string (which special-cased one judge
and was applied to the threads-list dot but not the trace badge or session verdict, so the same
trace could show a green dot in the list and "EVALS FAIL" on its detail page). The advisory set is
now a per-evaluator property (`config.advisory`) and this is the ONE place the Python read paths
apply it; the ClickHouse readers apply the identical rule in SQL via `name NOT IN {advisory}`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def is_failing(scores: Iterable[dict], advisory: Sequence[str]) -> bool:
    """True iff any score is a FAIL on an evaluator not in the advisory set."""
    adv = set(advisory)
    return any(s.get("verdict") == "FAIL" and s.get("name") not in adv for s in scores)


def rollup_verdict(scores: Iterable[dict], advisory: Sequence[str]) -> str | None:
    """The roll-up shown on a trace/turn: FAIL if any non-advisory FAIL, else PASS, else None when
    there are no scores at all (nothing graded yet → no badge)."""
    scores = list(scores)
    if not scores:
        return None
    return "FAIL" if is_failing(scores, advisory) else "PASS"
