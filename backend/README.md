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
                                         tasks._apply_default_agent()          ← agent-less spans → trace's agent, else `default`
                                         registry.upsert_agent()/upsert_agent_version()  ← slug → UUID
                                         clickhouse.insert_rows("events", …)
                                         evaluate_run_task.apply_async(…, countdown=4)   ← debounce late spans
```
**Why blob-first:** nothing is queued unless the raw body is durably stored, so a worker crash never loses data. **Why `async_insert`:** Celery tasks are separate processes with no shared in-memory buffer (Langfuse batches in-process), so we let ClickHouse batch server-side.

### 2. Online evaluation — auto-score every trace
`tasks.evaluate_run_task` → `eval_runner.evaluate_run()` loads the project's **enabled `Evaluator` records**, runs each via `evaluators.run_evaluator()`, and writes `scores` rows. Evaluators are **opt-in**: `seed.py` installs the recommended catalog (`TEMPLATES`) as editable rows so online eval works out of the box, but a project with no enabled evaluators simply produces no scores (no built-in fallback). Score ids are a deterministic `uuid5(trace_id:name:span_id)` so re-evaluating a trace (spans arrive across batches) **replaces** rather than duplicates.

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

> Evaluators are **fully DB-backed** (`Evaluator` model + migration `0007`) and editable per project (`enabled`, `target_agent`/`target_env`, `sampling`, `config`). `seed.py` seeds the recommended catalog as editable rows (idempotent by `score_name`), so disabling or editing a row sticks across re-seeds. The built-in checks in `evaluators.py` are the implementations these records dispatch to.

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

The package is layered: **domain** (pure logic, no I/O), **infrastructure** (DB / CH / S3 / Redis / LLM adapters), **services** (use-case orchestrators, classes), **workers** (Celery tasks), **api** (HTTP). Old flat paths (`tracely.regression`, `tracely.gate`, `tracely.fi`, `tracely.evaluators`, `tracely.db`, …) are kept as thin re-export shims so external callers (alembic, workers, scripts, SDK tests) keep working unchanged.

### `tracely/config.py`
`Settings` (pydantic-settings) — all env: ClickHouse/Postgres/Redis/S3, OpenAI keys, embedding/judge models, gate thresholds, `default_agent_slug`.

### `tracely/domain/` — pure logic, no I/O
| Module | Purpose |
|---|---|
| `trajectory.py` | `Trajectory` / `TrajectoryStep` + assertion helpers (`tool_sequence`, `erroring_steps`, `split_errors`, `tools_satisfied`). |
| `traces/spans.py` | `root_span`, `input_digest`, `failure_facts` — canonical span helpers used by every service. |
| `traces/metadata.py` | Parse the ClickHouse-aggregated `tracely.metadata.*` JSON. |
| `evaluation/results.py` | `EvalResult`, `RunContext` dataclasses. |
| `evaluation/text.py` | Answer / I/O text extraction shared between structural + judge. |
| `evaluation/evaluators/` | `Evaluator` ABC + `EvaluatorRegistry` + one class per check (`RunOutcomeEvaluator`, `ToolSuccessEvaluator`, `ToolConsistencyEvaluator`, `LatencyEvaluator`, `RequiredToolsEvaluator`, `LLMJudgeEvaluator`) + `TEMPLATES` catalog. |
| `evaluation/evaluator_suggestion.py` | Generate a starting-point evaluator from a cluster's mechanism. |
| `failure/signature.py` | `FailureSignature` value object — the cheap masked sha256 key. |
| `failure/text.py` | `embedding_text` / `summarize_failure` — terse mechanism vs. full-context summaries. |
| `failure/clustering.py` | `ClusterEngine` — UMAP+HDBSCAN regime selection. |
| `failure/histogram.py` | Occurrence-over-time bucketing. |
| `regression/contract.py` | `evaluate_assertions(case, traj)` — pure fail-to-pass evaluation. |
| `regression/fixtures.py` | `FixtureBundle` value object — capture/encode/decode the v2 hermetic-replay bundle. |
| `gate/warnings.py` | `delta_warnings(latency, tokens, baseline)` — pure % regression check. |

### `tracely/infrastructure/` — I/O adapters
| Module | Purpose |
|---|---|
| `db/base.py` | SQLAlchemy 2.0 `Base = DeclarativeBase`. |
| `db/engine.py` | Async + sync engines + sessionmakers. |
| `db/session.py` | `get_session()` / `sync_session()` helpers. |
| `db/models.py` | Postgres registry entities + enums (Project, IngestKey, Agent, AgentVersion, EvaluationSuite/Case, GateRun/Case, FailureCluster/Member, FailureEmbedding, Evaluator, CaseReplay). |
| `clickhouse/client.py` | sync + async clients; `insert_rows()`. |
| `clickhouse/events_schema.py` | `EVENT_COLUMNS` + `to_rows()`. |
| `clickhouse/trace_reader.py` | `TraceReader` — one class owns every `events`/`scores` SELECT (`read_spans`, `candidate_metrics`, `latest_traces_for_env`, `failing_trace_reasons`, `member_meta`). |
| `clickhouse/score_writer.py` | `ScoreWriter` — `write_eval_scores` + `write_regression_verdict`. |
| `clickhouse/migrations.py` + `ddl/` | Tiny migration runner + the `*.up.sql` files. |
| `blob/s3.py` | S3/MinIO `put_blob` / `get_blob` / `event_blob_key`. |
| `queue/celery_app.py` | The shared Celery app. |
| `llm/embeddings.py` | `Embedder` (OpenAI embeddings, lazy-imported). |
| `llm/judge.py` | `judge(rubric, ...)` — LLM judge HTTP call. |
| `llm/analysis_agents.py` | LangGraph/LangChain agents (`analyze_cluster`, `consolidate`) — lazy-imported. |
| `registry/agents.py` | Idempotent `upsert_agent` / `upsert_agent_version`. |
| `text.py` | `extract_text` / `message_text` — readable text from stored I/O. |

### `tracely/services/` — use-case orchestrators (classes)
| Class | Owns |
|---|---|
| `IngestionService` | `process_blob` — blob → events → registry resolve → CH insert. Plus the producer `ingest_otlp()` module function. |
| `EvaluationService` | `evaluate_trace` — load project's evaluators, dispatch via `EvaluatorRegistry`, persist scores, trigger structural clustering. |
| `RegressionService` | `promote_trace`, `replay_case`. |
| `GateService` | `run_gate`, `replay_suite`, `resolve_agent_id`. |
| `FailureIntelService` | `rebuild_clusters` — embed → cluster → analyze → consolidate. |
| `StructuralClusteringService` | `cluster_failure` — ingest-time signature clustering. |
| `seeding_service` | `main()` — default project + ingest key + recommended evaluators. |

### `tracely/workers/tasks.py`
Three Celery tasks, each a 3-line dispatch into a service class: `ingest_otlp_blob` → `IngestionService`, `evaluate_run` → `EvaluationService`, `rebuild_clusters` → `FailureIntelService`.

### `tracely/otel/` — OTLP → event mapper (split from the old 1035-line `mapping.py`)
| Module | Purpose |
|---|---|
| `attributes.py` | OTLP `AnyValue` decoding + tiny scalar helpers. |
| `types.py` | Observation-type constants + `map_observation_type` (`tracely.observation.type` > OpenInference > `gen_ai.operation.name` > heuristics; includes `THINKING`). |
| `messages.py` | Reassemble the three on-the-wire message shapes (structured / OpenInference flattened / OpenLLMetry legacy) into Tracely's `{role, content:[blocks]}`. |
| `io_field.py` | Resolve a span's `input`/`output` column from the attrs. |
| `usage.py` | Token usage + model parameters + TTFT. |
| `convention.py` | Detect which message convention the span used (drift tracking). |
| `tool_enrichment.py` | Reconstruct TOOL span input/output for instrumentors that don't capture them. |
| `span_mapper.py` | `_map_span` — the central span → event row rule. |
| `parser.py` | `events_from_request`, `parse_otlp_traces`, `parse_otlp_traces_json`. |
| `mapping.py` | Back-compat shim re-exporting the public + commonly-imported private names. |

### `tracely/api/` — FastAPI
| Module | Purpose |
|---|---|
| `main.py` | App factory + middleware + router mount. |
| `auth.py` | `Authorization: Bearer <ingest-key>` → `project_id`. |
| `dto/{common,traces}.py` | Pydantic response models (`SpanOut`, `TraceDetail`, `AgentOut`, `IngestResponse`). |
| `routers/{traces,sessions,search,cases,gate,clusters,analytics,otlp,health}.py` | Thin request/response — business logic in services/domain. |

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
- **Postgres** (`migrations/versions/*`, Alembic): `0001` registry (projects/keys/agents/versions) · `0002` suites/cases/replays · `0003` gate runs/cases · `0004` failure clusters/members/embeddings · `0005` FI extensions · `0006` gate metric columns (latency/tokens/warnings) · `0007` `evaluators` (user-defined: kind, config, score_name, level, enabled, target_agent/env, sampling) — applied + seeded with the recommended catalog by `seed.py`.

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
