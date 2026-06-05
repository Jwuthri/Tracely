# `backend/` — the `tracely` package (API + shared domain)

The Python heart of Tracely. One installable package, `tracely`, that is **both**:

1. the **FastAPI app** — OTLP ingest (`/v1/traces`) + the read/write API the frontend and CLI call, and
2. the **shared domain** every process imports — OTLP→event mapping, ClickHouse/Postgres/S3 access, the registry, evaluators, failure intelligence, regression, and the gate. The Celery [`workers/`](../workers/) runtime imports this same package and runs its `tasks.py`.

> Trace-native CI/CD for AI agents: **production trace → failure detection → regression test → CI/CD gate**. The trace is the source of truth; everything else is derived from it. The "why" behind every design choice lives in the [design dossier](../design/README.md) — this README is the implementation guide.

---

## The five stores

Tracely deliberately mirrors Langfuse's proven write path, reimplemented in Python ([why](../design/part2-tracely/01-steal-and-do-not-copy.md)):

| Store | Tech | Holds |
|---|---|---|
| **OLAP** | ClickHouse | `events` (one row per span) + `scores` — the trace + eval substrate. `ReplacingMergeTree` for upsert/dedup. |
| **OLTP / registry** | Postgres + pgvector | Projects, ingest keys, Agents, AgentVersions, EvaluationSuites/Cases, GateRuns, FailureClusters, Evaluators, failure embeddings. SQLAlchemy 2.0, Alembic migrations. |
| **Blobs** | S3 / MinIO | The raw OTLP request body (durable **source of truth**, written *before* anything is queued) + regression fixture bundles. |
| **Queue** | Redis | Celery broker/result backend. |
| **Vectors** | pgvector | Failure embeddings for clustering. |

---

## The flows (trace the code)

### 1. Ingest — OTLP → blob → queue → ClickHouse
```
POST /v1/traces                         api/routers/otlp.py
  → ingestion.ingest_otlp()             blobstore.put_blob(raw)   ← durable FIRST
                                         tasks.ingest_otlp_blob.delay(...)  ← then enqueue
  ─ (worker) ─
  → tasks.ingest_otlp_blob()            blobstore.get_blob()
                                         otel/mapping.parse_otlp_traces() → event dicts
                                         registry.upsert_agent()/upsert_agent_version()  ← slug → UUID
                                         clickhouse.insert_rows("events", …)
                                         evaluate_run_task.apply_async(…, countdown=4)   ← debounce late spans
```
**Why blob-first:** nothing is queued unless the raw body is durably stored, so a worker crash never loses data. **Why `async_insert`:** Celery tasks are separate processes with no shared in-memory buffer (Langfuse batches in-process), so we let ClickHouse batch server-side.

### 2. Online evaluation — auto-score every trace
`tasks.evaluate_run_task` → `eval_runner.evaluate_run()` loads the project's **enabled `Evaluator` records** (or the recommended built-in `TEMPLATES` as a fallback), runs each via `evaluators.run_evaluator()`, and writes `scores` rows. Score ids are a deterministic `uuid5(trace_id:name:span_id)` so re-evaluating a trace (spans arrive across batches) **replaces** rather than duplicates.

The built-in checks (`evaluators.py`):

| Evaluator | `score_name` | level | FAILs when |
|---|---|---|---|
| Run outcome | `tracely.run.outcome` | AGENT_RUN | any span has `level=ERROR` |
| Tool success | `tracely.tool.success` | TOOL | a TOOL span errored (`observation_id` = span) |
| Tool consistency | `tracely.run.tool_consistency` | AGENT_RUN | the model requested a tool that never executed (silent failure) |
| Latency | `tracely.run.latency_ms` | AGENT_RUN | run duration > budget |
| Answer quality (LLM judge) | `tracely.run.quality` | AGENT_RUN | judge score < threshold (needs `OPENAI_API_KEY`; skipped if absent) |
| Required tools | `tracely.run.required_tools` | AGENT_RUN | a configured required tool is missing (off by default) |

The judge grades the agent's **real answer** for faithfulness to the actual tool results — it catches hallucinations, not just crashes.

> ⚠️ Evaluators are mid-refactor to fully DB-backed records (`Evaluator` model + migration `0007`). Today `eval_runner` falls back to the built-in `TEMPLATES` when the table is empty/unapplied (logs a benign `evaluator_load_failed`). See the [next-steps PRD](../design/part2-tracely/11-prd-next-steps.md).

### 3. Failure intelligence — group failures into Issues
Two stages:
- **Ingest-time (cheap, structural):** `cluster.cluster_failure()` builds a masked signature (`failed_evals ## masked_error_text`, ids/numbers/quotes redacted) → sha256 key → upserts a `FailureCluster` + member. Runs automatically when a trace has failures.
- **On-demand (semantic):** "Analyze failures" → `fi.rebuild_clusters()` embeds a mechanism-focused signature of each failing run (`fi.embedding_text`), clusters with HDBSCAN (UMAP first only at large n), then a LangChain/LangGraph agent (`agents.analyze_cluster`) writes a semantic Issue per cluster and a meta-agent (`agents.consolidate`) merges/splits them. Promotion/ignore state is carried over from the old clusters. LLM steps are lazy-imported and skipped without `OPENAI_API_KEY`.

### 4. Regression — freeze a failing trace into a test
`regression.promote_trace()` turns a trace into an `EvaluationCase`: it captures the input (+ `input_digest` sha256 for dedup), records a **v2 fixture bundle** (ordered tool/LLM calls each with `args`, `tool_call_id`, output **and error status**) to S3 for hermetic replay, snapshots the `reference_trajectory`, and writes a **fail-to-pass** contract (`no_error`, `required_tools`, `match_mode`, `allow_tool_errors`). It then validates the contract by re-running `evaluate_case()` against the source trajectory — the source must initially **fail** the case. `allow_tool_errors` is auto-set when the source had a tool error *and* a run error, so a graceful error-handling fix passes while a crashing agent fails.

### 5. Gate — block the PR
`gate.run_gate()` replays an agent's **PROMOTED** cases against the PR's candidate `env=ci` traces (paired explicitly by `tracely replay`, or auto-matched by `input_digest`), runs `evaluate_case()` per pair, and returns PASS/FAIL. It also rolls up candidate latency + token usage, compares to the last green gate (`_baseline_gate`), and emits **non-blocking warnings** on regressions (default 25%). **Fail-to-pass is the only hard gate** unless `gate_block_on_warnings`.

---

## Module map (`backend/tracely/`)

| File | Purpose |
|---|---|
| `config.py` | `Settings` (pydantic-settings) — all env: ClickHouse/Postgres/Redis/S3, OpenAI keys, embedding/judge models, gate thresholds. |
| `db.py` | SQLAlchemy 2.0 async engine (API) + sync engine (workers/migrations); `AsyncSessionLocal` / `SyncSessionLocal`. |
| `models.py` | Postgres registry entities + enums (`Project, IngestKey, Agent, AgentVersion, EvaluationSuite/Case, GateRun/Case, FailureCluster/Member, FailureEmbedding, Evaluator, CaseReplay`). |
| `clickhouse.py` | sync + async CH clients; `insert_rows()` (server-side `async_insert`). |
| `blobstore.py` | S3/MinIO (boto3); `put_blob`/`get_blob`/`event_blob_key` — blob-first durability. |
| `events.py` | `EVENT_COLUMNS` — the canonical ClickHouse `events` row schema; `to_rows()` fills defaults/timestamps. |
| `otel/mapping.py` | OTLP `ExportTraceServiceRequest` → event dicts. Type classification (`tracely.observation.type` > OpenInference > `gen_ai.operation.name` > heuristics); `_KNOWN_TYPES` incl. `THINKING`. |
| `registry.py` | idempotent `upsert_agent` / `upsert_agent_version` (slug/`config_hash` → UUID). |
| `ingestion/` | blob-first enqueue (`process_batch.ingest_otlp`). |
| `celery_app.py` / `tasks.py` | Celery app + the three tasks: `ingest_otlp_blob`, `evaluate_run`, `rebuild_clusters`. |
| `eval_runner.py` | run the project's evaluators on a trace, persist `scores`, trigger structural clustering. |
| `evaluators.py` | the structural checks + LLM judge + `run_evaluator()` dispatch + recommended `TEMPLATES`. |
| `trajectory.py` | `Trajectory`/`TrajectoryStep` snapshot + assertion helpers (`tool_sequence`, `erroring_steps`, `split_errors`, `tools_satisfied`). |
| `regression.py` | `promote_trace`, `evaluate_case`, fixture capture (v2), `read_trace_spans`. |
| `cluster.py` | ingest-time structural failure clustering (cheap signature). |
| `fi.py` | semantic failure intelligence — embed → HDBSCAN → analyze → consolidate. |
| `agents.py` | LangGraph/LangChain agents (`analyze_cluster`, `consolidate`) — lazy-imported. |
| `gate.py` | `run_gate`, suite replay, candidate metrics, baseline compare, soft warnings. |
| `schemas.py` | Pydantic API models (`SpanOut`, `TraceDetail`, …). |
| `seed.py` / `ch_migrate.py` | bootstrap the default project + ingest key; apply ClickHouse DDL. |
| `api/` | FastAPI `main.py`, `auth.py` (Bearer → `project_id`), and the routers below. |

## API surface (`backend/tracely/api/routers/`)

| Method · Path | Router | Does |
|---|---|---|
| `POST /v1/traces` | `otlp.py` | OTLP/HTTP ingest (protobuf or JSON) → blob + enqueue. |
| `GET /api/traces`, `/api/traces/{id}` | `reads.py` | trace list; trace detail (spans + scores + verdict). |
| `GET /api/sessions`, `/api/sessions/{thread}` | `reads.py` | conversations (grouped by `conversation_id`) + per-turn rollups (tokens, input/output split, model, cost, verdict). |
| `GET /api/search` | `reads.py` | ⌘K search over conversations/issues/cases/gates. |
| `GET /api/stats` · `POST /api/promote` · `GET /api/cases` · `GET /api/cases/{id}` · `POST /api/cases/{id}/replay` | `cases.py` | dashboard stats; promote a trace → case; case list/detail; manual replay. |
| `GET /api/clusters`, `/api/clusters/{id}` · `POST …/rebuild` | `clusters.py` | failure clusters list/detail; trigger `rebuild_clusters`. |
| `POST /api/gate` · `GET /api/gate/suite` · `GET /api/gates`, `/api/gates/{id}` | `gate.py` | run a gate; fetch the replay suite (cases + inputs + fixtures); gate list/detail. |
| `GET /api/trends` | `analytics.py` | daily traces/failures + gate pass-rate + summary (failure rate, MTTR proxy…). |
| `GET /api/health` | `health.py` | liveness. |

Every read/write is scoped by `project_id`, resolved from the `Authorization: Bearer <ingest-key>` header (`auth.get_project_id`).

## Data schemas

- **ClickHouse** (`tracely/ch_migrations/*.up.sql`): `0001_events` — the wide span table (identifiers, timing, agent semantics as **first-class indexed columns** `agent_id/agent_run_id/turn_id/step_id/env`, tool edges, `usage_details`/`cost_details` Maps, `input`/`output`, full `metadata` Map), `ReplacingMergeTree(event_ts, is_deleted)`. `0002_scores` — the `scores` sink (`name, verdict, value, evaluation_level, observation_id, source, …`).
- **Postgres** (`migrations/versions/*`, Alembic): `0001` registry (projects/keys/agents/versions) · `0002` suites/cases/replays · `0003` gate runs/cases · `0004` failure clusters/members/embeddings · `0005` FI extensions · `0006` gate metric columns (latency/tokens/warnings) · `0007` `evaluators` (user-defined: kind, config, score_name, level, enabled, target_agent/env, sampling) — **not yet applied** in deployed DBs.

## Run it

From the repo root (see the [root README](../README.md) for the full quickstart). Local dev (hot reload):
```bash
make infra-up         # clickhouse, postgres, redis, minio
make migrate          # ClickHouse DDL + Alembic (Postgres)
make seed             # default project + ingest key (tracely_dev_key)
make backend          # FastAPI on :8000 (OpenAPI at /docs)
make workers          # Celery worker (the async half of the write path)
make send-trace       # post a sample OTLP trace
make test             # OTLP-mapper unit tests (no infra needed)
```
In Docker, the `backend` and `worker` services run this package off a **source volume-mount** (editable install), so a Python edit needs only `docker compose restart backend worker` — **the Celery worker does not hot-reload**, so always restart it after changing worker/eval/FI/mapping code. New Alembic migrations apply via the mounted `migrate` one-shot.

## Tests
`backend/tests/` — `test_otel_mapping.py` exercises the OTLP→event mapper (type classification, attribute/usage extraction, column alignment) with no infra. Run with `make test`.

## Key decisions (and why)

1. **One package, three roles (API · domain · tasks).** The API, the Celery worker, and the CLI all import the same `tracely` domain — no duplicated mapping/DB logic, no drift. (`workers/` is a thin runtime shim.)
2. **Blob-first ingestion.** Durable S3 write *before* enqueue → zero-loss; the queue only ever points at data that already exists.
3. **Server-side batching, not in-process.** `async_insert` instead of Langfuse's in-process writer buffer — correct for a multi-process Celery deployment.
4. **Agent semantics are columns, not metadata.** `agent_id/agent_run_id/conversation_id/turn_id/step_id/env` are indexed ClickHouse columns, so agent-level queries/gating are first-class (Langfuse reconstructs these from strings at read time). [Why](../design/part2-tracely/03-agent-and-trace-data-model.md)
5. **Idempotent writes everywhere.** Deterministic ids + `ReplacingMergeTree` mean re-ingesting a trace or re-evaluating it converges instead of duplicating.
6. **The recorded run is the test.** A regression case = a real trace + its fixture bundle + reference trajectory + fail-to-pass contract — no hand-authored datasets. [Why](../design/part2-tracely/05-regression-testing.md)
7. **Hermetic replay by default.** Fixtures record each tool/LLM call's args, output, and error, replayed FIFO so CI is deterministic, offline, and free. `--live` opts out.
8. **Fail-to-pass is the only hard gate.** Cost/latency/token deltas are advisory warnings — they inform without blocking, avoiding flaky gates. [Why](../design/part2-tracely/08-cicd-architecture.md)
9. **Graceful degradation.** No `OPENAI_API_KEY` → the LLM judge and failure-intelligence agents are skipped (lazy imports), and the rest of the pipeline runs unchanged.
