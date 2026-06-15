"""Judge-vs-human calibration math (pure).

Given human labels on judge verdicts (each carries the judge's verdict snapshot + the human's
verdict), compute per-evaluator agreement and the two error directions a reviewer cares about:

- **false_pass** — the judge said PASS-ish but the human says FAIL (a missed failure; the dangerous
  one for a merge gate).
- **false_fail** — the judge said FAIL but the human says PASS-ish (an over-flag; noisy gate).

No I/O. The service fetches annotations (Postgres) + the evaluator catalog (ClickHouse) and feeds the
rows here; the router serializes the result.
"""

from __future__ import annotations

FAIL = "FAIL"


def _norm(v: object) -> str:
    return str(v or "").strip().upper()


def _is_fail(v: object) -> bool:
    return _norm(v) == FAIL


def evaluator_agreement(rows: list[dict]) -> dict:
    """Agreement for ONE evaluator's labels. `rows` items need `judge_verdict` + `human_verdict`.
    Returns counts + agreement fraction (0..1) and the two confusion directions."""
    labeled = len(rows)
    agree = sum(1 for r in rows if _norm(r.get("judge_verdict")) == _norm(r.get("human_verdict")))
    false_pass = sum(
        1 for r in rows if _is_fail(r.get("human_verdict")) and not _is_fail(r.get("judge_verdict"))
    )
    false_fail = sum(
        1 for r in rows if _is_fail(r.get("judge_verdict")) and not _is_fail(r.get("human_verdict"))
    )
    return {
        "labeled": labeled,
        "agree": agree,
        "agreement": (agree / labeled) if labeled else 0.0,
        "false_pass": false_pass,
        "false_fail": false_fail,
    }


def agreement_by_evaluator(annotations: list[dict]) -> dict[str, dict]:
    """Group annotations by `score_name` → per-evaluator agreement stats."""
    groups: dict[str, list[dict]] = {}
    for a in annotations:
        groups.setdefault(a.get("score_name") or "", []).append(a)
    return {name: evaluator_agreement(rows) for name, rows in groups.items()}


def merge_catalog_with_agreement(catalog: list[dict], annotations: list[dict]) -> list[dict]:
    """Join the evaluator catalog (every judge that produced verdicts) with its agreement stats, so
    the calibration view lists all evaluators — labeled or not (unlabeled → labeled=0)."""
    stats = agreement_by_evaluator(annotations)
    empty = {"labeled": 0, "agree": 0, "agreement": 0.0, "false_pass": 0, "false_fail": 0}
    out = []
    for ev in catalog:
        out.append({**ev, **stats.get(ev["name"], empty)})
    return out
