"""The organization tier: who can join what, and how big an account may get.

These pin the rules the layer exists for — break one and either tenants bleed into each other or
the free plan becomes unbounded:

- a workspace is reachable exactly when you belong to its ORG (no per-workspace grants);
- a personal account is one human with one workspace, and can never be joined;
- a company account's workspaces and seats are bounded by its plan, with pending invites
  counting as seats already taken;
- caps only exist when billing is on, so self-hosters stay unlimited;
- registration is invite-only unless the deployment opts into public signup.
"""

from __future__ import annotations

import pytest

from tracely.config import settings
from tracely.infrastructure.db import models


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def hosted(monkeypatch):
    """Hosted cloud: public signup + billing caps, with small limits so tests stay readable."""
    monkeypatch.setattr(settings, "allow_public_signup", True)
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "free_workspace_limit", 2)
    monkeypatch.setattr(settings, "free_seat_limit", 2)


async def _signup(client, email: str, password: str = "hunter2-pw") -> str:
    r = await client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ── registration shapes ───────────────────────────────────────────────────────


async def test_first_registrant_gets_a_company_org(client):
    """Self-host: the founder can invite their team, so their account is a company."""
    token = await _signup(client, "founder@x.test")
    me = (await client.get("/auth/me", headers=_bearer(token))).json()
    assert me["organization_kind"] == "company"
    assert me["role"] == "OWNER"
    assert len(me["projects"]) == 1


async def test_second_signup_is_invite_only_by_default(client):
    await _signup(client, "founder@x.test")
    r = await client.post(
        "/auth/register", json={"email": "stranger@x.test", "password": "hunter2-pw"}
    )
    assert r.status_code == 409  # an exposed self-host URL can't be used to mint accounts


async def test_public_signup_gives_each_account_its_own_personal_org(client, hosted):
    await _signup(client, "founder@x.test")
    token = await _signup(client, "someone@x.test")
    me = (await client.get("/auth/me", headers=_bearer(token))).json()
    assert me["organization_kind"] == "personal"
    assert len(me["projects"]) == 1 and len(me["organizations"]) == 1


async def test_public_signup_rejects_a_duplicate_email(client, hosted):
    await _signup(client, "founder@x.test")
    await _signup(client, "dup@x.test")
    r = await client.post(
        "/auth/register", json={"email": "dup@x.test", "password": "other-pw-1"}
    )
    assert r.status_code == 409


# ── personal accounts are un-joinable and single-workspace ────────────────────


async def test_personal_account_cannot_add_a_second_workspace(client, hosted):
    await _signup(client, "founder@x.test")
    token = await _signup(client, "solo@x.test")
    r = await client.post("/auth/projects", json={"name": "Second"}, headers=_bearer(token))
    assert r.status_code == 409
    assert "organization" in r.json()["detail"]


async def test_personal_account_cannot_invite(client, hosted):
    await _signup(client, "founder@x.test")
    token = await _signup(client, "solo@x.test")
    r = await client.post(
        "/auth/invitations", json={"email": "friend@x.test"}, headers=_bearer(token)
    )
    assert r.status_code == 409
    assert "personal account" in r.json()["detail"]


async def test_creating_an_organization_is_how_a_solo_account_grows(client, hosted):
    await _signup(client, "founder@x.test")
    token = await _signup(client, "solo@x.test")

    r = await client.post("/auth/organizations", json={"name": "Acme"}, headers=_bearer(token))
    assert r.status_code == 200 and r.json()["kind"] == "company"
    org_id = r.json()["id"]

    me = (await client.get("/auth/me", headers=_bearer(token))).json()
    assert len(me["organizations"]) == 2  # personal + the new company
    assert len([p for p in me["projects"] if p["organization_id"] == org_id]) == 1


# ── company caps ──────────────────────────────────────────────────────────────


async def _company_token(client, email="boss@x.test"):
    """A company org (the first registrant's) with its OWNER's token."""
    return await _signup(client, email)


async def test_workspace_cap_is_enforced_then_lifted_by_the_plan(client, hosted, session):
    token = await _company_token(client)
    # limit is 2 and signup created one
    assert (
        await client.post("/auth/projects", json={"name": "W2"}, headers=_bearer(token))
    ).status_code == 200
    r = await client.post("/auth/projects", json={"name": "W3"}, headers=_bearer(token))
    assert r.status_code == 409 and "workspace limit" in r.json()["detail"]

    me = (await client.get("/auth/me", headers=_bearer(token))).json()
    org = await session.get(models.Organization, me["organization_id"])
    org.plan = "pro"
    await session.commit()

    assert (
        await client.post("/auth/projects", json={"name": "W3"}, headers=_bearer(token))
    ).status_code == 200


async def test_pending_invites_occupy_seats(client, hosted):
    """Otherwise an org invites past its cap and only discovers it when people accept."""
    token = await _company_token(client)
    # seat limit 2: the owner holds one, so exactly one invite fits
    r1 = await client.post(
        "/auth/invitations", json={"email": "a@x.test"}, headers=_bearer(token)
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/auth/invitations", json={"email": "b@x.test"}, headers=_bearer(token)
    )
    assert r2.status_code == 409 and "seat limit" in r2.json()["detail"]

    # revoking the pending invite frees the seat again
    await client.delete(f"/auth/invitations/{r1.json()['id']}", headers=_bearer(token))
    r3 = await client.post(
        "/auth/invitations", json={"email": "b@x.test"}, headers=_bearer(token)
    )
    assert r3.status_code == 200


async def test_self_hosted_deployments_are_never_capped(client, monkeypatch):
    """Billing off (the self-host default) = no workspace or seat limits at all."""
    monkeypatch.setattr(settings, "billing_enabled", False)
    token = await _company_token(client)
    for i in range(4):
        r = await client.post(
            "/auth/projects", json={"name": f"W{i}"}, headers=_bearer(token)
        )
        assert r.status_code == 200
    for i in range(4):
        r = await client.post(
            "/auth/invitations", json={"email": f"m{i}@x.test"}, headers=_bearer(token)
        )
        assert r.status_code == 200


# ── invites grant the whole org, and nothing outside it ───────────────────────


async def test_accepting_an_invite_grants_every_workspace_in_the_org(client, hosted):
    token = await _company_token(client)
    await client.post("/auth/projects", json={"name": "W2"}, headers=_bearer(token))
    owner_me = (await client.get("/auth/me", headers=_bearer(token))).json()

    inv = await client.post(
        "/auth/invitations", json={"email": "teammate@x.test"}, headers=_bearer(token)
    )
    joined = await client.post(
        "/auth/invitations/accept",
        json={"token": inv.json()["token"], "password": "member-pw-1"},
    )
    assert joined.status_code == 200
    member_me = (
        await client.get("/auth/me", headers=_bearer(joined.json()["token"]))
    ).json()

    assert member_me["organization_id"] == owner_me["organization_id"]
    assert {p["id"] for p in member_me["projects"]} == {p["id"] for p in owner_me["projects"]}
    assert member_me["role"] == "MEMBER"


async def test_a_member_cannot_reach_another_accounts_workspace(client, hosted):
    """The cross-tenant boundary: no invite, no membership, no access — even by explicit id."""
    boss = await _company_token(client)
    boss_me = (await client.get("/auth/me", headers=_bearer(boss))).json()
    outsider = await _signup(client, "outsider@x.test")

    r = await client.get(
        "/auth/me",
        headers={**_bearer(outsider), "X-Tracely-Project": boss_me["project_id"]},
    )
    assert r.status_code == 403


async def test_members_endpoint_lists_the_org(client, hosted):
    token = await _company_token(client)
    inv = await client.post(
        "/auth/invitations", json={"email": "teammate@x.test", "role": "ADMIN"},
        headers=_bearer(token),
    )
    await client.post(
        "/auth/invitations/accept",
        json={"token": inv.json()["token"], "password": "member-pw-1"},
    )
    rows = (await client.get("/auth/members", headers=_bearer(token))).json()
    assert {(r["email"], r["role"]) for r in rows} == {
        ("boss@x.test", "OWNER"),
        ("teammate@x.test", "ADMIN"),
    }


async def test_inviting_an_existing_member_is_refused(client, hosted):
    token = await _company_token(client)
    inv = await client.post(
        "/auth/invitations", json={"email": "teammate@x.test"}, headers=_bearer(token)
    )
    await client.post(
        "/auth/invitations/accept",
        json={"token": inv.json()["token"], "password": "member-pw-1"},
    )
    r = await client.post(
        "/auth/invitations", json={"email": "teammate@x.test"}, headers=_bearer(token)
    )
    assert r.status_code == 409


async def test_a_plain_member_cannot_invite_or_add_workspaces(client, hosted):
    token = await _company_token(client)
    inv = await client.post(
        "/auth/invitations", json={"email": "teammate@x.test"}, headers=_bearer(token)
    )
    member = await client.post(
        "/auth/invitations/accept",
        json={"token": inv.json()["token"], "password": "member-pw-1"},
    )
    mh = _bearer(member.json()["token"])
    assert (
        await client.post("/auth/invitations", json={"email": "x@x.test"}, headers=mh)
    ).status_code == 403
    assert (
        await client.post("/auth/projects", json={"name": "Sneaky"}, headers=mh)
    ).status_code == 403
