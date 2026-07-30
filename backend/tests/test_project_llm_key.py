"""A workspace's own OpenRouter key: encrypted at rest, Redis-cached, scoped via
`provider.use_project_key`.

`effective_openrouter_key()` must prefer the project's key inside the context, fall back to the
server-wide key outside it (or when the project has none / the lookup fails), and never leak a
key past the `with` block — the whole point of a workspace being able to bill its own eval spend
instead of ours.

The Redis seam is always pinned explicitly (never left to whatever is running on localhost), so
these tests neither depend on Redis being up nor pollute each other through a live cache.
"""

from __future__ import annotations

import types

import pytest

from tracely.config import settings
from tracely.infrastructure.db import repositories as repo_module
from tracely.infrastructure.llm import provider


class _FakeRedis:
    """Minimal stand-in for the two calls the key cache makes, plus counters so a test can prove
    the DB was (or wasn't) consulted."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, _ttl, v):
        self.store[k] = v.encode() if isinstance(v, str) else v

    def delete(self, k):
        self.store.pop(k, None)


class _DeadRedis:
    """Redis unreachable — every call raises, exercising the fall-through-to-Postgres path."""

    def _boom(self, *a, **kw):
        raise ConnectionError("redis down")

    get = setex = delete = _boom


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Default every test to the cache-miss path so the DB behavior is what's under test.
    Cache-specific tests override this with their own _FakeRedis."""
    monkeypatch.setattr(provider, "_redis", lambda: _DeadRedis())


def _counting_project_get(encrypted: str | None, counter: list):
    def _get(s, project_id):
        counter.append(project_id)
        return types.SimpleNamespace(openrouter_api_key_encrypted=encrypted)

    return _get


# ── encryption ────────────────────────────────────────────────────────────────


def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", "y" * 40)
    token = provider.encrypt_project_key("sk-or-abc123")
    assert token != "sk-or-abc123"
    assert provider._decrypt_project_key(token) == "sk-or-abc123"


def test_encrypt_requires_configured_server_key(monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", "")
    with pytest.raises(RuntimeError):
        provider.encrypt_project_key("sk-or-abc123")


def test_decrypt_degrades_to_none_on_bad_token(monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", "y" * 40)
    assert provider._decrypt_project_key("not-a-valid-fernet-token") is None


def test_rotated_encryption_key_degrades_instead_of_crashing(monkeypatch):
    """Re-keying the server must not take evaluation down: an undecryptable stored token falls
    back to the server-wide key rather than raising through the eval pipeline."""
    monkeypatch.setattr(settings, "secrets_encryption_key", "y" * 40)
    token = provider.encrypt_project_key("project-key")
    monkeypatch.setattr(settings, "secrets_encryption_key", "z" * 40)  # rotated
    monkeypatch.setattr(settings, "openrouter_api_key", "server-key")
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted=token),
    )
    with provider.use_project_key("proj-1"):
        assert provider.effective_openrouter_key() == "server-key"


# ── contextvar scoping ────────────────────────────────────────────────────────


def test_use_project_key_overrides_then_resets(monkeypatch):
    monkeypatch.setattr(settings, "secrets_encryption_key", "y" * 40)
    monkeypatch.setattr(settings, "openrouter_api_key", "server-key")
    encrypted = provider.encrypt_project_key("project-key")
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted=encrypted),
    )

    assert provider.effective_openrouter_key() == "server-key"
    with provider.use_project_key("proj-1"):
        assert provider.effective_openrouter_key() == "project-key"
    assert provider.effective_openrouter_key() == "server-key"


def test_nested_scopes_restore_the_outer_key(monkeypatch):
    """Two projects' work interleaving in one process must not bleed keys across each other."""
    monkeypatch.setattr(settings, "secrets_encryption_key", "y" * 40)
    monkeypatch.setattr(settings, "openrouter_api_key", "server-key")
    tokens = {
        "a": provider.encrypt_project_key("key-a"),
        "b": provider.encrypt_project_key("key-b"),
    }
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted=tokens[pid]),
    )
    with provider.use_project_key("a"):
        assert provider.effective_openrouter_key() == "key-a"
        with provider.use_project_key("b"):
            assert provider.effective_openrouter_key() == "key-b"
        assert provider.effective_openrouter_key() == "key-a"
    assert provider.effective_openrouter_key() == "server-key"


def test_use_project_key_falls_back_when_project_has_none(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "server-key")
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted=None),
    )
    with provider.use_project_key("proj-1"):
        assert provider.effective_openrouter_key() == "server-key"


def test_use_project_key_degrades_on_lookup_failure(monkeypatch):
    """A DB hiccup (or no Postgres reachable at all) must never block evaluation — it just means
    this call falls back to the server-wide key, same as a project with none configured."""
    monkeypatch.setattr(settings, "openrouter_api_key", "server-key")

    def boom(s, project_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(repo_module, "project_get", boom)
    with provider.use_project_key("proj-1"):
        assert provider.effective_openrouter_key() == "server-key"


# ── Redis cache ───────────────────────────────────────────────────────────────


def test_cache_hit_skips_postgres(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(provider, "_redis", lambda: fake)
    seen: list = []
    monkeypatch.setattr(repo_module, "project_get", _counting_project_get("enc-token", seen))

    assert provider._encrypted_key_for("proj-1") == "enc-token"
    assert provider._encrypted_key_for("proj-1") == "enc-token"
    assert len(seen) == 1  # second call served from Redis


def test_negative_result_is_cached(monkeypatch):
    """'No workspace key' is the common case — it must not cost a Postgres round-trip per trace."""
    fake = _FakeRedis()
    monkeypatch.setattr(provider, "_redis", lambda: fake)
    seen: list = []
    monkeypatch.setattr(repo_module, "project_get", _counting_project_get(None, seen))

    assert provider._encrypted_key_for("proj-1") is None
    assert provider._encrypted_key_for("proj-1") is None
    assert len(seen) == 1


def test_invalidate_forces_a_refetch(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(provider, "_redis", lambda: fake)
    seen: list = []
    monkeypatch.setattr(repo_module, "project_get", _counting_project_get("enc-token", seen))

    provider._encrypted_key_for("proj-1")
    provider.invalidate_project_key("proj-1")
    provider._encrypted_key_for("proj-1")
    assert len(seen) == 2  # invalidation dropped the entry, so Postgres was consulted again


def test_cache_is_per_project(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(provider, "_redis", lambda: fake)
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted=f"enc-{pid}"),
    )
    assert provider._encrypted_key_for("a") == "enc-a"
    assert provider._encrypted_key_for("b") == "enc-b"
    assert provider._encrypted_key_for("a") == "enc-a"


def test_redis_down_still_resolves_via_postgres(monkeypatch):
    monkeypatch.setattr(provider, "_redis", lambda: _DeadRedis())
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted="enc-token"),
    )
    assert provider._encrypted_key_for("proj-1") == "enc-token"


def test_cache_never_holds_plaintext(monkeypatch):
    """Redis is the Celery broker, not a secrets store: only ciphertext may be cached, so a Redis
    compromise alone can't hand over a customer's OpenRouter key."""
    monkeypatch.setattr(settings, "secrets_encryption_key", "y" * 40)
    fake = _FakeRedis()
    monkeypatch.setattr(provider, "_redis", lambda: fake)
    encrypted = provider.encrypt_project_key("sk-or-super-secret")
    monkeypatch.setattr(
        repo_module, "project_get",
        lambda s, pid: types.SimpleNamespace(openrouter_api_key_encrypted=encrypted),
    )
    with provider.use_project_key("proj-1"):
        assert provider.effective_openrouter_key() == "sk-or-super-secret"
    cached = b"".join(fake.store.values())
    assert b"sk-or-super-secret" not in cached
    assert cached == encrypted.encode()
