"""Sessions are stateless JWTs, so `users.token_version` is the only thing that can end one early.

What this pins down: a password change or reset strands every token issued before it (the point of
"I'm taking my account back"), the person doing it keeps working, and shipping the feature doesn't
sign out the tokens that were already in the wild."""

from __future__ import annotations

import pytest

from tracely.auth import AuthError, resolve_principal, tokens


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_password_change_kills_other_sessions_but_not_this_one(client):
    reg = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    intruder = reg.json()["token"]  # the session someone else already holds
    laptop = (
        await client.post("/auth/login", json={"email": "owner@x.test", "password": "hunter2-pw"})
    ).json()["token"]
    assert (await client.get("/auth/me", headers=_bearer(intruder))).status_code == 200

    changed = await client.post(
        "/auth/change-password",
        json={"current_password": "hunter2-pw", "new_password": "brand-new-pw"},
        headers=_bearer(laptop),
    )
    assert changed.status_code == 200, changed.text

    # every token minted before the change is dead — including the one that made the change
    assert (await client.get("/auth/me", headers=_bearer(intruder))).status_code == 401
    assert (await client.get("/auth/me", headers=_bearer(laptop))).status_code == 401
    # ...and the caller is handed a fresh one so they aren't logged out by their own action
    fresh = changed.json()["token"]
    assert (await client.get("/auth/me", headers=_bearer(fresh))).status_code == 200


async def test_password_reset_kills_existing_sessions(client, session):
    from tracely.auth.password_reset import create_reset

    reg = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    stolen = reg.json()["token"]
    grant = await create_reset(session, "owner@x.test")
    assert grant is not None
    raw, _user = grant

    done = await client.post(
        "/auth/reset-password", json={"token": raw, "new_password": "recovered-pw"}
    )
    assert done.status_code == 200, done.text
    assert (await client.get("/auth/me", headers=_bearer(stolen))).status_code == 401
    assert (await client.get("/auth/me", headers=_bearer(done.json()["token"]))).status_code == 200


async def test_a_token_minted_before_this_feature_still_works(session, make_workspace):
    """No `tv` claim reads as 0, which is the column default — deploying must not sign anyone out."""
    import jwt

    from tracely.config import settings

    _proj, user, _key = await make_workspace("ws", "tk_1", "o@x.test")
    legacy = jwt.encode(
        {"sub": user.id, "iss": settings.session_issuer, "exp": 2**31 - 1},
        settings.session_secret,
        algorithm="HS256",
    )
    p = await resolve_principal(token=legacy, x_project=None, session=session)
    assert p.user_id == user.id

    user.token_version = 1
    await session.commit()
    with pytest.raises(AuthError):
        await resolve_principal(token=legacy, x_project=None, session=session)


async def test_a_stale_version_is_rejected(session, make_workspace):
    _proj, user, _key = await make_workspace("ws", "tk_2", "o@x.test")
    old = tokens.issue_session(user.id, token_version=0)
    user.token_version = 3
    await session.commit()
    with pytest.raises(AuthError):
        await resolve_principal(token=old, x_project=None, session=session)
    current = tokens.issue_session(user.id, token_version=3)
    assert (await resolve_principal(token=current, x_project=None, session=session)).user_id == user.id
