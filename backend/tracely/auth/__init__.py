"""Multi-tenant auth: credential classification, session tokens, password hashing, Clerk JWKS
verification, and workspace provisioning. The FastAPI dependency layer lives in `tracely.api.auth`."""

from __future__ import annotations

from tracely.auth.principal import AuthError, Principal, resolve_principal

__all__ = ["AuthError", "Principal", "resolve_principal"]
