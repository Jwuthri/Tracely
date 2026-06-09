"""Principal resolution: ingest keys, local session JWTs, multi-membership selection, isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tracely.auth import tokens
from tracely.auth.principal import AuthError, resolve_principal
from tracely.infrastructure.db import models


async def test_ingest_key_resolves_to_its_project(session, make_workspace):
    proj, _, key = await make_workspace("acme", "tk_acme_key", "a@acme.test")
    p = await resolve_principal(token=key.key, x_project=None, session=session)
    assert p.project_id == proj.id and p.kind == "ingest" and p.user_id is None and p.role is None


async def test_invalid_ingest_key_is_401(session):
    with pytest.raises(AuthError) as e:
        await resolve_principal(token="tk_does_not_exist", x_project=None, session=session)
    assert e.value.status == 401


async def test_local_jwt_resolves_user_and_role(session, make_workspace):
    proj, user, _ = await make_workspace("acme", "tk_a", "a@acme.test", role="OWNER")
    p = await resolve_principal(token=tokens.issue_session(user.id), x_project=None, session=session)
    assert p.project_id == proj.id and p.user_id == user.id and p.role == "OWNER" and p.kind == "local"


async def test_tampered_jwt_is_401(session, make_workspace):
    _, user, _ = await make_workspace("acme", "tk_a", "a@acme.test")
    with pytest.raises(AuthError) as e:
        await resolve_principal(token=tokens.issue_session(user.id) + "x", x_project=None, session=session)
    assert e.value.status == 401


async def test_expired_jwt_is_401(session, make_workspace):
    _, user, _ = await make_workspace("acme", "tk_a", "a@acme.test")
    expired = tokens.issue_session(user.id, ttl_seconds=-10)
    with pytest.raises(AuthError):
        await resolve_principal(token=expired, x_project=None, session=session)


async def test_jwt_for_unknown_user_is_401(session):
    with pytest.raises(AuthError):
        await resolve_principal(token=tokens.issue_session("ghost"), x_project=None, session=session)


async def test_multi_membership_x_project_selection(session, make_workspace):
    p1, user, _ = await make_workspace("w1", "tk_1", "u@x.test", role="OWNER")
    p2, _, _ = await make_workspace("w2", "tk_2", "owner2@x.test", role="OWNER")
    session.add(models.Membership(id=str(uuid4()), user_id=user.id, project_id=p2.id, role="MEMBER"))
    await session.commit()
    token = tokens.issue_session(user.id)

    # no header → a project the user is a member of
    default = await resolve_principal(token=token, x_project=None, session=session)
    assert default.project_id in {p1.id, p2.id}

    # explicit header → that exact project, with the membership's role
    sel = await resolve_principal(token=token, x_project=p2.id, session=session)
    assert sel.project_id == p2.id and sel.role == "MEMBER"


async def test_x_project_non_member_is_403(session, make_workspace):
    _, user, _ = await make_workspace("w1", "tk_1", "u@x.test")
    p2, _, _ = await make_workspace("w2", "tk_2", "owner2@x.test")  # user is NOT a member of p2
    with pytest.raises(AuthError) as e:
        await resolve_principal(token=tokens.issue_session(user.id), x_project=p2.id, session=session)
    assert e.value.status == 403


async def test_tenant_isolation_each_key_resolves_own_project(session, make_workspace):
    pa, _, ka = await make_workspace("a", "tk_a", "a@a.test")
    pb, _, kb = await make_workspace("b", "tk_b", "b@b.test")
    assert pa.id != pb.id
    assert (await resolve_principal(token=ka.key, x_project=None, session=session)).project_id == pa.id
    assert (await resolve_principal(token=kb.key, x_project=None, session=session)).project_id == pb.id
