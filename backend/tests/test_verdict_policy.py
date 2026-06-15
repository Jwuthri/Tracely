"""The unified roll-up-verdict policy: a non-advisory FAIL flips the roll-up; an advisory FAIL
(e.g. the subjective answer-quality judge) is shown per-score but does not. This is the single
definition the threads dot / trace badge / session verdict / trends counters all share, so they
can never disagree the way they used to (green dot in the list, "EVALS FAIL" on the detail page)."""

from __future__ import annotations

from tracely.domain.evaluation.verdict import is_failing, rollup_verdict

STRUCTURAL = "tracely.run.tool_consistency"
QUALITY = "tracely.run.quality"


def test_no_scores_yields_no_verdict():
    assert rollup_verdict([], []) is None
    assert rollup_verdict([], [QUALITY]) is None


def test_structural_fail_flips_rollup():
    scores = [{"name": STRUCTURAL, "verdict": "FAIL"}]
    assert is_failing(scores, [QUALITY]) is True
    assert rollup_verdict(scores, [QUALITY]) == "FAIL"


def test_advisory_fail_does_not_flip_rollup():
    scores = [{"name": QUALITY, "verdict": "FAIL"}]
    assert is_failing(scores, [QUALITY]) is False
    # the same trace with the quality judge NOT advisory would be FAIL — proving it's the flag, not the name
    assert rollup_verdict(scores, [QUALITY]) == "PASS"
    assert rollup_verdict(scores, []) == "FAIL"


def test_mixed_advisory_and_structural():
    scores = [
        {"name": QUALITY, "verdict": "FAIL"},
        {"name": STRUCTURAL, "verdict": "PASS"},
    ]
    assert rollup_verdict(scores, [QUALITY]) == "PASS"
    scores.append({"name": "tracely.run.latency_ms", "verdict": "FAIL"})
    assert rollup_verdict(scores, [QUALITY]) == "FAIL"  # a non-advisory FAIL still flips it
