"""Password-reset grants: mint, verify, consume.

Reuses the invite-token primitives (256-bit random, stored as sha256) — a reset link is the same
kind of bearer secret as an invite, with a much shorter life.

Security properties this module is responsible for:

- **No user enumeration.** `create_reset` returns None for an unknown or non-local email and the
  caller still answers 200. Whether an address has an account is not something an unauthenticated
  request gets to learn.
- **Single use.** A consumed grant is stamped `used_at`, and consuming one invalidates every other
  outstanding grant for that user — a leaked older link stops working the moment a newer one lands.
- **Short life.** Default 1 hour (`PASSWORD_RESET_TTL_SECONDS`), against the invite's 7 days.
- **Lookup by hash.** The raw token is never stored, never logged, and never returned by the API;
  it exists only in the link the user receives.

Not handled here: existing sessions are stateless HS256 JWTs with no revocation list, so a reset
does NOT sign out other devices. Anyone who already holds a valid session keeps it until it
expires. Revoking would need a token version on `users` checked at verify time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.auth.invitations import hash_token, new_invite_token
from tracely.auth.passwords import hash_password
from tracely.config import settings
from tracely.infrastructure.db.models import PasswordReset, User


async def create_reset(session: AsyncSession, email: str) -> tuple[str, User] | None:
    """Mint a reset grant for a local account. Returns `(raw_token, user)`, or None when the email
    has no local account — the caller must answer identically either way."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return None
    user = (
        await session.execute(
            select(User).where(User.email == normalized, User.source == "local")
        )
    ).scalar_one_or_none()
    if user is None:
        return None

    raw, token_hash = new_invite_token()
    session.add(
        PasswordReset(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=settings.password_reset_ttl_seconds),
        )
    )
    await session.commit()
    return raw, user


async def consume_reset(
    session: AsyncSession, raw_token: str, new_password: str
) -> User | None:
    """Set the new password if `raw_token` names a live grant. Returns the user, or None when the
    token is unknown, already used, or expired — the caller reports one generic failure for all
    three, since distinguishing them only helps an attacker."""
    grant = (
        await session.execute(
            select(PasswordReset).where(PasswordReset.token_hash == hash_token(raw_token or ""))
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if grant is None or grant.used_at is not None:
        return None
    # Postgres returns tz-aware datetimes; SQLite (tests) returns naive ones.
    expires = grant.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        return None

    user = await session.get(User, grant.user_id)
    if user is None:
        return None

    user.password_hash = hash_password(new_password)
    grant.used_at = now
    # Burn every other outstanding grant for this user: a reset means "I am taking this account
    # back", so any older link still sitting in a mailbox must stop working now.
    await session.execute(
        update(PasswordReset)
        .where(
            PasswordReset.user_id == user.id,
            PasswordReset.id != grant.id,
            PasswordReset.used_at.is_(None),
        )
        .values(used_at=now)
    )
    await session.commit()
    return user
