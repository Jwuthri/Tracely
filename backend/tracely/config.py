"""Centralized settings (pydantic-settings), read from environment / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
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
    llm_judge_model: str = "gpt-5.4-nano"

    # failure intelligence (embeddings + LangGraph agents) — needs an OpenAI key
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1024
    agent_model: str = "gpt-5.4-mini"
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

    # ── Auth & multi-tenancy ──────────────────────────────────────────────────────
    # "dev"   = no human auth; the ingest key is the only credential (today's behavior, no secret needed).
    # "local" = email/password owned by this backend; POST /auth/login issues an HS256 session JWT.
    # "clerk" = Clerk owns login/orgs/invites; this backend verifies Clerk's RS256 session JWT.
    auth_mode: str = "dev"
    # HS256 signing key for local-mode session JWTs. REQUIRED (>=32 chars) when auth_mode="local".
    session_secret: str = ""
    session_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    session_issuer: str = "tracely"
    # Clerk (auth_mode="clerk"): the issuer / Frontend API origin, e.g. https://<slug>.clerk.accounts.dev
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""  # blank → derived as f"{clerk_issuer}/.well-known/jwks.json"
    clerk_audience: str = ""  # optional 'aud' to pin; blank → not enforced
    clerk_secret_key: str = ""
    clerk_jwks_cache_seconds: int = 600
    # Hosted CORS: the browser-facing frontend origin allowed to call the API directly (blank → localhost only).
    frontend_origin: str = ""

    # ── Transactional email (Resend) ──────────────────────────────────────────────
    # Optional. When RESEND_API_KEY is set, team invites are emailed automatically; when blank the
    # invite link is only surfaced once in the UI for manual sharing (dev default — no email sent).
    resend_api_key: str = ""
    # Sender identity for invite emails. The default uses Resend's shared test domain, which only
    # delivers to your OWN Resend-account email — verify a domain (resend.com/domains) and set this to
    # e.g. "Tracely <invites@yourdomain.com>" to reach real teammates.
    email_from: str = "Tracely <onboarding@resend.dev>"
    # Public base URL of the frontend; used to build the accept-invite link inside invite emails.
    app_base_url: str = "http://localhost:3001"

    @model_validator(mode="after")
    def _validate_auth(self) -> "Settings":
        if self.auth_mode not in ("dev", "local", "clerk"):
            raise ValueError(f"AUTH_MODE must be dev|local|clerk, got {self.auth_mode!r}")
        if self.auth_mode == "local" and len(self.session_secret) < 32:
            raise ValueError("AUTH_MODE=local requires SESSION_SECRET (>=32 chars)")
        if self.auth_mode == "clerk" and not self.clerk_issuer:
            raise ValueError("AUTH_MODE=clerk requires CLERK_ISSUER")
        return self

    @property
    def resolved_clerk_jwks_url(self) -> str:
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        return f"{self.clerk_issuer.rstrip('/')}/.well-known/jwks.json" if self.clerk_issuer else ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
