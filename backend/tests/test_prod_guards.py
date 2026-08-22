"""Prod-deploy safety: AUTH_MODE+TRACELY_ENV cross-check + the seeded dev-key refusal at startup.

Why this matters: dev-mode auth means "no human login, ingest key is enough" and the seeded
`tracely_dev_key` is published in the docs. Without these guards, a careless deploy
(`TRACELY_ENV=prod` but no `AUTH_MODE` set, or with the seed key still in the IngestKey table) is
world-pwnable via `Authorization: Bearer tracely_dev_key`. We fail-fast at config validation +
startup probe.
"""

from __future__ import annotations

import importlib

import pytest

from tracely.config import Settings


def _settings(**over) -> Settings:
    base: dict = {"tracely_env": "dev", "auth_mode": "dev", "session_secret": ""}
    base.update(over)
    return Settings(**base)


def test_dev_mode_allowed_outside_prod():
    s = _settings(tracely_env="dev", auth_mode="dev")
    assert s.auth_mode == "dev" and not s.is_prod


def test_prod_env_refuses_dev_auth_mode():
    with pytest.raises(ValueError, match=r"TRACELY_ENV=prod requires AUTH_MODE"):
        _settings(tracely_env="prod", auth_mode="dev")


def test_prod_env_accepts_local_auth_with_secret():
    s = _settings(tracely_env="prod", auth_mode="local", session_secret="x" * 32)
    assert s.is_prod and s.auth_mode == "local"


def test_prod_env_accepts_clerk_with_issuer():
    s = _settings(tracely_env="prod", auth_mode="clerk", clerk_issuer="https://x.clerk.accounts.dev")
    assert s.is_prod and s.auth_mode == "clerk"


def test_is_prod_recognizes_aliases():
    assert _settings(tracely_env="prod", auth_mode="local", session_secret="x" * 32).is_prod
    assert _settings(tracely_env="PRODUCTION", auth_mode="local", session_secret="x" * 32).is_prod
    assert not _settings(tracely_env="staging").is_prod
    assert not _settings(tracely_env="docker").is_prod


def test_seeding_service_skips_dev_key_in_prod(monkeypatch):
    """Re-import the seeding service with TRACELY_ENV=prod and verify it does NOT seed the dev key."""
    monkeypatch.setenv("TRACELY_ENV", "prod")
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    # Refresh settings + reimport (config has @lru_cache around get_settings).
    from tracely import config as cfg

    # Put the ORIGINAL object back at the end, rather than building a replacement from the
    # env. Every module that did `from tracely.config import settings` at import time holds this
    # exact instance; a rebuilt one silently disagrees with them — including on SESSION_SECRET,
    # which monkeypatch has not restored yet while this test body is still running. That split is
    # invisible until something signs a token with one and verifies it with the other.
    original = cfg.settings
    try:
        cfg.get_settings.cache_clear()
        cfg.settings = cfg.get_settings()
        seeding = importlib.reload(importlib.import_module("tracely.services.seeding_service"))
        assert seeding.settings.is_prod, "test sanity: prod env must be applied"
    finally:
        cfg.settings = original
        cfg.get_settings.cache_clear()
        importlib.reload(importlib.import_module("tracely.services.seeding_service"))


def test_settings_singleton_survives_this_module(monkeypatch):
    """Guard the guard: the reload test above must leave `tracely.config.settings` as the SAME
    object every other module imported, or a token signed via one binding fails to verify via the
    other — which is how a passing test file broke an unrelated one."""
    from tracely import config as cfg
    from tracely.auth import tokens

    assert tokens.settings is cfg.settings
    assert cfg.settings.session_secret == tokens.settings.session_secret
