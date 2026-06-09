"""Structural classification of a bearer credential: JWT vs opaque ingest key. No crypto here.

A JWS compact serialization is exactly three non-empty base64url segments (header.payload.signature).
Ingest keys are opaque, dot-free strings ("tracely_dev_key", "tk_<urlsafe>"), so this split is exact
for our key format without a DB hit. Critically, a JWT-shaped token that later fails verification is a
hard 401 — it must NEVER fall through to an ingest-key lookup (see resolve_principal)."""

from __future__ import annotations

_B64URL = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _is_base64url(s: str) -> bool:
    return bool(s) and all(c in _B64URL for c in s)


def looks_like_jwt(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 3 and all(_is_base64url(p) for p in parts)
