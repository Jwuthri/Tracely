"""Embedder picks OpenRouter when its key is set, OpenAI otherwise (model id differs)."""

from tracely.config import settings
from tracely.infrastructure.llm.embeddings import Embedder, embeddings_enabled


def test_openrouter_route(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-or-x")
    monkeypatch.setattr(settings, "openai_api_key", "")
    e = Embedder()
    assert embeddings_enabled()
    assert e.model == "openai/text-embedding-3-small"
    assert e.api_key == "sk-or-x"
    assert e.base_url == settings.openrouter_base_url


def test_openai_fallback(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "sk-oai")
    monkeypatch.setattr(settings, "embedding_model", "openai/text-embedding-3-small")
    e = Embedder()
    assert e.model == "text-embedding-3-small"
    assert e.api_key == "sk-oai"
    assert e.base_url is None


def test_no_key(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert not embeddings_enabled()
