"""Clerk session-JWT verification (RS256 via JWKS) for hosted mode.

Security: the algorithm is PINNED to RS256, the issuer is pinned to CLERK_ISSUER, the audience is pinned
when configured, and JWKS keys are fetched lazily + cached by `kid` (PyJWKClient handles the cache and
re-fetch on an unknown kid). Claims are read ONLY after the signature verifies; the User/Project/
Membership are then upserted from those verified claims.

Note: org claims (`org_id`, `org_role`) are present in Clerk session tokens when organizations are
active; `email`/`name` require a Clerk JWT template (the frontend requests it via getToken({template})).
Tenant mapping relies only on `sub` + `org_id`, so a missing email is cosmetic, never a security issue."""

from __future__ import annotations

import jwt
from jwt import PyJWKClient
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.auth.principal import AuthError, Principal, select_membership
from tracely.config import settings

_jwks_client: PyJWKClient | None = None


def _client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = settings.resolved_clerk_jwks_url
        if not url:
            raise AuthError(500, "CLERK_ISSUER / CLERK_JWKS_URL not configured")
        # cache signing keys for the configured lifespan; PyJWKClient re-fetches on an unknown kid
        _jwks_client = PyJWKClient(
            url, cache_keys=True, lifespan=settings.clerk_jwks_cache_seconds
        )
    return _jwks_client


def _verify(token: str) -> dict:
    try:
        # NOTE: PyJWKClient does a (cached) synchronous JWKS fetch — only the first request after a
        # cache miss / key rotation blocks briefly; acceptable given the ~10min cache.
        signing_key = _client().get_signing_key_from_jwt(token)
        kwargs: dict = {
            "algorithms": ["RS256"],
            "issuer": settings.clerk_issuer,
            "options": {"require": ["exp", "iss", "sub"]},
        }
        if settings.clerk_audience:
            kwargs["audience"] = settings.clerk_audience
        return jwt.decode(token, signing_key.key, **kwargs)
    except jwt.PyJWTError as e:
        raise AuthError(401, "invalid session") from e
    except AuthError:
        raise
    except Exception as e:  # JWKS fetch / network / malformed key
        raise AuthError(401, "invalid session") from e


def _role_from_claims(claims: dict) -> str:
    org_role = str(claims.get("org_role") or "").lower()
    if "admin" in org_role:
        return "ADMIN"
    if not claims.get("org_id"):
        return "OWNER"  # personal workspace → the user owns it
    return "MEMBER"


async def resolve_clerk_jwt(
    token: str, x_project: str | None, session: AsyncSession
) -> Principal:
    from tracely.auth import provisioning  # lazy: keeps clerk deps out of dev/local import paths

    claims = _verify(token)
    principal = await provisioning.upsert_clerk_principal(
        session,
        clerk_user_id=claims["sub"],
        email=(claims.get("email") or claims.get("email_address") or ""),
        display_name=(claims.get("name") or claims.get("full_name") or ""),
        org_id=claims.get("org_id"),
        role=_role_from_claims(claims),
    )
    # X-Tracely-Project override: only honor a project the user is actually a member of
    if x_project and x_project != principal.project_id:
        return await select_membership(principal.user_id, x_project, session, kind="clerk")
    return principal
