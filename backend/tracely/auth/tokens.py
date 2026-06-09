"""Local-mode session tokens: HS256 JWTs signed with SESSION_SECRET.

Security: the algorithm is PINNED to HS256 on verify (defeats alg-confusion forgery), the issuer is
checked, and exp/iss/sub are required. The secret never leaves the backend; the frontend only forwards
the opaque token in `Authorization: Bearer`."""

from __future__ import annotations

import time

import jwt

from tracely.config import settings


class TokenError(Exception):
    """Raised when a session token is malformed, expired, or fails verification."""


def issue_session(user_id: str, *, ttl_seconds: int | None = None) -> str:
    now = int(time.time())
    ttl = settings.session_ttl_seconds if ttl_seconds is None else ttl_seconds
    payload = {
        "sub": user_id,
        "iss": settings.session_issuer,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def verify_session(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            settings.session_secret,
            algorithms=["HS256"],
            issuer=settings.session_issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as e:  # expired, bad sig, wrong issuer, missing claim, alg mismatch …
        raise TokenError(str(e)) from e
