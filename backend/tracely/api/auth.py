"""FastAPI auth dependencies.

Resolves the project from any of three credentials — an ingest key (SDK/CI), a local session JWT, or a
Clerk session JWT — via `tracely.auth.resolve_principal`, then exposes:

- `get_principal`  : the full Principal (project_id + optional user_id/role)
- `get_project_id` : just the project_id — the data routers depend on THIS (signature unchanged)
- `require_role`   : a dependency factory for admin-only endpoints
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tracely.auth import AuthError, Principal, resolve_principal
from tracely.infrastructure.db.session import get_session


def _extract_token(authorization: str | None, x_tracely_key: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return x_tracely_key


async def get_principal(
    authorization: str | None = Header(default=None),
    x_tracely_key: str | None = Header(default=None),
    x_tracely_project: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    token = _extract_token(authorization, x_tracely_key)
    if not token:
        raise HTTPException(status_code=401, detail="missing credentials")
    try:
        return await resolve_principal(
            token=token, x_project=x_tracely_project, session=session
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from None


async def get_project_id(principal: Principal = Depends(get_principal)) -> str:
    return principal.project_id


def require_role(
    *roles: str,
) -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def _require(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="insufficient role")
        return principal

    return _require
