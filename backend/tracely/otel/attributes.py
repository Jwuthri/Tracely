"""OTLP attribute decoding primitives.

`_any_value` walks the OTLP `AnyValue` oneof; `_attrs` turns a `KeyValue` list into a plain
dict. `_first` / `_truthy` / `_ns_to_dt` / `_to_str` are tiny scalar helpers used everywhere.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue


def _any_value(v: AnyValue) -> Any:
    kind = v.WhichOneof("value")
    if kind == "string_value":
        return v.string_value
    if kind == "bool_value":
        return v.bool_value
    if kind == "int_value":
        return v.int_value
    if kind == "double_value":
        return v.double_value
    if kind == "bytes_value":
        return v.bytes_value.hex()
    if kind == "array_value":
        return [_any_value(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _any_value(kv.value) for kv in v.kvlist_value.values}
    return None


def _attrs(kvs: list[KeyValue]) -> dict[str, Any]:
    return {kv.key: _any_value(kv.value) for kv in kvs}


def _ns_to_dt(ns: int) -> datetime | None:
    if not ns:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _first(attrs: dict[str, Any], keys: list[str]) -> Any:
    for k in keys:
        if k in attrs and attrs[k] not in (None, ""):
            return attrs[k]
    return None


def _truthy(v: Any) -> bool:
    return str(v).lower() in ("1", "true", "yes")


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v)
    except (TypeError, ValueError):
        return str(v)
