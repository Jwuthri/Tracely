# Tracely

**Trace-native CI/CD for AI agents.** Production traces become regression tests.

This repo is the **MVP foundation slice**: OTLP/OpenInference traces → ClickHouse `events` + Postgres registry, with a minimal trace waterfall UI. The full design dossier (reverse-engineered Langfuse + the Tracely architecture, eval, regression, CI/CD, failure-intelligence) lives in [`design/`](design/README.md).

## Stack

| Layer | Tech |
|---|---|
| Backend | **FastAPI** (`backend/`, package `tracely`) — OTLP `/v1/traces` + reads **and** the shared domain (OTLP mapping, ClickHouse, registry, Celery tasks) |
| Workers | **Celery + Redis** (`workers/`) — blob → map → ClickHouse insert; runs the backend's tasks |
| OLAP | **ClickHouse** — `events` (one row per span) + `scores` |
| OLTP | **Postgres** + SQLAlchemy 2.0 + **Alembic** — agent registry (no Prisma) |
| Queue | **Redis** (Celery broker) |
| Blobs | **MinIO/S3** — raw OTLP body = source of truth (blob-first ingestion) |
| Frontend | **Next.js** (`frontend/`) — trace list + waterfall |
| SDK | **`tracely-sdk`** (`sdk/`) — instrument agents, export traces over OTLP |
| Schemas | **Pydantic v2** |
| Tooling | **uv** workspace (Python) + **pnpm** (frontend) |

Architecture deliberately mirrors Langfuse's proven write path — SDK/OTLP → S3 (durable) → Redis queue → worker → ClickHouse (`ReplacingMergeTree`) — reimplemented in Python. One adaptation: instead of Langfuse's in-process `ClickhouseWriter` buffer (no shared memory across Celery processes), we lean on ClickHouse **server-side `async_insert`** for batching.

## Prerequisites

- Docker + Docker Compose
- [uv](https://docs.astral.sh/uv/)
- Node 20+ and pnpm (for the web app)

## Quickstart

### Option A — everything in Docker (one command)

`docker compose up` builds and runs the whole stack: ClickHouse, Postgres, Redis, MinIO,
a one-shot **migrate** job (runs migrations + seeds the default project), **backend**,
**worker**, and **frontend**.

```bash
docker compose up -d --build --wait        # if host port 8000 is free
# or, if 8000 is taken on your machine:
TRACELY_BACKEND_PORT=8088 docker compose up -d --build --wait

# open the webapp:
open http://localhost:3000/traces          # (TRACELY_WEB_PORT to change the 3000 mapping)

# send a fake trace (agent -> llm -> failing tool) and refresh the page:
docker compose exec backend python scripts/send_test_trace.py   # raw OTLP
docker compose exec backend python sdk/example.py               # via the SDK

docker compose down                        # stop (add -v to wipe data)
```

The backend is reachable at `http://localhost:${TRACELY_BACKEND_PORT:-8000}` (OpenAPI at `/docs`).
Real agents point their OTLP exporter there with `Authorization: Bearer tracely_dev_key`.

### Option B — local dev (hot reload)

Infra in Docker, apps run locally (best for active development):

```bash
cp .env.example .env
make infra-up      # clickhouse, postgres, redis, minio (+ bucket)
make install       # uv sync + pnpm install
make migrate       # ClickHouse DDL + Alembic (Postgres)
make seed          # default project + ingest key  ->  tracely_dev_key

# three terminals (BACKEND_PORT note: free :8000 first, or run uvicorn on another port):
make backend       # http://localhost:8000  (OpenAPI at /docs)
make workers       # Celery ingestion worker
make frontend      # http://localhost:3000

make send-trace    # raw OTLP   (or: make sdk-example  to send via the SDK)
open http://localhost:3000/traces
```

## Tests

```bash
make test          # OTLP-mapper unit tests (no infra needed)
```

## Layout

```
backend/                       the `tracely` package: FastAPI API + shared domain
  tracely/
    config.py                  settings (pydantic-settings)
    clickhouse.py              CH client + async_insert path
    blobstore.py               S3/MinIO (blob-first)
    db.py                      async + sync SQLAlchemy engines
    models.py                  registry (Project, IngestKey, Agent, AgentVersion)
    events.py                  the CH `events` row schema (EVENT_COLUMNS)
    otel/mapping.py            OTLP span -> event (gen_ai / openinference / tracely.*)
    ingestion/                 blob-first enqueue
    celery_app.py, tasks.py    Celery app + ingest_otlp_blob task
    ch_migrations/             ClickHouse SQL (0001_events, 0002_scores)
    seed.py, ch_migrate.py     bootstrap helpers
    api/                       FastAPI (main, auth, routers: health/otlp/reads)
  migrations/                  Alembic (Postgres)
  alembic.ini, tests/
workers/tracely_workers/       Celery worker runtime (imports backend)
frontend/                      Next.js (trace list + waterfall)
sdk/tracely_sdk/               Python client SDK (instrument agents -> OTLP)
scripts/send_test_trace.py     raw-OTLP sample sender
design/                        full design dossier
```

## Ingesting from your agent

Point any OTLP/HTTP exporter at `http://localhost:8000/v1/traces` with header
`Authorization: Bearer tracely_dev_key`. Tracely reads standard `gen_ai.*` / OpenInference
attributes, plus first-class `tracely.*` hints:

- `tracely.agent.id` — the agent slug (auto-registered)
- `tracely.agent.version` — config hash / version ref (auto-registered as an AgentVersion)
- `tracely.conversation.id`, `tracely.turn.id`, `tracely.turn.index`, `tracely.step.id`, `tracely.step.name`
- `tracely.env` — `prod|staging|ci|dev` (the gating axis)

## What's next (post-MVP)

failure detection → clustering → **promote a failing trace into a regression case** → replay → **CI/CD gate (GitHub Action)**. See [`design/part2-tracely/10-mvp-and-roadmap.md`](design/part2-tracely/10-mvp-and-roadmap.md).
