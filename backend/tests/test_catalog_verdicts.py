"""Catalog templates must be able to emit the verdict they claim to.

A `json`-output judge only produces PASS/FAIL when its parsed object carries a numeric
`score`/`overall_score` AND the config sets a `threshold` (see `LLMJudgeEvaluator._json_result`).
Nine shipped templates used to declare a threshold with no score field anywhere in their schema,
so the threshold was dead config: the column rendered its JSON but never a verdict, and — because
the roll-up policy is "fails iff a non-advisory evaluator FAILs" — those detectors could never
affect the trace badge, the threads dot, gates or trends. They looked wired up and did nothing.

These tests pin the invariant in both directions so the class of bug can't return.
"""

from __future__ import annotations

import pytest

from tracely.domain.evaluation.evaluators.catalog import TEMPLATES

_SCORE_KEYS = ("score", "overall_score")          # what _json_result looks for
_REASON_KEYS = ("reason", "reasoning", "summary")  # what it turns into the comment


def _json_templates():
    return [t for t in TEMPLATES if (t.get("config") or {}).get("output_type") == "json"]


def _props(template) -> dict:
    return ((template["config"].get("output_schema") or {}).get("properties") or {})


def test_there_are_json_templates_to_check():
    # Guards against the helpers silently matching nothing if the catalog shape ever changes.
    assert _json_templates()


@pytest.mark.parametrize("t", _json_templates(), ids=lambda t: t["score_name"])
def test_json_template_with_threshold_can_actually_produce_a_verdict(t):
    """A `threshold` is a promise to gate PASS/FAIL — the schema must expose a score to gate on."""
    if t["config"].get("threshold") is None:
        pytest.skip("informational column — no threshold, so no verdict is expected")
    props = _props(t)
    assert any(k in props for k in _SCORE_KEYS), (
        f"{t['score_name']} sets threshold={t['config']['threshold']} but its output_schema has "
        f"no {' / '.join(_SCORE_KEYS)} field, so _json_result can never emit PASS/FAIL"
    )


@pytest.mark.parametrize("t", _json_templates(), ids=lambda t: t["score_name"])
def test_json_template_score_field_is_numeric_and_required(t):
    """The score must be a required number: optional → the model may omit it and the column
    silently drops back to no-verdict; non-numeric → `_json_result` ignores it."""
    if t["config"].get("threshold") is None:
        pytest.skip("informational column")
    props = _props(t)
    key = next(k for k in _SCORE_KEYS if k in props)
    assert props[key].get("type") == "number", f"{t['score_name']}.{key} must be type number"
    required = (t["config"].get("output_schema") or {}).get("required") or []
    assert key in required, f"{t['score_name']}.{key} must be in `required`"


@pytest.mark.parametrize("t", _json_templates(), ids=lambda t: t["score_name"])
def test_scored_json_template_explains_itself(t):
    """A FAIL with an empty comment is unactionable — a gating column needs a reason field."""
    if t["config"].get("threshold") is None:
        pytest.skip("informational column")
    props = _props(t)
    assert any(k in props for k in _REASON_KEYS), (
        f"{t['score_name']} gates PASS/FAIL but exposes no {' / '.join(_REASON_KEYS)} field, so "
        f"its verdict lands with no explanation"
    )


@pytest.mark.parametrize("t", _json_templates(), ids=lambda t: t["score_name"])
def test_threshold_is_within_the_normalized_score_range(t):
    thr = t["config"].get("threshold")
    if thr is None:
        pytest.skip("informational column")
    # _json_result clamps value into 0..1, so a threshold outside it is always-pass/always-fail.
    assert 0.0 < float(thr) <= 1.0, f"{t['score_name']} threshold {thr} outside (0, 1]"


# ── the intent column's label contract ───────────────────────────────────────────
# `tracely.run.intent` is informational (no threshold, no verdict): its whole output is a label
# the trace table shows. The frontend headlines the FIRST short string field that isn't prose
# (`trace-table/format.ts:jsonResultLabel`, ≤ 24 chars), so a long enum value or a reordered
# schema silently turns the cell into raw JSON.


def _intent_template():
    return next(t for t in TEMPLATES if t["score_name"] == "tracely.run.intent")


def test_intent_column_is_recommended_and_sequential():
    """Installed in every new workspace, and chained so each turn sees the earlier intents."""
    t = _intent_template()
    assert t["recommended"] is True
    assert t["config"]["execution_mode"] == "sequential"
    assert t["config"].get("threshold") is None  # a label, never a verdict
    # the user's message alone: the agent's answer is the long half of the item, and reading it
    # makes the label follow what the agent did instead of what the user asked for
    assert t["config"]["include_answer"] is False


def test_intent_labels_render_in_the_trace_table_cell():
    t = _intent_template()
    props = (t["config"]["output_schema"] or {}).get("properties") or {}
    assert next(iter(props)) == "intent", "the label field must come first (jsonResultLabel)"
    enum = props["intent"]["enum"]
    assert enum and all(len(v) <= 24 for v in enum), f"too long to headline: {[v for v in enum if len(v) > 24]}"
    assert len(set(enum)) == len(enum)

# ── @VARIABLE templates must declare themselves advanced ─────────────────────────
# The seeder (`seeding_service` / `auth.provisioning`) inserts a template's config into the DB
# verbatim — unlike the API, it never runs `_stamp_advanced`. A template whose prompt holds
# `@VARIABLES` but no `is_advanced` therefore ships as a BASIC column whose rubric is the literal
# text "@CURRENT_STEPS.tool", and every grade it produces is nonsense.


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["score_name"])
def test_a_template_with_variables_declares_is_advanced(t):
    from tracely.domain.evaluation.template_resolver import extract_template_variables

    config = t.get("config") or {}
    if not extract_template_variables(config.get("prompt") or ""):
        pytest.skip("no @VARIABLES — a plain rubric")
    assert config.get("is_advanced") is True, (
        f"{t['score_name']} uses @VARIABLES but doesn't set is_advanced; the seeder doesn't stamp it"
    )
