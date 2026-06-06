# Tracely

**Trace-native CI/CD for AI agents.** Your agents' production traces become regression tests that block bad pull requests — automatically detected, grouped into issues, frozen with one click, and replayed for free on every PR.

> 💡 **The recorded run _is_ the test.** You never hand-author a dataset of questions and ideal answers — production already handed you the perfect failing example. Tracely freezes it and guards against it forever. Everything else (quality scores, failure clusters, suggested fixes, CI verdicts, trends) is **derived from the trace**. The trace is the source of truth.

📖 New here? Read the guided tour in **[OVERVIEW.md](OVERVIEW.md)**. Want the rationale? The full **[design dossier](design/README.md)** reverse-engineers Langfuse and designs Tracely on top.

---

## The spine

```
Production trace  →  Failure detection  →  Regression test  →  CI/CD gate
   (OTLP/OTel)        (auto evaluators)     (one-click promote)   (PR pass/fail)
```

The product maps onto it: **Observe** (trace explorer + trends) · **Detect** (online evaluators grade every run) · **Triage** (failures cluster into issues) · **Test** (promote a failing trace into a hermetic regression case) · **Ship** (replay the suite in CI and gate the PR).

## Stack

| Layer | Tech | Where |
|---|---|---|
| Backend (API + domain) | **FastAPI** + Pydantic v2 | [`backend/`](backend/README.md) |
| Workers | **Celery + Redis** | [`workers/`](workers/README.md) |
| Traces + scores (OLAP) | **ClickHouse** (`ReplacingMergeTree`) | `backend/tracely/ch_migrations` |
| Registry (OLTP) | **Postgres + pgvector** + SQLAlchemy 2.0 + Alembic | `backend/migrations` |
| Queue / Blobs | **Redis** / **MinIO·S3** (blob-first, source of truth) | — |
| Frontend | **Next.js 15** (App Router) + Tailwind | [`frontend/`](frontend/README.md) |
| SDK + CI gate CLI | **`tracely-sdk`** (OTel wrapper + `tracely` CLI) | [`sdk/`](sdk/README.md) |
| Tooling | **uv** workspace (Python) · **pnpm** (web) | — |

The write path deliberately mirrors Langfuse's proven design — **SDK/OTLP → S3 (durable) → Redis → worker → ClickHouse** — reimplemented in Python, with agent semantics promoted to **first-class indexed columns** (Langfuse keeps them as read-time strings). One adaptation: ClickHouse server-side `async_insert` instead of an in-process write buffer (Celery tasks don't share memory). [Why](design/part2-tracely/01-steal-and-do-not-copy.md)

## Quickstart

**Prerequisites:** Docker + Docker Compose, [uv](https://docs.astral.sh/uv/), and Node 20+ / pnpm for the web app.

### Option A — everything in Docker
```bash
docker compose up -d --build --wait            # ClickHouse, Postgres, Redis, MinIO, migrate, backend, worker, frontend
# host ports default to backend :8000 and web :3001 — remap if taken:
TRACELY_BACKEND_PORT=8088 TRACELY_WEB_PORT=3002 docker compose up -d --build --wait

open http://localhost:3001/traces              # the UI  (TRACELY_WEB_PORT to remap)

# populate a rich demo, then refresh:
docker compose exec backend python sdk/examples/seed_conversations.py   # every trace shape (RAG, multi-agent, multimodal, …)
docker compose exec backend python sdk/examples/seed_regression.py      # + a red→green CI gate demo (fills Cases + Gates)
# or a single sample trace:  docker compose exec backend python scripts/send_test_trace.py
docker compose down                            # stop  (add -v to wipe data)
```
The one-shot **migrate** service runs all migrations + seeds the default project & ingest key (`tracely_dev_key`). `backend`/`worker`/`frontend` run off source volume-mounts, so most edits need only a `docker compose restart <svc>` — **except** the Celery worker, which doesn't hot-reload.

### Option B — local dev (hot reload)
```bash
cp .env.example .env
make infra-up      # clickhouse, postgres, redis, minio
make install       # uv sync + pnpm install
make migrate       # ClickHouse DDL + Alembic (Postgres)
make seed          # default project + ingest key → tracely_dev_key
make backend       # FastAPI  :8000  (OpenAPI at /docs)   ┐
make workers       # Celery ingestion/eval worker          ├ three terminals
make frontend      # Next.js  :3000                        ┘
make seed-demo     # rich demo conversations   ·   make seed-regression   (red→green CI gate)
make send-trace    # a single sample OTLP trace
make test          # backend unit tests (no infra)
```

## Ingest from your agent

Point any OTLP/HTTP exporter at `POST {endpoint}/v1/traces` with `Authorization: Bearer tracely_dev_key`. Tracely reads standard `gen_ai.*` / OpenInference attributes plus first-class hints — `tracely.agent.id` (auto-registered), `tracely.agent.version`, `tracely.conversation.id` / `turn.*` / `step.*`, `tracely.observation.type`, and `tracely.env` (`prod|staging|ci|dev`, the gating axis). The [`tracely-sdk`](sdk/README.md) is the ergonomic path and also ships the `tracely gate` / `tracely replay` CI commands.

## Repo map — each folder has its own detailed README

| Folder | What's inside |
|---|---|
| [`backend/`](backend/README.md) | The `tracely` package: FastAPI API + the shared domain (OTLP mapping, ClickHouse/Postgres/S3, registry, evaluators, failure intelligence, regression, gate, Celery tasks). |
| [`workers/`](workers/README.md) | The deployable Celery worker runtime (imports the backend's tasks). |
| [`frontend/`](frontend/README.md) | The Next.js web app — the hierarchical trace explorer, clusters, cases, gates, trends. |
| [`sdk/`](sdk/README.md) | The Python SDK (instrument agents over OTLP, hermetic record-replay) + the `tracely` CI gate CLI. |
| [`scripts/`](scripts/README.md) | Dev/demo helpers (raw-OTLP sender, gate shim). |
| [`design/`](design/README.md) | The full design dossier — reverse-engineered Langfuse + the Tracely architecture, eval, regression, CI/CD, and failure-intelligence designs. |

## What's next

The near-term execution plan is in **[design/part2-tracely/11-prd-next-steps.md](design/part2-tracely/11-prd-next-steps.md)** — make evaluators first-class & editable (close the Observe→Detect loop), take the trace explorer to GA, and add real projects/auth. The long-term roadmap is in [10-mvp-and-roadmap.md](design/part2-tracely/10-mvp-and-roadmap.md).
