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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
