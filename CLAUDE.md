# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Tracely is trace-native CI/CD for AI agents: **production trace → failure detection → regression test → CI/CD gate**. The trace is the source of truth; evals, clusters, cases, gates and trends are all derived from it. There are no hand-authored datasets.

A `uv` workspace (`backend`, `workers`, `sdk`) plus a pnpm Next.js app (`frontend`) and a Nextra docs site (`docs`).

## Commands

```bash
make install                     # uv sync --all-packages --all-extras + pnpm install
make infra-up                    # clickhouse, postgres, redis, minio (docker)
make migrate                     # ClickHouse DDL runner + Alembic (Postgres)
make seed                        # default project + ingest key `tracely_dev_key`
make backend / workers / frontend    # three terminals: FastAPI :8000 · Celery · next dev
make demo                        # populate the whole product (traces, clusters, cases, gates)
```

Tests — no infra required, ~6s:

```bash
uv run pytest -q backend/tests sdk/tests        # what CI runs
uv run pytest -q backend/tests/test_gate_eval.py::test_name -x     # single test
uv run ruff check . && uv run ruff format .
cd frontend && pnpm test        # vitest; pnpm test:watch; pnpm build type-checks (tsc) + lints
```

`make test` only runs `backend/tests`; run `sdk/tests` too before pushing. Alembic: `cd backend && uv run alembic revision -m "…"` / `alembic upgrade head`. ClickHouse migrations are `*.up.sql` files in `backend/tracely/infrastructure/clickhouse/ddl/` applied by `python -m tracely.infrastructure.clickhouse.migrations`.

Whole stack in Docker: `docker compose up -d --build --wait` → UI on **:3001**, backend on **:8000** (remap with `TRACELY_WEB_PORT` / `TRACELY_BACKEND_PORT`). `make frontend` runs plain `next dev` (:3000) — use `cd frontend && pnpm dev -p 3001` to match Docker.

## Architecture

Write path (deliberately mirrors Langfuse, reimplemented in Python):

```
SDK/OTLP → POST /v1/traces → S3 blob (durable FIRST) → Redis/Celery
  → worker: otel/ mapping → registry upsert → ClickHouse events
  → evaluate_run_task (countdown=4, debounces late spans) → scores + structural clustering
```

Five stores: **ClickHouse** (`events` one row per span + `scores`, `ReplacingMergeTree`) · **Postgres + pgvector** (registry: projects, keys, agents, cases, gates, clusters, evaluators, users, monitors, annotations) · **S3/MinIO** (raw OTLP body = source of truth, plus regression fixture bundles) · **Redis** (Celery) · **pgvector** (failure embeddings).

`backend/tracely/` is one package with three roles (FastAPI app, shared domain, Celery tasks) and strict layering:

| Layer | Rule |
|---|---|
| `domain/` | Pure logic, **no I/O**. Stats, verdict policy, contracts, trajectories, template resolution. |
| `infrastructure/` | Every adapter: `clickhouse/`, `db/`, `blob/`, `queue/`, `llm/`, `notifications/`, `registry/`. |
| `services/` | Use-case orchestrator classes (`IngestionService`, `EvaluationService`, `GateService`, …). |
| `api/`, `workers/` | Thin. Routers shape HTTP; tasks dispatch into a service. |

`workers/` is a deployable shim that imports `tracely.workers.tasks`. `sdk/` is the instrumentation SDK **and** the `tracely gate` / `tracely replay` CI CLI.

## Hard rules

- **No SQL in `api/routers/`.** ClickHouse reads go through `infrastructure/clickhouse/async_reader.py` (async, for the API) or `trace_reader.py` (sync, for workers/services); Postgres through `infrastructure/db/repositories.py`; auth lookups through `auth/queries.py`. Adding a query means adding a function there, not inlining SQL in a router. (`health.py`'s `SELECT 1` probe is the sole exception.)
- **Every LLM call goes through `infrastructure/llm/provider.py`** (`run_structured_agent` / `run_text_agent` — LangChain `create_agent` on OpenRouter, OpenAI as fallback). Never construct a client elsewhere. LLM modules are lazy-imported and `llm_enabled()` gates them: with no key the pipeline must still run (judge/FI/meta-analysis degrade, not crash).
- **Everything is scoped by `project_id`**, resolved from `Authorization: Bearer <ingest-key>` via `api/auth`. Every read and write takes it.
- **Writes are idempotent.** Deterministic ids (score id = `uuid5(trace_id:name:span_id)`) + `ReplacingMergeTree` mean re-ingest/re-eval converges instead of duplicating. Anything sampled must be deterministic per `(trace_id, score_name)` for the same reason (`domain/evaluation/targeting.py`).
- **One verdict policy.** A trace/turn/session fails iff it has a `FAIL` on a **non-advisory** evaluator. Python: `domain/evaluation/verdict.py`. Its SQL twin lives in `async_reader` (`name NOT IN {adv:Array(String)}`), fed by `api/advisory.py`. Change both together or the badge, threads dot, and trends disagree.
- **Frontend fetch pattern:** Server Components (pages) call `app/lib/api.ts` directly; Client Components fetch a thin proxy under `app/api/*` which re-issues with the Bearer key server-side. `TRACELY_KEY` / `TRACELY_API` must never reach the browser — do not add an `env:` block to `next.config.mjs`.
- **New backend env var?** Add it to `config.py` (`Settings`) *and* the `x-app-env` anchor at the top of `docker-compose.yml` — `.env` alone won't reach the containers.

## Gotchas

- The Celery **worker does not hot-reload**. After touching worker/eval/failure-intel/otel-mapping code: `docker compose restart worker` (backend/frontend are volume-mounted and do reload).
- Celery runs `--pool=solo --concurrency=1` locally on purpose — numba/UMAP/HDBSCAN in failure intelligence are fork-fragile.
- `AUTH_MODE` is `dev` (open) | `local` (email/password + JWT, needs `SESSION_SECRET`) | `clerk`. The frontend's `NEXT_PUBLIC_AUTH_MODE` must match the backend's. Prod refuses to boot with `AUTH_MODE=dev` or a seeded `tracely_dev_key`.
- OTLP arrives in three message conventions (structured / OpenInference-flattened / OpenLLMetry legacy); `otel/messages.py` normalizes them. Fix I/O rendering bugs there, not in the frontend renderers.
- `uv sync --frozen` in CI catches lock/extra drift — regenerate `uv.lock` when touching deps.

## Where the detail lives

Each folder has a thorough README; read it before changing that area rather than re-deriving from code.

| Path | Contents |
|---|---|
| `backend/README.md` | Full flow walkthroughs (ingest, eval, failure intel, regression, gate, auth, rolling summary, meta-analysis), module map, API surface, schema/migration list. |
| `frontend/README.md` | Data-flow rule, app shell, per-route fetch table, theme tokens. |
| `sdk/README.md` | Auto + manual instrumentation, the `tracely.*` attributes the backend indexes, hermetic replay seam, CLI. |
| `README.md`, `OVERVIEW.md`, `DEMO.md`, `DEPLOY.md` | Quickstart / guided tour / 2-min demo / Railway runbook. |
| `design/` | The design dossier — the "why" behind every decision above. |
| `docs/` | The published SDK docs site (Nextra, `make docs` → :3002). |
