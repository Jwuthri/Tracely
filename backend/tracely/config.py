"""Centralized settings (pydantic-settings), read from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tracely_env: str = "dev"

    # Postgres
    database_url: str = "postgresql+asyncpg://tracely:tracely@localhost:5432/tracely"
    alembic_database_url: str = "postgresql+psycopg://tracely:tracely@localhost:5432/tracely"

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "tracely"
    clickhouse_async_insert: int = 1

    # Redis (Celery)
    redis_url: str = "redis://localhost:6379/0"

    # S3 / MinIO
    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "tracely"
    s3_secret_access_key: str = "tracely-secret"
    s3_bucket: str = "tracely-events"
    s3_event_prefix: str = "events/"

    ingestion_delay_seconds: int = 0
    # Spans/traces with no agent are attributed to this fallback agent slug, so agent-scoped
    # features (failure clusters, CI gates) still apply to plain LLM calls. Set to "" to disable
    # and leave agent-less traces unattributed.
    default_agent_slug: str = "default"

    # online evaluation
    eval_latency_budget_ms: int = 60000
    # optional LLM-as-judge (auto quality eval); skipped if no key is set
    llm_judge_api_key: str = ""
    llm_judge_base_url: str = "https://api.openai.com/v1"
    llm_judge_model: str = "gpt-4o-mini"

    # failure intelligence (embeddings + LangGraph agents) — needs an OpenAI key
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1024
    agent_model: str = "gpt-4o-mini"
    # cluster directly on cosine distance below this many failures; UMAP-denoise at/above it
    # (UMAP needs a large, diverse set — on few/near-duplicate points it invents structure).
    fi_umap_min_n: int = 50
    fi_min_cluster_size: int = 2

    # CI/CD gate soft thresholds — latency/token deltas vs the baseline (last green gate) raise a
    # WARNING by default (not a hard fail); fail-to-pass stays the only blocking gate unless the
    # block flag is set. Percentages are "% worse than baseline".
    gate_latency_warn_pct: float = 25.0
    gate_tokens_warn_pct: float = 25.0
    gate_block_on_warnings: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
