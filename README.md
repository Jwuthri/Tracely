# Tracely

**Trace-native CI/CD for AI agents.** Your agents' production traces become regression tests that block bad pull requests — automatically detected, grouped into issues, frozen with one click, and replayed for free on every PR.

> 💡 **The recorded run _is_ the test.** You never hand-author a dataset of questions and ideal answers — production already handed you the perfect failing example. Tracely freezes it and guards against it forever. Everything else (quality scores, failure clusters, suggested fixes, CI verdicts, trends) is **derived from the trace**. The trace is the source of truth.

📖 New here? Read the guided tour in **[OVERVIEW.md](OVERVIEW.md)**. Want the rationale? The full **[design dossier](design/README.md)** reverse-engineers Langfuse and designs Tracely on top.

🎬 **See the moat in 2 minutes → [DEMO.md](DEMO.md):** re-break an agent and watch the CI gate block the PR with a step-aligned trajectory diff — the move no dataset-first tool can reproduce.

---

## The spine

```
Production trace  →  Failure detection  →  Regression test  →  CI/CD gate
   (OTLP/OTel)        (auto evaluators)     (one-click promote)   (PR pass/fail)
```

The product maps onto it: **Observe** (trace explorer + trends + cross-metric meta-analysis) · **Detect** (online evaluators grade every run) · **Triage** (failures cluster into issues) · **Test** (promote a failing trace into a hermetic regression case) · **Ship** (replay the suite in CI and gate the PR).

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

# populate the WHOLE product (traces + clusters + Cases + Gates) in one command:
docker compose --profile demo up -d --build --wait     # adds a one-shot `demo` seeder, then refresh
# (or seed an already-running stack:  docker compose exec backend python scripts/seed_demo.py)
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
make frontend      # Next.js  :3001                        ┘
make demo          # populate the WHOLE product in one go: traces + clusters + Cases + Gates
make send-trace    # a single sample OTLP trace
make test          # backend unit tests (no infra)
```

### Option C — deploy to Railway

A pre-defined deployment for the whole stack — the three app services plus Postgres/pgvector, ClickHouse, Redis, and MinIO — lives in **[`deploy/railway/`](deploy/railway/README.md)**: add the four database templates, point three Railway services at the `deploy/railway/*.json` config files, wire the env from [`.env.railway.example`](deploy/railway/.env.railway.example), and deploy. Supports `local` (email/password) and `clerk` auth modes.

## Environment variables (key ones)

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_MODE` | `dev` | Auth mode: `dev` (open, no login) · `local` (email/password, self-host) · `clerk` (Clerk hosted SaaS). |
| `SESSION_SECRET` | — | Required when `AUTH_MODE=local`: HS256 signing key for JWTs (≥32 chars). |
| `CLERK_ISSUER` | — | Required when `AUTH_MODE=clerk`: Clerk issuer URL. |
| `OPENROUTER_API_KEY` | — | Enables LLM-as-judge evaluators (OpenRouter; any model). Skipped gracefully if absent. |
| `OPENAI_API_KEY` | — | Alternative LLM backend for judges + failure intelligence embeddings. |
| `TRACELY_BACKEND_PORT` | `8000` | Backend listen port (Docker compose override). |
| `TRACELY_WEB_PORT` | `3001` | Frontend listen port (Docker compose override). |

## Ingest from your agent

Point any OTLP/HTTP exporter at `POST {endpoint}/v1/traces` with `Authorization: Bearer tracely_dev_key`. Tracely reads standard `gen_ai.*` / OpenInference attributes plus first-class hints — `tracely.agent.id` (auto-registered), `tracely.agent.version`, `tracely.conversation.id` / `turn.*` / `step.*`, `tracely.observation.type`, and `tracely.env` (`prod|staging|ci|dev`, the gating axis). The [`tracely-sdk`](sdk/README.md) is the ergonomic path and also ships the `tracely gate` / `tracely replay` CI commands.

## Gate your PRs (CI/CD)

The differentiated half: a promoted production failure becomes a regression test that **blocks the PR** that reintroduces it. The gate **exits non-zero on failure** (so it blocks the check) and posts a commit status + PR comment. All you need is a **`key`** (your ingest key — it identifies your workspace), your Tracely **`api`** URL, and the **`agent`** slug. Wire it one of two ways, depending on how your CI runs your agent.

### Option A — gate the traces your CI already emits (lightest)

If your pipeline already runs your agent instrumented with `tracely.env=ci`, the gate just matches those traces to your promoted cases (by input) and returns PASS/FAIL — no agent code wiring. Use the bundled composite action:

```yaml
# .github/workflows/tracely.yml
name: Tracely gate
on: pull_request
permissions:
  contents: read
  statuses: write          # post the blocking commit status
  pull-requests: write     # upsert the results comment
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # → your existing step(s) that run the agent and emit env=ci traces go here ←
      - uses: Jwuthri/Tracely/.github/actions/tracely-gate@master
        with:
          agent: planner                       # which agent's promoted suite to run
          api:   https://tracely.your-co.dev   # your Tracely backend (TRACELY_API)
          key:   ${{ secrets.TRACELY_KEY }}    # your ingest key = your workspace
          # the SDK isn't on PyPI yet — install it from this repo until it is:
          sdk-spec: "tracely-sdk @ git+https://github.com/Jwuthri/Tracely#subdirectory=sdk"
```

### Option B — replay the recorded cases against your code (hermetic)

This re-runs your agent on each promoted case's *recorded input*, serving the recorded tool/LLM outputs as fixtures — deterministic, offline, **no API keys, no cost** — then gates. It guarantees the exact failing inputs are tested. Run the CLI directly:

```yaml
      - run: pip install "tracely-sdk @ git+https://github.com/Jwuthri/Tracely#subdirectory=sdk"
      - run: tracely replay planner --entrypoint my_pkg.agent:run    # a Python agent
        # …or any language:  tracely replay planner --cmd "node run.js"  (your script reads $TRACELY_INPUT)
        env:
          TRACELY_API: https://tracely.your-co.dev
          TRACELY_KEY: ${{ secrets.TRACELY_KEY }}
```

Hermetic replay requires your agent to route tool/model calls through the SDK's `call_tool` / `call_llm` seam (see [the SDK guide](sdk/README.md)); add `--live` to make real calls instead. Both commands auto-detect the PR/commit from the Actions context; `web-url` / `TRACELY_WEB_URL` is optional and only builds the "view gate run" link in the PR comment.

> ℹ️ The repo's own [`.github/workflows/tracely-gate.yml`](.github/workflows/tracely-gate.yml) is Tracely **dogfooding itself** — it replays the bundled `weather_agent` example, which is why it uses an in-repo `pip install ./sdk` and `--entrypoint weather_agent:run`. **Your** integration is one of the two options above, not that file.

## Repo map — each folder has its own detailed README

| Folder | What's inside |
|---|---|
| [`backend/`](backend/README.md) | The `tracely` package: FastAPI API + the shared domain (OTLP mapping, ClickHouse/Postgres/S3, registry, evaluators, failure intelligence, regression, gate, auth, Celery tasks). |
| [`workers/`](workers/README.md) | The deployable Celery worker runtime (imports the backend's tasks). |
| [`frontend/`](frontend/README.md) | The Next.js web app — the hierarchical trace explorer, clusters, cases, gates, trends, settings, and auth flows. |
| [`sdk/`](sdk/README.md) | The Python SDK (instrument agents over OTLP, hermetic record-replay) + the `tracely` CI gate CLI. |
| [`docs/`](docs/README.md) | The **SDK documentation site** (Nextra / Next.js + MDX) — how it works, instrumentation guide, full API reference, hermetic replay, CI gate. `make docs` → :3002. |
| [`scripts/`](scripts/README.md) | Dev/demo helpers (raw-OTLP sender, the one-command full-product `seed_demo.py`, gate shim). |
| [`design/`](design/README.md) | The full design dossier — reverse-engineered Langfuse + the Tracely architecture, eval, regression, CI/CD, and failure-intelligence designs. |

## What's shipped

The core **trace → detect → cluster → regression → gate** loop is end-to-end:

- **Ingest:** any OTLP/HTTP source, first-class agent semantics, blob-first durability.
- **Evaluate:** DB-backed evaluators as **TurnWise-style table columns** — CRUD from the UI, run on every ingest. Multi-output LLM-as-judge (score / number / boolean / text / JSON with custom schema) at conversation / run / span granularity, in **basic** (context auto-injected) or **advanced** (`@VARIABLE` template prompts with live preview + autocomplete) mode. Batch and sequential (chained) execution. Per-evaluator targeting (agent/env) + deterministic sampling to scope judge spend; **advisory** evaluators record a verdict without flipping the roll-up.
- **Auth:** three modes — `dev` (open), `local` (email/password + invite flow + change-password, self-host), `clerk` (hosted SaaS). Team management, API keys, invitations, account settings.
- **Triage:** structural + semantic failure clustering, a creatable suggested-evaluator draft, promote-to-case.
- **Regression:** hermetic fixture bundles, fail-to-pass contracts, CI replay.
- **Gate:** PR blocking via `tracely replay` / `tracely gate`, GitHub status + comment.
- **Insights:** daily traces/failures/gate pass-rate **Trends** + per-agent cross-metric **meta-analysis** (Spearman correlations + z-score outliers, LLM-synthesized).
- **Conversation intelligence:** real-time **rolling summary** (accumulating per-turn memory backing the judge's `@HISTORY`) + a **conversation-agents** panel (declared via the SDK, or derived from spans).
- **CI:** the repo's own GitHub Actions pipeline (ruff + pytest + `next build` + prod Docker images) and Dependabot, alongside the regression-gate dogfood.

The near-term execution plan is in **[design/part2-tracely/11-prd-next-steps.md](design/part2-tracely/11-prd-next-steps.md)** and the long-term roadmap is in [10-mvp-and-roadmap.md](design/part2-tracely/10-mvp-and-roadmap.md).
