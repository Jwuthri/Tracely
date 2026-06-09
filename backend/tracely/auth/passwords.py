"""Argon2id password hashing for local-mode accounts.

One shared hasher. `verify_password` runs a dummy verify when the user/hash is absent so the timing of
"no such user" matches "wrong password" — callers should always return a single generic 401."""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    # computed once, lazily (argon2 hashing is intentionally slow) to equalize missing-user timing
    return _hasher.hash("tracely-timing-equalizer")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        try:
            _hasher.verify(_dummy_hash(), password)
        except Exception:  # noqa: BLE001 — timing-equalizer only; result is discarded
            pass
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
