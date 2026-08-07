"""Embedding wrapper, lazy-imported so workers/API start without it.

Routes through OpenRouter's OpenAI-compatible `/embeddings` endpoint when `OPENROUTER_API_KEY`
is set (one key for the whole pipeline), else a direct `OPENAI_API_KEY`.
"""

from __future__ import annotations

from tracely.config import settings
from tracely.infrastructure.llm import provider


def embeddings_enabled() -> bool:
    """Whether an embedding credential applies right now. Inside `provider.use_project_key()`
    only the workspace's own OpenRouter key counts — no fallback to the server's keys. Under
    `REQUIRE_PROJECT_LLM_KEY` (hosted infra) the server keys never count, scoped or not."""
    if provider.project_scoped():
        return bool(provider.effective_openrouter_key())
    if settings.require_project_llm_key:
        return False
    return bool(settings.openrouter_api_key or settings.openai_api_key)


class Embedder:
    """Thin facade over `langchain_openai.OpenAIEmbeddings`. The LangChain client itself caches
    nothing useful, so it's cheap to construct per call — but we keep one per instance for the
    common batch-embed path.

    `model`/`api_key`/`base_url` are resolved lazily (properties, not `__init__` state) so a
    caller that constructs the `Embedder` before entering `provider.use_project_key(...)` (e.g.
    `FailureIntelService.__init__`) still picks up the project's key once `.embed()` actually
    runs inside that scope."""

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self._model_arg = model
        self._api_key_arg = api_key
        self.dimensions = dimensions if dimensions is not None else settings.embedding_dim
        self._client = None

    def _resolved(self) -> tuple[str, str | None, str | None]:
        name = (self._model_arg or settings.embedding_model).strip()
        # Same schema either way; only the model id differs — OpenRouter wants
        # `openai/text-embedding-3-small`, OpenAI wants it bare.
        key = self._api_key_arg or provider.effective_openrouter_key()
        if key:
            return (name if "/" in name else f"openai/{name}"), key, settings.openrouter_base_url
        if provider.project_scoped() or settings.require_project_llm_key:
            # Workspace key or nothing — never the server's OpenAI key. The hard-gate flag
            # extends that to unscoped calls too (a path that forgot `use_project_key()`).
            return name, None, None
        return name.removeprefix("openai/"), settings.openai_api_key, None

    @property
    def model(self) -> str:
        return self._resolved()[0]

    @property
    def api_key(self) -> str | None:
        return self._resolved()[1]

    @property
    def base_url(self) -> str | None:
        return self._resolved()[2]

    def _ensure(self):
        if self._client is None:
            from langchain_openai import OpenAIEmbeddings

            model, api_key, base_url = self._resolved()
            self._client = OpenAIEmbeddings(
                model=model, api_key=api_key, base_url=base_url, dimensions=self.dimensions
            )
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._ensure().embed_documents(texts)
