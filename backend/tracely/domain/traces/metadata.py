"""Parse the `tracely.metadata.*` JSON aggregations ClickHouse hands back to the routers."""

from __future__ import annotations

import json

_META_PREFIX = "tracely.metadata."


def parse_thread_meta(raw: str | None) -> dict[str, str]:
    """A thread's aggregated `metadata` JSON (a Map dumped by ClickHouse) → a clean dict of
    user-set metadata, with the `tracely.metadata.` prefix stripped."""
    meta: dict[str, str] = {}
    if not raw:
        return meta
    try:
        for k, v in json.loads(raw).items():
            meta[k[len(_META_PREFIX):] if k.startswith(_META_PREFIX) else k] = v
    except (ValueError, TypeError):
        pass
    return meta
