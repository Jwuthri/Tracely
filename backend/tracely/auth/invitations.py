"""Invite tokens: 256-bit random, persisted only as a sha256 hash (the raw token is shown once)."""

from __future__ import annotations

import hashlib
import secrets


def new_invite_token() -> tuple[str, str]:
    """Return (raw_token, token_hash). Store only the hash; surface the raw token once to the inviter."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
