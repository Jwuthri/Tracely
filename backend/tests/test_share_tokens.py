"""Share tokens are capabilities for one conversation — never credentials for a project.

The whole safety story is that the two token families cannot be swapped, so that is what these
check: a share token must be useless to `verify_session` (which is what `resolve_principal` feeds),
and a session token must be useless to `verify_share`.
"""

from __future__ import annotations

import time

import jwt
import pytest

from tracely.auth.tokens import (
    SHARE_ISSUER,
    TokenError,
    issue_session,
    issue_share,
    verify_session,
    verify_share,
)
from tracely.config import settings


def test_round_trip_returns_the_scope_it_was_minted_with():
    token = issue_share("proj-1", "thread-abc")
    assert verify_share(token) == ("proj-1", "thread-abc")


def test_share_token_is_not_a_session_token():
    """The one that matters: if this ever passes `verify_session`, a share link becomes a project
    read key the moment anyone puts it in an Authorization header."""
    with pytest.raises(TokenError):
        verify_session(issue_share("proj-1", "thread-abc"))


def test_session_token_is_not_a_share_token():
    with pytest.raises(TokenError):
        verify_share(issue_session("user-1"))


def test_expired_link_is_rejected():
    with pytest.raises(TokenError):
        verify_share(issue_share("proj-1", "thread-abc", ttl_seconds=-1))


def test_tampered_scope_is_rejected():
    """Re-signing with a different key must fail — otherwise anyone could mint a link for any
    project by editing the `pid` claim."""
    forged = jwt.encode(
        {
            "pid": "someone-elses-project",
            "tid": "thread-abc",
            "iss": SHARE_ISSUER,
            "exp": int(time.time()) + 60,
        },
        "not-the-real-secret",
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        verify_share(forged)


def test_alg_none_forgery_is_rejected():
    forged = jwt.encode(
        {
            "pid": "proj-1",
            "tid": "thread-abc",
            "iss": SHARE_ISSUER,
            "exp": int(time.time()) + 60,
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(TokenError):
        verify_share(forged)


def test_missing_scope_claims_are_rejected():
    """A validly signed token that omits `tid` must not fall through to "the whole project"."""
    partial = jwt.encode(
        {"pid": "proj-1", "iss": SHARE_ISSUER, "exp": int(time.time()) + 60},
        settings.session_secret,
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        verify_share(partial)
