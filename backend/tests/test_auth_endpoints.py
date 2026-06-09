"""End-to-end local-mode auth via the ASGI app: register → login → me, invite → accept, RBAC."""

from __future__ import annotations


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_register_bootstrap_login_and_me(client):
    r = await client.post(
        "/auth/register",
        json={"email": "owner@x.test", "password": "hunter2-pw", "workspace_name": "Acme"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    me = await client.get("/auth/me", headers=_bearer(token))
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "OWNER"
    assert body["email"] == "owner@x.test"
    assert body["ingest_keys"], "bootstrapped workspace should expose an ingest key"

    login = await client.post(
        "/auth/login", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    assert login.status_code == 200


async def test_second_registration_is_invite_only(client):
    await client.post("/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"})
    r = await client.post(
        "/auth/register", json={"email": "intruder@x.test", "password": "hunter2-pw"}
    )
    assert r.status_code == 409


async def test_login_wrong_password_is_401(client):
    await client.post("/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"})
    r = await client.post("/auth/login", json={"email": "owner@x.test", "password": "WRONG-pw"})
    assert r.status_code == 401


async def test_invite_accept_and_rbac(client):
    reg = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    owner = reg.json()["token"]

    inv = await client.post(
        "/auth/invitations",
        json={"email": "teammate@x.test", "role": "MEMBER"},
        headers=_bearer(owner),
    )
    assert inv.status_code == 200, inv.text
    raw = inv.json()["token"]

    acc = await client.post(
        "/auth/invitations/accept", json={"token": raw, "password": "newpass-12"}
    )
    assert acc.status_code == 200, acc.text
    member = acc.json()["token"]

    me = await client.get("/auth/me", headers=_bearer(member))
    assert me.json()["role"] == "MEMBER"

    # a MEMBER cannot create invitations
    forbidden = await client.post(
        "/auth/invitations", json={"email": "x@y.z", "role": "MEMBER"}, headers=_bearer(member)
    )
    assert forbidden.status_code == 403


async def test_accept_invite_is_single_use(client):
    reg = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    inv = await client.post(
        "/auth/invitations",
        json={"email": "t@x.test", "role": "MEMBER"},
        headers=_bearer(reg.json()["token"]),
    )
    raw = inv.json()["token"]
    a1 = await client.post("/auth/invitations/accept", json={"token": raw, "password": "newpass-12"})
    a2 = await client.post("/auth/invitations/accept", json={"token": raw, "password": "newpass-12"})
    assert a1.status_code == 200 and a2.status_code == 400


async def test_create_workspace_adds_membership_and_own_key(client):
    reg = await client.post(
        "/auth/register",
        json={"email": "owner@x.test", "password": "hunter2-pw", "workspace_name": "First"},
    )
    owner = reg.json()["token"]

    me1 = (await client.get("/auth/me", headers=_bearer(owner))).json()
    assert len(me1["projects"]) == 1
    first_key = me1["ingest_keys"][0]

    created = await client.post(
        "/auth/projects", json={"name": "Second WS"}, headers=_bearer(owner)
    )
    assert created.status_code == 200, created.text
    new = created.json()
    assert new["role"] == "OWNER" and new["name"] == "Second WS"

    me2 = (await client.get("/auth/me", headers=_bearer(owner))).json()
    assert {p["name"] for p in me2["projects"]} == {"First", "Second WS"}

    # selecting the new workspace (X-Tracely-Project) re-scopes /auth/me to its own ingest key
    scoped = (
        await client.get(
            "/auth/me", headers={**_bearer(owner), "X-Tracely-Project": new["id"]}
        )
    ).json()
    assert scoped["project_id"] == new["id"]
    assert scoped["project_name"] == "Second WS"
    assert scoped["ingest_keys"] and scoped["ingest_keys"][0] != first_key


async def test_create_workspace_rejects_ingest_key_principal(client):
    # an ingest-key principal (SDK/dev) has no user — the endpoint must 400, not 500
    reg = await client.post(
        "/auth/register", json={"email": "owner@x.test", "password": "hunter2-pw"}
    )
    me = (await client.get("/auth/me", headers=_bearer(reg.json()["token"]))).json()
    ingest_key = me["ingest_keys"][0]
    r = await client.post("/auth/projects", json={"name": "Nope"}, headers=_bearer(ingest_key))
    assert r.status_code == 400


async def test_missing_credentials_is_401(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401


async def test_bogus_ingest_key_is_401(client):
    # the broadened dependency still rejects unknown ingest keys before any data access
    r = await client.get("/api/traces", headers=_bearer("tk_bogus"))
    assert r.status_code == 401
