"""Meta-analysis: deterministic statistics + the LLM-merge (stats stay authoritative)."""

from __future__ import annotations

import pytest

from tracely.domain.analysis import statistics as st
from tracely.infrastructure.llm.meta_analysis_agent import (
    Correlation,
    MetaAnalysisOutput,
    Pattern,
)
from tracely.services import meta_analysis_service as svc
from tracely.services.meta_analysis_service import MetaAnalysisService


def _rows():
    rows = []
    x = {"c1": 0.1, "c2": 0.3, "c3": 0.5, "c4": 0.7, "c5": 0.9, "c6": 5.0}  # c6 outlier
    y = {"c1": 0.1, "c2": 0.3, "c3": 0.5, "c4": 0.7, "c5": 0.9}  # tracks x
    z = {"c1": 0.9, "c2": 0.7, "c3": 0.5, "c4": 0.3, "c5": 0.1}  # anti-correlated
    for c, v in x.items():
        rows.append({"conversation_id": c, "metric_name": "x", "value": v})
    for c, v in y.items():
        rows.append({"conversation_id": c, "metric_name": "y", "value": v})
    for c, v in z.items():
        rows.append({"conversation_id": c, "metric_name": "z", "value": v})
    return rows


def test_build_matrix_averages_duplicates():
    rows = [
        {"conversation_id": "c1", "metric_name": "m", "value": 0.2},
        {"conversation_id": "c1", "metric_name": "m", "value": 0.4},
        {"conversation_id": "c2", "metric_name": "m", "value": 1.0},
        {"conversation_id": "c3", "metric_name": "m", "value": None},  # skipped
    ]
    m = st.build_matrix(rows)
    assert m["m"]["c1"] == pytest.approx(0.3)  # averaged
    assert m["m"]["c2"] == 1.0
    assert "c3" not in m["m"]


def test_spearman_perfect_and_sorted():
    m = st.build_matrix(_rows())
    corr = st.spearman_correlations(m)
    by_pair = {frozenset((c["metric_a"], c["metric_b"])): c for c in corr}
    assert by_pair[frozenset(("x", "y"))]["coefficient"] == 1.0
    assert by_pair[frozenset(("x", "z"))]["coefficient"] == -1.0
    # sorted by |coefficient| descending
    coefs = [abs(c["coefficient"]) for c in corr]
    assert coefs == sorted(coefs, reverse=True)


def test_correlation_needs_min_points():
    m = {"a": {"c1": 1.0, "c2": 2.0}, "b": {"c1": 1.0, "c2": 2.0}}  # only 2 shared
    assert st.spearman_correlations(m) == []


def test_zscore_outlier_detected():
    m = st.build_matrix(_rows())
    outliers = st.zscore_outliers(m)
    ids = {o["conversation_id"] for o in outliers}
    assert "c6" in ids
    c6 = next(o for o in outliers if o["conversation_id"] == "c6")
    assert "x" in c6["metrics_affected"]
    assert c6["severity"] in ("low", "medium", "high")


def test_analyze_stats_only_when_no_llm(monkeypatch):
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: False)
    result, meta = MetaAnalysisService._analyze("", "", _rows())
    assert result["metrics_analyzed"] == 3
    assert result["conversations_analyzed"] == 6
    assert result["correlations"], "deterministic correlations must survive without an LLM"
    assert result["patterns"] == []
    assert "stats only" in result["summary"].lower() or "statistics only" in result["summary"].lower()
    assert meta["llm"] is False


def test_analyze_merges_llm_but_keeps_stats(monkeypatch):
    monkeypatch.setattr(svc.provider, "llm_enabled", lambda: True)

    def fake_synthesize(prompt: str) -> MetaAnalysisOutput:
        return MetaAnalysisOutput(
            patterns=[Pattern(description="x and y move together", evidence="strong corr", affected_metrics=["x", "y"])],
            correlations=[Correlation(metric_a="x", metric_b="y", coefficient=0.123, interpretation="they rise together")],
            outliers=[],
            recommendations=["look at c6"],
            summary="key findings",
            confidence=0.8,
        )

    monkeypatch.setattr(svc, "synthesize", fake_synthesize)
    result, meta = MetaAnalysisService._analyze("aid", "weather", _rows())

    assert meta["llm"] is True
    assert result["summary"] == "key findings"
    assert result["patterns"][0]["description"] == "x and y move together"
    # deterministic coefficient wins; the LLM only contributes interpretation
    xy = next(c for c in result["correlations"] if {c["metric_a"], c["metric_b"]} == {"x", "y"})
    assert xy["coefficient"] == 1.0
    assert xy["interpretation"] == "they rise together"
