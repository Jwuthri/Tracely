<div align="center">

<img src="frontend/app/icon.svg" width="76" alt="Tracely" />

# Tracely

### Production failures become regression tests.

**Trace-native CI/CD for AI agents.** Tracely grades every agent trace as it lands, clusters the
failures into issues, freezes the bad runs into hermetic replayable cases — and blocks the pull
request that would ship them again.

```
production trace  →  failure detection  →  regression test  →  CI gate
```

[**Website**](https://tracely-studio.xyz) · [**Docs**](https://doc.tracely-studio.xyz) · [**Guided tour**](OVERVIEW.md) · [**2-min demo**](DEMO.md) · [**Design dossier**](design/README.md)

[![CI](https://github.com/Jwuthri/Tracely/actions/workflows/ci.yml/badge.svg)](https://github.com/Jwuthri/Tracely/actions/workflows/ci.yml) [![PyPI](https://img.shields.io/pypi/v/tracely-ai?logo=pypi&logoColor=white)](https://pypi.org/project/tracely-ai/) [![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://pypi.org/project/tracely-ai/) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![Stars](https://img.shields.io/github/stars/Jwuthri/Tracely?style=flat&logo=github)](https://github.com/Jwuthri/Tracely/stargazers)

<img src=".github/assets/dashboard.png" alt="Tracely dashboard — traces, failure clusters, auto-detected failures and regression cases" width="100%" />

</div>

---

## Why another agent-observability tool?

Because observability stops at the dashboard. You can see that your agent broke — then what?

Every eval tool asks you to **hand-author a dataset**: sit down, invent questions, write ideal
answers, keep them current as the product changes. That dataset is a guess about what might break.

Production already handed you the real thing: a trace of the exact run that failed, with the exact
input, the exact tool calls, the exact model responses.

> **The recorded run _is_ the test.** Tracely freezes that trace into a hermetic regression case and
> replays it on every PR. Everything else — quality scores, failure clusters, suggested fixes, CI
> verdicts, trends — is **derived from the trace**. There are no hand-authored datasets.

|  | Dataset-first tools | Tracely |
|---|---|---|
| Where tests come from | You write them | Promoted from real failing traces |
| Fidelity to production | A guess | The exact failing run, byte for byte |
| Cost to replay in CI | Live model calls | **$0** — recorded tool/LLM fixtures |
| What happens on regression | A dashboard number moves | **The PR is blocked** |

---

## The spine

The product maps onto four steps. Each one is a page in the app.

### 1 · Observe — every run, hierarchically

Traces arrive over plain OTLP. Agent semantics (`agent.id`, `conversation.id`, `turn`, `step`) are
promoted to first-class indexed columns, so runs group into conversation threads instead of a flat
span soup. The waterfall shows agent → tool → thinking → generation, with the failing span in red.

<img src=".github/assets/trace-timeline.png" alt="Trace timeline — agent, tool, thinking and generation spans with the failing tool call highlighted" width="100%" />

Evaluators are **columns on the trace table**, not a separate tab — each one grades at conversation,
run or span level and writes its verdict into the grid. Scores stream in live over SSE as judges
finish, so you watch a run get graded in place.

<img src=".github/assets/traces.png" alt="Trace explorer — conversation threads with an evaluator column showing PASS/FAIL verdicts and scores" width="100%" />

### 2 · Detect & triage — failures group into issues

Online evaluators grade every run as it lands (LLM-as-judge at conversation / run / span level, plus
structural checks that need no model at all). Failures then cluster — structurally and semantically —
so 31 broken runs become **one issue with a count**, not 31 rows to read.

<img src=".github/assets/clusters.png" alt="Failure clusters — auto-detected failures grouped into issues with occurrence counts" width="100%" />

### 3 · Test — freeze the failure

One click promotes a failing trace into a hermetic case: recorded input, tool and LLM outputs bundled
as fixtures, and a **fail-to-pass contract** attached — the case must fail on the old code and pass on
the fix, or the promotion isn't trusted.

<img src=".github/assets/case.png" alt="Regression case — promoted, fail-to-pass validated, with assertions and reference trajectory" width="100%" />

### 4 · Ship — block the PR

The suite replays in CI against recorded fixtures: deterministic, offline, **no API keys and no model
spend**. `tracely gate` exits non-zero, posts a commit status, and upserts a PR comment.

<img src=".github/assets/gate-run.png" alt="A failing CI gate run — FAIL, 0 passed, 1 failed, with the judge's reason" width="100%" />

### Plus — trends and cross-metric analysis

Daily failure and gate pass-rates, latency percentiles, token spend, and per-agent meta-analysis
(Spearman correlations + z-score outliers, LLM-synthesized).

<img src=".github/assets/trends.png" alt="Trends — failure rate, gate pass-rate, latency percentiles, token and cost metrics over time" width="100%" />

---

## Quickstart

**Prerequisites:** Docker + Docker Compose. (For local dev also [uv](https://docs.astral.sh/uv/) and Node 20+ / pnpm.)

### Everything in Docker — the whole product, populated

```bash
git clone https://github.com/Jwuthri/Tracely && cd Tracely
docker compose --profile demo up -d --build --wait
open http://localhost:3001
```

That brings up ClickHouse, Postgres, Redis and MinIO, runs every migration, seeds the default project
and ingest key (`tracely_dev_key`), then populates **traces, clusters, cases and gates** — so the app
opens with the screenshots above rather than an empty shell.

```bash
docker compose down            # stop  (add -v to wipe data)
```

Host ports default to web **:3001** and backend **:8000**; remap with `TRACELY_WEB_PORT` / `TRACELY_BACKEND_PORT`.
`backend`/`worker`/`frontend` run off source volume-mounts, so most edits need only `docker compose restart <svc>` —
**except** the Celery worker, which doesn't hot-reload.

### Local dev (hot reload)

```bash
cp .env.example .env
make infra-up      # clickhouse, postgres, redis, minio
make install       # uv sync + pnpm install
make migrate       # ClickHouse DDL + Alembic (Postgres)
make seed          # default project + ingest key → tracely_dev_key

make backend       # FastAPI  :8000  (OpenAPI at /docs)   ┐
make workers       # Celery ingestion/eval worker          ├ three terminals
make frontend      # Next.js  :3001                        ┘

make demo          # populate the WHOLE product: traces + clusters + cases + gates
make test          # backend unit tests (no infra, ~6s)
```

### Deploy your own (Railway, ~15 minutes)

Don't want to run servers by hand? The whole stack — API, worker, UI, Postgres, ClickHouse, Redis,
MinIO — deploys to [Railway](https://railway.com) from the checked-in configs: four one-click
database templates plus three services pointed at this repo, each with a config-as-code file that
carries its Dockerfile, start command, health check and migrations. The step-by-step walkthrough is
[`deploy/railway/README.md`](deploy/railway/README.md) (copy-paste env included:
[`.env.railway.example`](deploy/railway/.env.railway.example)); the production-hardening runbook
(auth guards, backups, worker pool, post-deploy checks) is
[`guides/DEPLOY.md`](guides/DEPLOY.md).

---

## Send your first trace

```bash
pip install "tracely-ai[openai]"     # or [anthropic], [langchain], [all]
```

Initialize once at startup, then wrap a run — your normal provider calls are captured automatically,
with no span code:

```python
import tracely_sdk as tracely

tracely.init(
    endpoint="http://localhost:8000",   # your Tracely API
    api_key="tracely_dev_key",          # an ingest key
    service_name="support-agent",
    env="prod",                         # prod | staging | ci | dev — the gating axis
    instrument="auto",                  # auto-detect openai / anthropic / google / mistral / langchain
)

with tracely.trace(agent="support-agent", conversation="conv-1", user="u_42"):
    client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Where is order ORD-4471?"}],
    )
```

That produces a **GENERATION** span with model, messages, tokens, latency, tool calls and cost.
Need spans for your own logic? `@observe` and the manual `agent` / `tool` / `llm` / `retriever` /
`guardrail` context managers are all there.

Any OTLP/HTTP exporter works too — point it at `POST {endpoint}/v1/traces` with
`Authorization: Bearer tracely_dev_key`. Tracely reads standard `gen_ai.*` / OpenInference attributes
plus first-class hints: `tracely.agent.id` (auto-registered), `tracely.agent.version`,
`tracely.conversation.id` / `turn.*` / `step.*`, `tracely.observation.type`, and `tracely.env`
(`prod|staging|ci|dev` — the gating axis).

### Declare your agents and record your state

Two optional lines make a conversation self-describing. **The agent catalog** tells Tracely which
agents, tools, prompts and models the conversation *has* (not just which ones fired) — it fills the
**Conversation Agents** panel and is readable from judge prompts as `@LIST_AGENT`. **State deltas**
record what each step wrote to your shared state, folded into the **Conversation State** drawer and
the per-message **State Δ** column:

```python
AGENTS = [{
    "name": "support",
    "description": "front-line agent; routes billing questions",
    "system_prompt": "You are the support agent for Acme…",   # free-form keys kept verbatim
    "model": "gpt-5.2",
    "tools": {"lookup_order": {"name": "lookup_order", "description": "order by id",
                               "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}}}},
}]

with tracely.trace(agent="support", conversation="conv-1", agents=AGENTS):
    ...
    tracely.set_state({"cart": cart, "last_action": "add_to_cart"})   # inside any span/@observe
```

LangGraph users get state for free (node outputs are captured as deltas automatically), and
non-Python services can push the catalog with `POST /api/sessions/{conversation_id}/config`.

Full instrumentation guide → **[doc.tracely-studio.xyz](https://doc.tracely-studio.xyz)** · [`sdk/README.md`](sdk/README.md)

---

## Gate your PRs

A promoted production failure becomes a regression test that **blocks the PR** that reintroduces it.
All you need is your ingest key (it identifies your workspace) and your Tracely API URL. Three ways to
wire it, depending on how your CI can reach your agent.

<details open>
<summary><b>Option A — let Tracely call your agent</b> (no agent code in CI, any language)</summary>

Register your agent's HTTP endpoint once, author [scenarios](https://doc.tracely-studio.xyz/scenarios) —
multi-turn conversations, or an adversarial goal a red-team model improvises against — and Tracely
drives them itself. **Nothing to install, import or shim**, so a TypeScript or Go service gates exactly
like a Python one.

```yaml
      - uses: Jwuthri/Tracely/.github/actions/tracely-gate@master
        with:
          api:   https://tracely.your-co.dev
          key:   ${{ secrets.TRACELY_KEY }}
          # agent: planner,support-agent   ← a subset; omit it to gate EVERY agent with scenarios
```

Scenarios belong to an agent, so leaving `agent` blank gates each one in its own run and fails the job
if any of them fails — a new agent is covered the day someone writes its first scenario.

</details>

<details>
<summary><b>Option B — gate the traces your CI already emits</b></summary>

If your pipeline already runs your agent instrumented with `tracely.env=ci`, the gate matches those
traces to your promoted cases (by input) and returns PASS/FAIL.

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
          mode:  gate                          # grade the ci traces this workflow emitted
          agent: planner                       # which agent's promoted suite to run
          api:   https://tracely.your-co.dev   # your Tracely backend (TRACELY_API)
          key:   ${{ secrets.TRACELY_KEY }}    # your ingest key = your workspace
```

</details>

<details>
<summary><b>Option C — replay recorded cases against your code</b> (hermetic, $0)</summary>

Re-runs your agent on each promoted case's *recorded input*, serving the recorded tool/LLM outputs as
fixtures — deterministic, offline, **no API keys, no cost** — then gates. Guarantees the exact failing
inputs are tested.

```yaml
      - run: pip install tracely-ai
      - run: tracely replay planner --entrypoint my_pkg.agent:run    # a Python agent
        # …or any language:  tracely replay planner --cmd "node run.js"  (reads $TRACELY_INPUT)
        env:
          TRACELY_API: https://tracely.your-co.dev
          TRACELY_KEY: ${{ secrets.TRACELY_KEY }}
```

Hermetic replay requires your agent to route tool/model calls through the SDK's `call_tool` /
`call_llm` seam (see [the SDK guide](sdk/README.md)); add `--live` to make real calls instead.

</details>

Both commands auto-detect the PR/commit from the Actions context; `web-url` / `TRACELY_WEB_URL` is
optional and only builds the "view gate run" link in the PR comment.

> ℹ️ The repo's own [`.github/workflows/tracely-gate.yml`](.github/workflows/tracely-gate.yml) is
> Tracely **dogfooding itself** — it replays the bundled `weather_agent` example, which is why it uses
> an in-repo `pip install ./sdk`. **Your** integration is one of the three options above, not that file.

---

## Architecture

The write path deliberately mirrors Langfuse's proven design — reimplemented in Python, with agent
semantics promoted to **first-class indexed columns** (Langfuse keeps them as read-time strings):

```
SDK/OTLP → POST /v1/traces → S3 blob (durable FIRST) → Redis/Celery
  → worker: otel mapping → registry upsert → ClickHouse events
  → evaluate_run_task → scores + structural clustering
```

| Layer | Tech | Where |
|---|---|---|
| Backend (API + domain) | **FastAPI** + Pydantic v2 | [`backend/`](backend/README.md) |
| Workers | **Celery + Redis** | [`workers/`](workers/README.md) |
| Traces + scores (OLAP) | **ClickHouse** (`ReplacingMergeTree`) | `backend/tracely/infrastructure/clickhouse/ddl` |
| Registry (OLTP) | **Postgres + pgvector** + SQLAlchemy 2.0 + Alembic | `backend/migrations` |
| Queue / Blobs | **Redis** / **MinIO·S3** (blob-first, source of truth) | — |
| Frontend | **Next.js 15** (App Router) + Tailwind | [`frontend/`](frontend/README.md) |
| SDK + CI gate CLI | **`tracely-ai`** (OTel wrapper + `tracely` CLI) | [`sdk/`](sdk/README.md) |
| Tooling | **uv** workspace (Python) · **pnpm** (web) | — |

One deliberate adaptation: ClickHouse server-side `async_insert` instead of an in-process write buffer
(Celery tasks don't share memory). [Why](design/part2-tracely/01-steal-and-do-not-copy.md)

### Repo map — each folder has its own detailed README

| Folder | What's inside |
|---|---|
| [`backend/`](backend/README.md) | The `tracely` package: FastAPI API + shared domain (OTLP mapping, ClickHouse/Postgres/S3, registry, evaluators, failure intelligence, regression, gate, auth, Celery tasks). |
| [`workers/`](workers/README.md) | The deployable Celery worker runtime. |
| [`frontend/`](frontend/README.md) | The Next.js web app — trace explorer, clusters, cases, gates, trends, settings, auth. |
| [`sdk/`](sdk/README.md) | The Python SDK (instrument agents over OTLP, hermetic record-replay) + the `tracely` CI gate CLI. |
| [`docs/`](docs/README.md) | The published SDK docs site (Nextra). `make docs` → :3002. |
| [`scripts/`](scripts/README.md) | Dev/demo helpers (raw-OTLP sender, one-command `seed_demo.py`, gate shim). |
| [`design/`](design/README.md) | The full design dossier — reverse-engineered Langfuse + every Tracely design decision. |

---

## What's shipped

The core **trace → detect → cluster → regression → gate** loop is end-to-end:

- **Ingest** — any OTLP/HTTP source, first-class agent semantics, blob-first durability.
- **Evaluate** — DB-backed evaluators as table columns: CRUD from the UI, run on every ingest.
  Multi-output LLM-as-judge (score / number / boolean / text / JSON with custom schema) at
  conversation / run / span granularity, in **basic** (context auto-injected) or **advanced**
  (`@VARIABLE` template prompts with live preview + autocomplete) mode. Batch and sequential
  execution, per-evaluator targeting (agent/env) + deterministic sampling to scope judge spend;
  **advisory** evaluators record a verdict without flipping the roll-up.
- **Triage** — structural + semantic failure clustering, creatable suggested-evaluator drafts, promote-to-case.
- **Regression** — hermetic fixture bundles, fail-to-pass contracts, CI replay.
- **Gate** — PR blocking via `tracely simulate` / `replay` / `gate`, GitHub status + comment.
- **Insights** — daily traces/failures/gate pass-rate **Trends** + per-agent cross-metric **meta-analysis**.
- **Conversation intelligence** — real-time **rolling summary** (per-turn memory backing the judge's
  `@HISTORY`) + a **conversation-agents** panel.
- **Judge calibration** — label judge verdicts against human review, get per-evaluator agreement, and
  catch an over-flagging judge before you let it gate a release.
- **Auth** — three modes: `dev` (open), `local` (email/password + invites, self-host), `clerk` (hosted).
  Team management, API keys, invitations, account settings.

Near-term plan: [design/part2-tracely/11-prd-next-steps.md](design/part2-tracely/11-prd-next-steps.md) ·
Long-term roadmap: [10-mvp-and-roadmap.md](design/part2-tracely/10-mvp-and-roadmap.md)

## Key environment variables

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_MODE` | `dev` | `dev` (open, no login) · `local` (email/password, self-host) · `clerk` (hosted SaaS). |
| `SESSION_SECRET` | — | Required when `AUTH_MODE=local`: HS256 signing key for JWTs (≥32 chars). |
| `CLERK_ISSUER` | — | Required when `AUTH_MODE=clerk`. |
| `OPENROUTER_API_KEY` | — | Enables LLM-as-judge evaluators (any model). Skipped gracefully if absent. |
| `OPENAI_API_KEY` | — | Alternative LLM backend for judges + failure-intelligence embeddings. |
| `TRACELY_BACKEND_PORT` | `8000` | Backend host port (Docker compose override). |
| `TRACELY_WEB_PORT` | `3001` | Frontend host port (Docker compose override). |

With no LLM key at all the pipeline still runs — judges, failure intelligence and meta-analysis
degrade rather than crash.

---

## Contributing

Issues and PRs welcome. Before pushing:

```bash
uv run pytest -q backend/tests sdk/tests    # what CI runs
uv run ruff check . && uv run ruff format .
cd frontend && pnpm test && pnpm build      # vitest + tsc typecheck + lint
```

## License

[MIT](LICENSE) © Julien Wuthrich

<div align="center">

**[tracely-studio.xyz](https://tracely-studio.xyz)** · [Docs](https://doc.tracely-studio.xyz) · [Star on GitHub](https://github.com/Jwuthri/Tracely)

If Tracely is useful to you, a ⭐ helps other people find it.

</div>
