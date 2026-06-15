"""Judge-vs-human calibration math: agreement %, the two confusion directions (false_pass /
false_fail), grouping, and the catalog join that surfaces unlabeled evaluators."""

from __future__ import annotations

from tracely.domain.evaluation.calibration import (
    agreement_by_evaluator,
    evaluator_agreement,
    merge_catalog_with_agreement,
)


def _ann(judge: str, human: str, name: str = "faithfulness") -> dict:
    return {"score_name": name, "judge_verdict": judge, "human_verdict": human}


def test_perfect_agreement():
    rows = [_ann("PASS", "PASS"), _ann("FAIL", "FAIL")]
    out = evaluator_agreement(rows)
    assert out["labeled"] == 2 and out["agree"] == 2
    assert out["agreement"] == 1.0
    assert out["false_pass"] == 0 and out["false_fail"] == 0


def test_false_pass_is_judge_pass_human_fail():
    # the dangerous one: the judge let a failure through
    out = evaluator_agreement([_ann("PASS", "FAIL")])
    assert out["false_pass"] == 1 and out["false_fail"] == 0
    assert out["agreement"] == 0.0


def test_false_fail_is_judge_fail_human_pass():
    # the noisy one: the judge over-flagged
    out = evaluator_agreement([_ann("FAIL", "PASS")])
    assert out["false_fail"] == 1 and out["false_pass"] == 0


def test_agreement_fraction_and_case_insensitive():
    rows = [_ann("pass", "PASS"), _ann("PASS", "pass"), _ann("FAIL", "pass")]  # 2 agree, 1 false_fail
    out = evaluator_agreement(rows)
    assert out["agree"] == 2
    assert out["agreement"] == 2 / 3
    assert out["false_fail"] == 1


def test_empty_is_zero_not_div_by_zero():
    out = evaluator_agreement([])
    assert out["labeled"] == 0 and out["agreement"] == 0.0


def test_agreement_by_evaluator_groups_by_name():
    rows = [_ann("PASS", "PASS", "a"), _ann("FAIL", "PASS", "b"), _ann("PASS", "PASS", "a")]
    by = agreement_by_evaluator(rows)
    assert by["a"]["labeled"] == 2 and by["a"]["agreement"] == 1.0
    assert by["b"]["false_fail"] == 1


def test_merge_catalog_surfaces_unlabeled_evaluators():
    catalog = [
        {"name": "faithfulness", "level": "AGENT_RUN", "total": 10, "fails": 3},
        {"name": "tone", "level": "AGENT_RUN", "total": 5, "fails": 0},
    ]
    annotations = [_ann("PASS", "FAIL", "faithfulness")]
    merged = {m["name"]: m for m in merge_catalog_with_agreement(catalog, annotations)}
    assert merged["faithfulness"]["labeled"] == 1 and merged["faithfulness"]["false_pass"] == 1
    assert merged["tone"]["labeled"] == 0 and merged["tone"]["agreement"] == 0.0  # unlabeled
    assert merged["tone"]["total"] == 5  # catalog fields preserved
