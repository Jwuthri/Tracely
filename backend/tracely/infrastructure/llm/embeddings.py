"""OpenAI embedding wrapper, lazy-imported so workers/API start without it."""

from __future__ import annotations

from tracely.config import settings


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
        self.model = model or settings.embedding_model
        self.api_key = api_key or settings.openai_api_key
        self.dimensions = dimensions if dimensions is not None else settings.embedding_dim
        self._client = None

    def _ensure(self):
        if self._client is None:
            from langchain_openai import OpenAIEmbeddings

            self._client = OpenAIEmbeddings(
                model=self.model, api_key=self.api_key, dimensions=self.dimensions
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._ensure().embed_documents(texts)
