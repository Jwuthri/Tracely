"""JSON Schema → pydantic response models for custom evaluator outputs.

The Add Column schema builder stores a flat JSON Schema in the evaluator's
`config.output_schema` (the `json` output type). At grading time it compiles to a pydantic
model handed to `create_agent(response_format=…)`, so the judge's reply is validated —
including ENUM properties, which become `Literal[...]` constraints the model cannot escape
(TurnWise dropped enum constraints at runtime; we enforce them).

The output is exactly what the user defined — nothing is appended. A column that wants to drive
PASS/FAIL and gates simply includes a numeric `score` field (and a `reason` string for the
explanation); see `LLMJudgeEvaluator._json_result`.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, create_model

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
