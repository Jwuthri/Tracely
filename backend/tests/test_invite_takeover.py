"""An invite must never become a login for an account that already exists.

The raw invite token is handed to the INVITER (so the UI can show the link). If the invited email
already has an account, accepting must prove knowledge of that account's password — otherwise an
owner in org A invites someone from org B, accepts the invite themselves, and receives a session
for the victim's account with every workspace the victim can reach."""

from __future__ import annotations


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_inviter_cannot_accept_as_an_existing_account(client, make_workspace):
    # the victim already has an account in their own org
    await make_workspace("victim-ws", "tk_victim", "victim@b.test", password="victim-secret")

    # an unrelated org's owner invites the victim's email
    await make_workspace("attacker-ws", "tk_attacker", "owner@a.test", password="hunter2-pw")
    login = await client.post("/auth/login", json={"email": "owner@a.test", "password": "hunter2-pw"})
    owner = login.json()["token"]
    inv = await client.post(
        "/auth/invitations", json={"email": "victim@b.test", "role": "MEMBER"}, headers=_bearer(owner)
    )
    assert inv.status_code == 200, inv.text
    raw = inv.json()["token"]

    # the inviter tries to accept with a password of their choosing
    acc = await client.post("/auth/invitations/accept", json={"token": raw, "password": "attacker-pw"})
    assert acc.status_code == 401, acc.text

    # the invite is still pending: the real person accepts with THEIR password and joins
    acc = await client.post("/auth/invitations/accept", json={"token": raw, "password": "victim-secret"})
    assert acc.status_code == 200, acc.text
    me = await client.get("/auth/me", headers=_bearer(acc.json()["token"]))
    assert me.json()["email"] == "victim@b.test"
    assert {p["slug"] for p in me.json()["projects"]} >= {"victim-ws"}
    assert len(me.json()["organizations"]) == 2
