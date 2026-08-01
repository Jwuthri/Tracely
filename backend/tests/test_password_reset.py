"""Password reset: the happy path, and the properties that make it safe to expose unauthenticated."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tracely.auth import password_reset
from tracely.auth.invitations import hash_token
from tracely.infrastructure.db.models import PasswordReset


async def _register(client, email="owner@x.test", password="hunter2-pw"):
    r = await client.post(
        "/auth/register", json={"email": email, "password": password, "workspace_name": "Acme"}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _mint(client, session, email="owner@x.test") -> str:
    """Ask for a reset the way the endpoint does, and read the raw token the caller would email."""
    await client.post("/auth/forgot-password", json={"email": email})
    grant = await password_reset.create_reset(session, email)
    assert grant is not None
    return grant[0]


# ── happy path ────────────────────────────────────────────────────────────────


async def test_reset_sets_the_new_password_and_signs_in(client, session):
    await _register(client)
    token = await _mint(client, session)

    r = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "brand-new-pw"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["token"], "a successful reset should return a usable session"

    assert (
        await client.post("/auth/login", json={"email": "owner@x.test", "password": "brand-new-pw"})
    ).status_code == 200
    assert (
        await client.post("/auth/login", json={"email": "owner@x.test", "password": "hunter2-pw"})
    ).status_code == 401, "the old password must stop working"


# ── no user enumeration ───────────────────────────────────────────────────────


async def test_forgot_password_answers_identically_for_unknown_emails(client):
    """The response to an unknown address must be byte-identical to a known one, or this endpoint
    becomes a free account-existence oracle for anyone on the internet."""
    await _register(client)

    known = await client.post("/auth/forgot-password", json={"email": "owner@x.test"})
    unknown = await client.post("/auth/forgot-password", json={"email": "nobody@x.test"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_forgot_password_never_returns_the_token(client):
    await _register(client)
    body = (await client.post("/auth/forgot-password", json={"email": "owner@x.test"})).json()
    assert "token" not in str(body).lower().replace("reset link", "")


async def test_no_grant_is_created_for_an_unknown_email(client, session):
    await _register(client)
    await client.post("/auth/forgot-password", json={"email": "nobody@x.test"})
    rows = (await session.execute(select(PasswordReset))).scalars().all()
    assert rows == []


# ── token hygiene ─────────────────────────────────────────────────────────────


async def test_raw_token_is_never_stored(client, session):
    await _register(client)
    token = await _mint(client, session)
    stored = [r.token_hash for r in (await session.execute(select(PasswordReset))).scalars()]
    assert stored and all(token not in h for h in stored)


async def test_a_token_works_only_once(client, session):
    await _register(client)
    token = await _mint(client, session)

    first = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "brand-new-pw"}
    )
    assert first.status_code == 200
    replay = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "attacker-pw"}
    )
    assert replay.status_code == 400
    assert (
        await client.post("/auth/login", json={"email": "owner@x.test", "password": "attacker-pw"})
    ).status_code == 401


async def test_using_one_grant_burns_every_other_outstanding_grant(client, session):
    """A stale link sitting in a mailbox must die the moment the account is taken back."""
    await _register(client)
    old = await _mint(client, session)
    new = await _mint(client, session)

    assert (
        await client.post("/auth/reset-password", json={"token": new, "new_password": "new-pw-1234"})
    ).status_code == 200
    assert (
        await client.post("/auth/reset-password", json={"token": old, "new_password": "old-pw-1234"})
    ).status_code == 400


async def test_an_expired_token_is_rejected(client, session):
    await _register(client)
    token = await _mint(client, session)
    grant = (
        await session.execute(
            select(PasswordReset).where(PasswordReset.token_hash == hash_token(token))
        )
    ).scalar_one()
    grant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await session.commit()

    r = await client.post(
        "/auth/reset-password", json={"token": token, "new_password": "brand-new-pw"}
    )
    assert r.status_code == 400


async def test_a_garbage_token_is_rejected(client):
    await _register(client)
    r = await client.post(
        "/auth/reset-password", json={"token": "not-a-real-token", "new_password": "brand-new-pw"}
    )
    assert r.status_code == 400


@pytest.mark.parametrize("bad", ["", "short", "1234567"])
async def test_short_passwords_are_rejected(client, session, bad):
    await _register(client)
    token = await _mint(client, session)
    r = await client.post("/auth/reset-password", json={"token": token, "new_password": bad})
    assert r.status_code == 422
