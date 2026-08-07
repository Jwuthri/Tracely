"""Clerk RS256 verification + idempotent upsert, with a locally-generated keypair and a faked JWKS."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import func, select

from tracely.auth import clerk
from tracely.auth.principal import AuthError, resolve_principal
from tracely.config import settings
from tracely.infrastructure.db import models

_ISSUER = "https://test.clerk.accounts.dev"


@pytest.fixture
def rsa_keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    return priv, pub


@pytest.fixture
def clerk_mode(monkeypatch, rsa_keys):
    _, pub = rsa_keys
    monkeypatch.setattr(settings, "auth_mode", "clerk")
    monkeypatch.setattr(settings, "clerk_issuer", _ISSUER)
    monkeypatch.setattr(settings, "clerk_audience", "")

    class _FakeKey:
        key = pub

    class _FakeClient:
        def get_signing_key_from_jwt(self, token):
            return _FakeKey()

    monkeypatch.setattr(clerk, "_client", lambda: _FakeClient())
    return rsa_keys


def _token(priv: str, **claims) -> str:
    base = {"iss": _ISSUER, "sub": "user_123", "exp": int(time.time()) + 600}
    base.update(claims)
    return jwt.encode(base, priv, algorithm="RS256")


async def test_clerk_jwt_upserts_and_is_idempotent(session, clerk_mode):
    priv, _ = clerk_mode
    token = _token(priv, sub="user_abc", org_id="org_1", org_role="org:admin", email="z@x.test")

    p1 = await resolve_principal(token=token, x_project=None, session=session)
    assert p1.kind == "clerk" and p1.role == "ADMIN" and p1.user_id

    p2 = await resolve_principal(token=token, x_project=None, session=session)
    assert p2.project_id == p1.project_id and p2.user_id == p1.user_id

    async def _count(model):
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()

    assert await _count(models.User) == 1
    assert await _count(models.Organization) == 1
    assert await _count(models.Project) == 1
    assert await _count(models.OrgMembership) == 1
    assert await _count(models.IngestKey) == 1  # provisioned a key for the new workspace


async def test_clerk_org_is_a_company_account(session, clerk_mode):
    """A Clerk org maps to a company organization, and everyone in it lands in the SAME one —
    which is what makes their workspaces shared and their quota a single pool."""
    priv, _ = clerk_mode
    admin = _token(priv, sub="user_admin", org_id="org_9", org_role="org:admin")
    member = _token(priv, sub="user_member", org_id="org_9", org_role="org:member")

    p_admin = await resolve_principal(token=admin, x_project=None, session=session)
    p_member = await resolve_principal(token=member, x_project=None, session=session)

    assert p_admin.organization_id == p_member.organization_id
    assert p_admin.project_id == p_member.project_id
    assert p_admin.role == "ADMIN" and p_member.role == "MEMBER"
    org = await session.get(models.Organization, p_admin.organization_id)
    assert org.kind == "company"
    n = (
        await session.execute(select(func.count()).select_from(models.Organization))
    ).scalar_one()
    assert n == 1  # the second sign-in joined the org, it didn't mint another


async def test_clerk_personal_account_is_a_personal_org(session, clerk_mode):
    priv, _ = clerk_mode
    p = await resolve_principal(token=_token(priv, sub="solo"), x_project=None, session=session)
    assert p.role == "OWNER"  # no org → personal workspace owned by the user
    org = await session.get(models.Organization, p.organization_id)
    assert org.kind == "personal"  # 1 workspace, 1 seat, un-joinable


async def test_clerk_alg_confusion_rejected(session, clerk_mode):
    # The classic alg-confusion attack swaps RS256→HS256 so the verifier HMACs with the public key. Our
    # defense is pinning algorithms=["RS256"], which rejects *any* HS256 token at the algorithm check —
    # so an HS256 token signed with an arbitrary secret must also be refused. (PyJWT additionally blocks
    # encoding HS256 with a PEM key, which is why we sign with a plain string here.)
    forged = jwt.encode(
        {"iss": _ISSUER, "sub": "attacker", "exp": int(time.time()) + 600},
        "attacker-chosen-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthError) as e:
        await resolve_principal(token=forged, x_project=None, session=session)
    assert e.value.status == 401


async def test_clerk_wrong_issuer_rejected(session, clerk_mode):
    priv, _ = clerk_mode
    bad = _token(priv, iss="https://evil.example.com")
    with pytest.raises(AuthError):
        await resolve_principal(token=bad, x_project=None, session=session)
