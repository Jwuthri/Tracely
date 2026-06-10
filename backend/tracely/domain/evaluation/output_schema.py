"""JSON Schema → pydantic response models for custom evaluator outputs.

The Add Column schema builder stores a flat JSON Schema in the evaluator's
`config.output_schema` (the `json` output type). At grading time it compiles to a pydantic
model handed to `create_agent(response_format=…)`, so the judge's reply is validated —
including ENUM properties, which become `Literal[...]` constraints the model cannot escape
(TurnWise dropped enum constraints at runtime; we enforce them).

`wrap_with_score` adds the TurnWise-style mandatory normalized-score field: every
custom-schema evaluation also yields a 0–1 score, popped off into the score row's `value` so
the user-visible JSON keeps their schema clean while verdicts/analytics stay uniform. (The
field is named `score__` — pydantic forbids leading underscores, so TurnWise's `__score__`
becomes the trailing-dunder twin; collision risk with user fields is nil.)
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, create_model

# The normalized-score field appended to every custom schema (pydantic forbids `__score__`).
SCORE_KEY = "score__"

SCORE_FIELD_DESCRIPTION = (
    "Overall evaluation score between 0 and 1. "
    "0.0 = worst/failure, 0.5 = average/neutral, 1.0 = best/perfect. "
    "For boolean-style judgments: 1.0 for positive, 0.0 for negative."
)

_PRIMITIVES: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
}


def _property_type(spec: dict) -> Any:
    """The python annotation for one JSON-Schema property (enum → Literal)."""
    enum_values = spec.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return Literal[tuple(str(v) for v in enum_values)]
    json_type = str(spec.get("type") or "string")
    if json_type == "array":
        items = spec.get("items") or {}
        item_enum = items.get("enum") if isinstance(items, dict) else None
        if isinstance(item_enum, list) and item_enum:
            return list[Literal[tuple(str(v) for v in item_enum)]]  # type: ignore[misc]
        item_type = _PRIMITIVES.get(str(items.get("type") or ""), str) if isinstance(items, dict) else str
        return list[item_type]  # type: ignore[valid-type]
    if json_type == "object":
        return dict
    return _PRIMITIVES.get(json_type, str)


def model_from_json_schema(
    schema: dict | None, name: str = "EvaluationOutput"
) -> type[BaseModel] | None:
    """Compile a (flat) JSON Schema into a pydantic model, or None when the schema can't be
    used as a structured-output contract (caller falls back to free-form JSON parsing).

    Supports `{"type": "object", "properties": …, "required": …}` plus top-level primitives
    (wrapped into a single `value` field). Nesting is one level deep — nested objects stay
    untyped dicts, arrays type their items when given.
    """
    if not schema or not isinstance(schema, dict):
        return None
    try:
        schema_type = schema.get("type")
        if schema_type in _PRIMITIVES:
            return create_model(
                name,
                value=(_PRIMITIVES[str(schema_type)], Field(description=str(schema.get("description") or ""))),
            )
        if schema_type != "object":
            return None
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict) or not properties:
            return None
        required = set(schema.get("required") or [])
        fields: dict[str, Any] = {}
        for field_name, spec in properties.items():
            spec = spec if isinstance(spec, dict) else {}
            annotation = _property_type(spec)
            description = str(spec.get("description") or "")
            if field_name in required:
                fields[field_name] = (annotation, Field(description=description))
            else:
                fields[field_name] = (Optional[annotation], Field(default=None, description=description))
        return create_model(name, **fields)
    except Exception:
        # invalid field names / exotic schemas — not a structured-output contract
        return None


def wrap_with_score(base_model: type[BaseModel]) -> type[BaseModel]:
    """Rebuild `base_model` with a mandatory `score__: float (0..1)` appended, so every
    custom-schema evaluation also produces the normalized score that drives verdicts."""
    if SCORE_KEY in base_model.model_fields:
        return base_model
    fields: dict[str, Any] = {
        field_name: (info.annotation, info)
        for field_name, info in base_model.model_fields.items()
    }
    fields[SCORE_KEY] = (float, Field(ge=0, le=1, description=SCORE_FIELD_DESCRIPTION))
    return create_model(f"Scored{base_model.__name__}", **fields)
