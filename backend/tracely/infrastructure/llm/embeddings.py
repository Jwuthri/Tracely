"""Embedding wrapper, lazy-imported so workers/API start without it.

Routes through OpenRouter's OpenAI-compatible `/embeddings` endpoint when `OPENROUTER_API_KEY`
is set (one key for the whole pipeline), else a direct `OPENAI_API_KEY`.
"""

from __future__ import annotations

from tracely.config import settings


def embeddings_enabled() -> bool:
    """Whether any embedding credential is configured (either key works)."""
    return bool(settings.openrouter_api_key or settings.openai_api_key)


class Embedder:
    """Thin facade over `langchain_openai.OpenAIEmbeddings`. The LangChain client itself caches
    nothing useful, so it's cheap to construct per call — but we keep one per instance for the
    common batch-embed path."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        name = (model or settings.embedding_model).strip()
        # Same schema either way; only the model id differs — OpenRouter wants
        # `openai/text-embedding-3-small`, OpenAI wants it bare.
        if not api_key and settings.openrouter_api_key:
            self.model = name if "/" in name else f"openai/{name}"
            self.api_key = settings.openrouter_api_key
            self.base_url: str | None = settings.openrouter_base_url
        else:
            self.model = name.removeprefix("openai/")
            self.api_key = api_key or settings.openai_api_key
            self.base_url = None
        self.dimensions = dimensions if dimensions is not None else settings.embedding_dim
        self._client = None

    def _ensure(self):
        if self._client is None:
            from langchain_openai import OpenAIEmbeddings

            self._client = OpenAIEmbeddings(
                model=self.model,
                api_key=self.api_key,
                base_url=self.base_url,
                dimensions=self.dimensions,
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._ensure().embed_documents(texts)
