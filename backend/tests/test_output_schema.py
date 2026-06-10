"""JSON Schema → pydantic compilation for custom evaluator outputs (the schema builder)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tracely.domain.evaluation.output_schema import (
    SCORE_KEY,
    model_from_json_schema,
    wrap_with_score,
)

_BUILDER_DEFAULT = {
    "type": "object",
    "properties": {
        "score": {"type": "number", "description": "Score from 0 to 1"},
        "reasoning": {"type": "string", "description": "Explanation for the score"},
    },
    "required": ["score", "reasoning"],
}


def test_builder_default_schema_compiles():
    model = model_from_json_schema(_BUILDER_DEFAULT)
    assert model is not None
    inst = model(score=0.8, reasoning="solid")
    assert inst.model_dump() == {"score": 0.8, "reasoning": "solid"}
    assert model.model_fields["score"].description == "Score from 0 to 1"
    with pytest.raises(ValidationError):
        model(score=0.8)  # reasoning required


def test_enum_becomes_literal_constraint():
    model = model_from_json_schema({
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": ["none", "mild", "severe"]},
            "reason": {"type": "string"},
        },
        "required": ["severity"],
    })
    assert model(severity="mild").severity == "mild"
    with pytest.raises(ValidationError):
        model(severity="catastrophic")  # off-list label rejected (TurnWise dropped this)
    # optional fields default to None
    assert model(severity="none").reason is None


def test_array_items_and_enum_arrays():
    model = model_from_json_schema({
        "type": "object",
        "properties": {
            "tags": {"type": "array", "items": {"type": "string"}},
            "issues": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
        },
        "required": ["tags", "issues"],
    })
    inst = model(tags=["x"], issues=["a", "b"])
    assert inst.tags == ["x"]
    with pytest.raises(ValidationError):
        model(tags=["x"], issues=["nope"])


def test_primitive_top_level_wraps_value():
    model = model_from_json_schema({"type": "number", "description": "a measurement"})
    assert model(value=3.5).value == 3.5


@pytest.mark.parametrize("bad", [None, {}, {"type": "array"}, {"type": "object"}, {"type": "object", "properties": {}}])
def test_unusable_schemas_return_none(bad):
    assert model_from_json_schema(bad) is None


def test_non_identifier_field_names_still_compile():
    """pydantic's create_model tolerates arbitrary string keys via **kwargs, so even odd
    builder-typed names survive (and round-trip through model_dump)."""
    model = model_from_json_schema({
        "type": "object",
        "properties": {"not a valid identifier": {"type": "string"}},
        "required": ["not a valid identifier"],
    })
    assert model is not None
    assert model(**{"not a valid identifier": "x"}).model_dump()["not a valid identifier"] == "x"


def test_wrap_with_score_appends_required_bounded_field():
    base = model_from_json_schema(_BUILDER_DEFAULT)
    wrapped = wrap_with_score(base)
    inst = wrapped(score=0.5, reasoning="r", **{SCORE_KEY: 0.9})
    assert inst.model_dump()[SCORE_KEY] == 0.9
    with pytest.raises(ValidationError):
        wrapped(score=0.5, reasoning="r")  # score__ required
    with pytest.raises(ValidationError):
        wrapped(score=0.5, reasoning="r", **{SCORE_KEY: 1.7})  # bounded 0..1
