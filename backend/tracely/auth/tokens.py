"""Local-mode session tokens: HS256 JWTs signed with SESSION_SECRET.

Security: the algorithm is PINNED to HS256 on verify (defeats alg-confusion forgery), the issuer is
checked, and exp/iss/sub are required. The secret never leaves the backend; the frontend only forwards
the opaque token in `Authorization: Bearer`.

Revocation: a token carries the issuing user's `token_version` as `tv`, and `resolve_principal`
rejects it when the stored counter has moved on. Bumping that counter (password change, password
reset) is the only way to end a session before it expires — there is no denylist and nothing to
sweep. A token minted before `tv` existed has no claim, reads as 0, and still matches the column
default, so shipping this signs nobody out."""

from __future__ import annotations

import time

import jwt

from tracely.config import settings


class TokenError(Exception):
    """Raised when a session token is malformed, expired, or fails verification."""


def issue_session(
    user_id: str, *, ttl_seconds: int | None = None, token_version: int = 0
) -> str:
    now = int(time.time())
    ttl = settings.session_ttl_seconds if ttl_seconds is None else ttl_seconds
    payload = {
        "sub": user_id,
        "iss": settings.session_issuer,
        "iat": now,
        "exp": now + ttl,
        "tv": int(token_version or 0),
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


# ── public share links ────────────────────────────────────────────────────────

# A share token is a read-only capability for exactly ONE conversation — not a login. It carries
# its own issuer and deliberately NO `sub`, so it can never satisfy `verify_session` (which requires
# both), and it must never be handed to `resolve_principal`: doing so would promote a share link
# into a full project read key. `api/routers/share.py` verifies it directly for that reason.
SHARE_ISSUER = "tracely-share"
SHARE_TTL_SECONDS = 30 * 24 * 3600

# ponytail: stateless, so a link dies only when it expires — there is no revoke. To add one, either
# a `share_revocations` table checked in `verify_share`, or a per-project salt mixed into the
# signing key (bumping it kills every link for that project at once).


def issue_share(
    project_id: str, thread_id: str, *, ttl_seconds: int = SHARE_TTL_SECONDS
) -> str:
    now = int(time.time())
    payload = {
        "pid": project_id,
        "tid": thread_id,
        "iss": SHARE_ISSUER,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def verify_share(token: str) -> tuple[str, str]:
    """`(project_id, thread_id)` for a valid share token; `TokenError` for anything else."""
    try:
        claims = jwt.decode(
            token,
            settings.session_secret,
            algorithms=["HS256"],
            issuer=SHARE_ISSUER,
            options={"require": ["exp", "iss", "pid", "tid"]},
        )
    except jwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    return claims["pid"], claims["tid"]
