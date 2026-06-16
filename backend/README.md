# `backend/` — the `tracely` package (API + shared domain)

The Python heart of Tracely. One installable package, `tracely`, that is **both**:

1. the **FastAPI app** — OTLP ingest (`/v1/traces`) + the read/write API the frontend and CLI call, and
2. the **shared domain** every process imports — OTLP→event mapping, ClickHouse/Postgres/S3 access, the registry, evaluators, failure intelligence, regression, auth, and the gate. The Celery [`workers/`](../workers/) runtime imports this same package and runs its `tasks.py`.

> Trace-native CI/CD for AI agents: **production trace → failure detection → regression test → CI/CD gate**. The trace is the source of truth; everything else is derived from it. The "why" behind every design choice lives in the [design dossier](../design/README.md) — this README is the implementation guide.

---

## The five stores

Tracely deliberately mirrors Langfuse's proven write path, reimplemented in Python ([why](../design/part2-tracely/01-steal-and-do-not-copy.md)):

| Store | Tech | Holds |
|---|---|---|
| **OLAP** | ClickHouse | `events` (one row per span) + `scores` — the trace + eval substrate. `ReplacingMergeTree` for upsert/dedup. |
| **OLTP / registry** | Postgres + pgvector | Projects, ingest keys, Agents, AgentVersions, EvaluationSuites/Cases, GateRuns, FailureClusters, Evaluators, Users, Memberships, Invitations, failure embeddings. SQLAlchemy 2.0, Alembic migrations. |
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
`tasks.evaluate_run_task` → `EvaluationService.evaluate_trace()` loads the project's **enabled `Evaluator` records**, runs each via `EvaluatorRegistry`, and writes `scores` rows. Evaluators are **opt-in**: `seed.py` installs the recommended catalog (`TEMPLATES`) as editable rows so online eval works out of the box. Score ids are a deterministic `uuid5(trace_id:name:span_id)` so re-evaluating a trace **replaces** rather than duplicates.

Evaluators are **DB-backed, editable per project, and rendered as TurnWise-style table columns** — add/remove/configure from the UI; each column is one evaluator. The built-in structural checks:

| Evaluator | `score_name` | level | FAILs when |
|---|---|---|---|
| Run outcome | `tracely.run.outcome` | AGENT_RUN | any span has `level=ERROR` |
| Tool success | `tracely.tool.success` | TOOL | a TOOL span errored (`observation_id` = span) |
| Tool consistency | `tracely.run.tool_consistency` | AGENT_RUN | the model requested a tool that never executed (silent failure) |
| Latency | `tracely.run.latency_ms` | AGENT_RUN | run duration > budget |
| Required tools | `tracely.run.required_tools` | AGENT_RUN | a configured required tool is missing (off by default) |

**LLM-as-judge (`kind: llm_judge`):** routes every call through LangChain `create_agent` on OpenRouter (`OPENROUTER_API_KEY`; falls back to OpenAI if `OPENAI_API_KEY` is set; skipped gracefully if neither is configured). Three granularity levels:

- **CONVERSATION** — one grade for the whole multi-turn thread (transcript).
- **AGENT_RUN** — one grade per trace (user request vs final answer + tool grounding).
- **SPAN/TOOL/GENERATION** — one grade per step (step I/O in context).

Output types: `score` (0..1 + PASS/FAIL via threshold), `number` (any range), `boolean` (PASS/FAIL), `text` (free-form string), `json` (user-defined schema compiled to a Pydantic model — exactly the fields the user defines, nothing appended; a numeric `score` field drives the value/PASS/FAIL and a `reason` field the explanation).

Execution modes: `batch` (independent, default) or `sequential` (each item's prompt carries the previous item's result — enabling progressive grading within a trace and chained context across conversation turns).

**Basic vs Advanced prompts.** A *basic* judge gets its context **auto-injected** (request / answer / tool results / transcript / step I/O). An *advanced* judge hands that control to the user: the rubric is written with `@VARIABLE` placeholders (`@REQUEST`, `@ANSWER`, `@TOOLS`, `@HISTORY`, `@LIST_AGENT`, `@STEP_INPUT`, …) resolved against the real trace/thread at run time (`domain/evaluation/template_resolver.py`). A missing variable becomes the literal `[No <REF> available]` — a soft miss, never an error. The same builder + resolver power both the run path and the `POST /api/evaluators/resolve` preview, so "what you preview" matches "what runs".

**Targeting + sampling (the AUTO run).** `domain/evaluation/targeting.py` decides which enabled evaluators run on a given trace: `target_agent` / `target_env` filter by the trace's agent (id or slug) / env, and `sampling` (0..1) rolls a **deterministic** per-`(trace_id, score_name)` die so a trace re-ingested across span batches makes the same keep/drop decision (scores converge under `ReplacingMergeTree` instead of flickering). This is the only lever for LLM-judge spend ("grade 10% of prod traces"). An explicit on-demand run from the UI always grades, ignoring targeting/sampling.

**Advisory verdicts.** `domain/evaluation/verdict.py` is the single roll-up policy: a trace / turn / session / trend counts as **failing** iff it has a `FAIL` on a *non-advisory* evaluator. An *advisory* evaluator (`config.advisory`, e.g. the subjective answer-quality judge) still records its verdict and shows its pill, but a FAIL on it does NOT flip the roll-up. This replaced the old hardcoded `name != 'tracely.run.quality'` magic string; `api/advisory.py` bridges the advisory set onto the async read paths, and the ClickHouse readers apply the identical `name NOT IN {advisory}` rule in SQL — so the threads dot, trace badge, session verdict, and trends agree (migration `0012` backfills the flag on existing installs).

### 3. Failure intelligence — group failures into Issues
Two stages:
- **Ingest-time (cheap, structural):** `cluster.cluster_failure()` builds a masked signature (`failed_evals ## masked_error_text`, ids/numbers/quotes redacted) → sha256 key → upserts a `FailureCluster` + member. Runs automatically when a trace has failures.
- **On-demand (semantic):** "Analyze failures" → `fi.rebuild_clusters()` embeds a mechanism-focused signature of each failing run (`fi.embedding_text`), clusters with HDBSCAN (UMAP first only at large n), then a LangChain/LangGraph agent (`agents.analyze_cluster`) writes a semantic Issue per cluster and a meta-agent (`agents.consolidate`) merges/splits them. Promotion/ignore state is carried over from the old clusters. LLM steps are lazy-imported and skipped without an LLM key.

### 4. Regression — freeze a failing trace into a test
`regression.promote_trace()` turns a trace into an `EvaluationCase`: it captures the input (+ `input_digest` sha256 for dedup), records a **v2 fixture bundle** (ordered tool/LLM calls each with `args`, `tool_call_id`, output **and error status**) to S3 for hermetic replay, snapshots the `reference_trajectory`, and writes a **fail-to-pass** contract (`no_error`, `required_tools`, `match_mode`, `allow_tool_errors`). It then validates the contract by re-running `evaluate_case()` against the source trajectory — the source must initially **fail** the case. `allow_tool_errors` is auto-set when the source had a tool error *and* a run error, so a graceful error-handling fix passes while a crashing agent fails.

### 5. Gate — block the PR
`gate.run_gate()` replays an agent's **PROMOTED** cases against the PR's candidate `env=ci` traces (paired explicitly by `tracely replay`, or auto-matched by `input_digest`), runs `evaluate_case()` per pair, and returns PASS/FAIL. It also rolls up candidate latency + token usage, compares to the last green gate (`_baseline_gate`), and emits **non-blocking warnings** on regressions (default 25%). **Fail-to-pass is the only hard gate** unless `gate_block_on_warnings`.

### 6. Auth — multi-mode authentication
Three modes controlled by `AUTH_MODE` in config:

- **`dev`** (default) — open access, no login required. Every request is treated as the default project.
- **`local`** — email/password self-hosting. JWT sessions signed with `SESSION_SECRET`. Full user registration, invite flow, team management, and API key management.
- **`clerk`** — Clerk-hosted SaaS auth. Verifies Clerk JWTs; requires `CLERK_ISSUER`.

All modes share `GET /auth/me`, `POST /auth/logout`, and `POST /auth/projects` (the project switcher). Local mode adds `/auth/register`, `/auth/login`, `/auth/change-password`, and the invitation endpoints (`POST/GET /auth/invitations`, `DELETE /auth/invitations/{id}`, `POST /auth/invitations/accept`); Clerk mode adds `POST /auth/sync`. Users, memberships, and invitations are stored in Postgres (migration `0008_auth`).

### 7. Rolling summary — accumulating conversation memory
`RollingSummaryService.build_for_thread()` keeps a per-span, accumulating summary of a conversation (table `rolling_summaries`, migration `0010`). It's a flat JSON **list** of items: a step ≤ `rolling_summary_step_max_tokens` (512) is appended **verbatim** (no LLM, no information loss); a larger step is compressed to ~10–20 words by `rolling_summary_agent`. When the list exceeds `rolling_summary_max_tokens` (20k), the older items fold into one `prev_summary` item and only the last two stay verbatim. One row per span holds the full list up to that point (conversation view = last row, message view = the turn's last step, step view = that exact row). Idempotent + incremental (an up-front read seeds a skip-cache), so the ingest hook re-runs cheaply; `format_summary_as_history` renders the list into the judge's `@HISTORY` string. The `evaluate_run_task` folds each turn in at ingest (best-effort — a summary failure never fails the run); `POST /api/sessions/{thread}/rolling-summary/generate` rebuilds on demand.

### 8. Meta-analysis — cross-metric "Analyze"
`MetaAnalysisService.analyze_and_save()` runs a cross-metric analysis over **one agent's** evaluator score rows (table `meta_analyses`, migration `0009`). The async ClickHouse gather (`async_reader.agent_score_rows`) happens in the router; the service computes **deterministic** statistics in `domain/analysis/statistics.py` — Spearman correlations (tie-averaged ranks, no scipy dependency; reports the shared-sample `n`, not a fabricated p-value) and z-score outliers — then `infrastructure/llm/meta_analysis_agent.py` synthesizes patterns / recommendations / a summary **on top**, and the precomputed numbers are **merged back in** so the model can never lose or hallucinate them. With no LLM credential the run still succeeds (stats + a templated summary). Surfaced on the Trends page.

### 9. Conversation agents — declared vs derived
`ConversationAgentsService.for_thread()` reads the user-declared agent/tool catalog a conversation sent via the SDK (`tracely.trace(agents=[...])` → table `conversation_agents`, migration `0011`). A tiny guarded sync seam: it never raises, so a lookup failure degrades to the spans-derived agent view. The catalog feeds both the UI's Conversation Agents panel and the judge's `@LIST_AGENT` variable.

---

## Module map (`backend/tracely/`)

The package is layered: **domain** (pure logic, no I/O), **infrastructure** (DB / CH / S3 / Redis / LLM adapters), **services** (use-case orchestrators, classes), **workers** (Celery tasks), **api** (HTTP). The only top-level Python files are `config.py` (pydantic settings) and `__init__.py` (re-exports `settings`).

### `tracely/config.py`
`Settings` (pydantic-settings) — all env: ClickHouse/Postgres/Redis/S3, `OPENROUTER_API_KEY` / `OPENAI_API_KEY`, embedding/judge models, `meta_analysis_model`, `rolling_summary_model` + its `*_step_max_tokens` (512) / `*_max_tokens` (20k) budgets, gate thresholds, `AUTH_MODE` (`dev|local|clerk`), `SESSION_SECRET`, `CLERK_ISSUER`, `default_agent_slug`.

### `tracely/domain/` — pure logic, no I/O
| Module | Purpose |
|---|---|
| `trajectory.py` | `Trajectory` / `TrajectoryStep` + assertion helpers (`tool_sequence`, `erroring_steps`, `split_errors`, `tools_satisfied`). |
| `traces/spans.py` | `root_span`, `input_digest`, `failure_facts` — canonical span helpers used by every service. |
| `traces/metadata.py` | Parse the ClickHouse-aggregated `tracely.metadata.*` JSON. |
| `evaluation/results.py` | `EvalResult`, `RunContext` dataclasses. |
| `evaluation/text.py` | Answer / I/O text extraction shared between structural + judge. |
| `evaluation/output_schema.py` | `model_from_json_schema` — compile a user's JSON schema definition into a Pydantic model for structured LLM output (runtime enum→`Literal` enforcement). |
| `evaluation/generation.py` | `generate_evaluator_from_prompt` — AI-generate an evaluator config from a natural-language prompt. |
| `evaluation/template_resolver.py` | `TEMPLATE_VARIABLES` catalog + `build_context` + `TemplateResolver` — `@VARIABLE` resolution for advanced-mode judge prompts (pure; materializes only the referenced vars). |
| `evaluation/targeting.py` | `spec_applies` — does an evaluator run on this trace? `target_agent`/`target_env` match + deterministic per-`(trace, evaluator)` `sampling`. |
| `evaluation/verdict.py` | `is_failing` / `rollup_verdict` — the one roll-up policy (FAIL iff a non-advisory FAIL). |
| `evaluation/rolling_summary.py` | The summary item schema + pure helpers (`step_components`, `format_summary_as_history`, compaction) for the accumulating conversation summary. |
| `evaluation/evaluators/` | `Evaluator` ABC + `EvaluatorRegistry` + one class per check (`RunOutcomeEvaluator`, `ToolSuccessEvaluator`, `ToolConsistencyEvaluator`, `LatencyEvaluator`, `RequiredToolsEvaluator`, `LLMJudgeEvaluator`) + `TEMPLATES` catalog + `DEFAULT_JUDGE_PROMPT`. |
| `evaluation/evaluator_suggestion.py` | Generate a starting-point evaluator **draft** (structural check or judge rubric) from a cluster's failure mechanism. |
| `analysis/statistics.py` | Deterministic cross-metric stats for meta-analysis — Spearman correlations (tie-averaged ranks) + z-score outliers. Pure, numpy-only. |
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
| `db/models.py` | Postgres registry entities + enums (Project, IngestKey, Agent, AgentVersion, EvaluationSuite/Case, GateRun/Case, FailureCluster/Member, FailureEmbedding, Evaluator, CaseReplay, User, Membership, Invitation, MetaAnalysis, RollingSummary, ConversationAgents). |
| `db/repositories.py` | Query helpers for every model (`evaluator_enabled_specs`, user/membership/invitation CRUD, etc.). |
| `clickhouse/client.py` | sync + async clients; `insert_rows()`. |
| `clickhouse/events_schema.py` | `EVENT_COLUMNS` + `to_rows()`. |
| `clickhouse/trace_reader.py` | `TraceReader` — one class owns every `events`/`scores` SELECT (`read_spans`, `candidate_metrics`, `latest_traces_for_env`, `failing_trace_reasons`, `member_meta`). |
| `clickhouse/score_writer.py` | `ScoreWriter` — `write_eval_scores` + `write_regression_verdict`. |
| `clickhouse/migrations.py` + `ddl/` | Tiny migration runner + the `*.up.sql` files. |
| `blob/s3.py` | S3/MinIO `put_blob` / `get_blob` / `event_blob_key`. |
| `queue/celery_app.py` | The shared Celery app. |
| `llm/embeddings.py` | `Embedder` (OpenAI embeddings, lazy-imported). |
| `llm/provider.py` | `run_structured_agent` / `run_text_agent` — all LLM calls routed through LangChain `create_agent` on OpenRouter (or OpenAI fallback). `llm_enabled()` returns false when neither key is set. |
| `llm/analysis_agents.py` | LangGraph/LangChain agents (`analyze_cluster`, `consolidate`) — lazy-imported. |
| `llm/meta_analysis_agent.py` | `synthesize` — turns the precomputed stats into patterns/recommendations/summary (via the provider; never invents the numbers). |
| `llm/rolling_summary_agent.py` | `summarize_components` — compresses an oversized step's components to ~10–20 words each (only path that calls the LLM for summaries). |
| `registry/agents.py` | Idempotent `upsert_agent` / `upsert_agent_version`. |
| `text.py` | `extract_text` / `message_text` — readable text from stored I/O. |

### `tracely/services/` — use-case orchestrators (classes)
| Class | Owns |
|---|---|
| `IngestionService` | `process_blob` — blob → events → registry resolve → CH insert. Plus the producer `ingest_otlp()` module function. |
| `EvaluationService` | `evaluate_trace` / `evaluate_thread` — load project's evaluators, dispatch via `EvaluatorRegistry`, persist scores, trigger structural clustering. Handles sequential chaining across spans and across conversation turns (`__previous_result__`). |
| `RegressionService` | `promote_trace`, `replay_case`. |
| `GateService` | `run_gate`, `replay_suite`, `resolve_agent_id`. |
| `FailureIntelService` | `rebuild_clusters` — embed → cluster → analyze → consolidate. |
| `StructuralClusteringService` | `cluster_failure` — ingest-time signature clustering. |
| `RollingSummaryService` | `build_for_thread` — the per-span accumulate loop (verbatim vs LLM-compressed; budget-folding). |
| `MetaAnalysisService` | `analyze_and_save` — compute stats + LLM synthesis + merge + persist a per-agent meta-analysis. |
| `ConversationAgentsService` | `for_thread` — read the declared agent catalog (guarded; degrades to spans). |
| `seeding_service` | `main()` — default project + ingest key + recommended evaluators. |

### `tracely/workers/tasks.py`
Three Celery tasks, each a thin dispatch into a service class: `ingest_otlp_blob` → `IngestionService` (then debounce-enqueues evaluation), `evaluate_run` → `EvaluationService` (then folds the turn into the thread's `RollingSummaryService`, best-effort), `rebuild_clusters` → `FailureIntelService`.

### `tracely/otel/` — OTLP → event mapper
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
| `main.py` | App factory + middleware + router mount (auth routers mounted per `AUTH_MODE`). |
| `auth.py` (pkg) | `Authorization: Bearer <ingest-key>` → `project_id`. |
| `advisory.py` | Bridge the project's advisory score-names onto the async read paths (one source for every verdict roll-up). |
| `dto/{common,traces,auth}.py` | Pydantic response models (`SpanOut`, `TraceDetail`, `AgentOut`, `IngestResponse`, auth DTOs). |
| `routers/otlp.py` | OTLP ingest. |
| `routers/traces.py` · `sessions.py` · `search.py` | Trace/session/search reads (sessions also serves rolling-summary + conversation-agents). |
| `routers/cases.py` · `gate.py` · `clusters.py` · `analytics.py` | Regression cases, gate, failure clusters, trends. |
| `routers/evaluators.py` · `evaluations.py` | Evaluator CRUD (`GET/POST/PATCH/DELETE`), templates, models/cost, template-variables, `@VARIABLE` resolve-preview, AI-generate; SSE on-demand runs. |
| `routers/meta_analysis.py` | Per-agent meta-analysis: list agents, run, fetch latest/by-id, delete. |
| `routers/auth.py` | Auth endpoints (common `me`/`logout`/`projects` + mode-specific local/clerk routers). |
| `routers/health.py` | Readiness probe (ClickHouse + Postgres; 503 when either is down). |

## API surface (`backend/tracely/api/routers/`)

| Method · Path | Router | Does |
|---|---|---|
| `POST /v1/traces` | `otlp.py` | OTLP/HTTP ingest (protobuf or JSON) → blob + enqueue. |
| `GET /api/traces`, `/api/traces/{id}` | `traces.py` | trace list; trace detail (spans + scores + verdict). |
| `GET /api/sessions`, `/api/sessions/{thread}` | `sessions.py` | conversations (grouped by `conversation_id`) + per-turn rollups (tokens, input/output split, model, cost, verdict). |
| `GET /api/sessions/{thread}/agents` | `sessions.py` | the conversation's agents — declared (SDK catalog) or derived from spans. |
| `GET …/{thread}/rolling-summary` · `…/by-level` · `POST …/generate` | `sessions.py` | the accumulated conversation summary (whole / per-level) + on-demand rebuild. |
| `GET /api/search` | `search.py` | ⌘K search over conversations/issues/cases/gates. |
| `GET /api/stats` · `POST /api/promote` · `GET /api/cases` · `GET /api/cases/{id}` · `POST /api/cases/{id}/replay` | `cases.py` | dashboard stats; promote a trace → case; case list/detail; manual replay. |
| `GET /api/clusters`, `/api/clusters/{id}` · `POST …/rebuild` | `clusters.py` | failure clusters list/detail; trigger `rebuild_clusters`. |
| `POST /api/gate` · `GET /api/gate/suite` · `GET /api/gates`, `/api/gates/{id}` | `gate.py` | run a gate; fetch the replay suite (cases + inputs + fixtures); gate list/detail. |
| `GET /api/trends` | `analytics.py` | daily traces/failures + gate pass-rate + summary (failure rate, MTTR proxy…). |
| `GET /api/evaluators` · `POST /api/evaluators` · `PATCH /api/evaluators/{id}` · `DELETE /api/evaluators/{id}` | `evaluators.py` | evaluator CRUD (POST creates, PATCH partial-updates). |
| `GET /api/evaluators/templates` · `/models` · `/cost` · `/template-variables/{level}` | `evaluators.py` | built-in catalog · selectable judge models · judge cost estimate · `@VARIABLE` catalog for a level. |
| `POST /api/evaluators/resolve` | `evaluators.py` | resolve an advanced `@VARIABLE` prompt against a real trace/thread (live preview, no LLM). |
| `POST /api/evaluators/generate` | `evaluators.py` | AI-generate evaluator config from a natural-language prompt. |
| `POST /api/evaluations/run` | `evaluations.py` | on-demand SSE run of an evaluator — streams one score dict per event. |
| `GET /api/meta-analyses/agents` · `POST …/run` · `GET …/agent/{id}` · `GET/DELETE …/{id}` | `meta_analysis.py` | per-agent meta-analysis: analyzable agents, run, latest-for-agent, fetch/delete. |
| `GET /auth/me` · `POST /auth/logout` · `POST /auth/projects` | `auth.py` | current user + logout + project switch (all modes). |
| `POST /auth/register` · `/login` · `/change-password` · `POST/GET /auth/invitations` · `DELETE /auth/invitations/{id}` · `POST /auth/invitations/accept` | `auth.py` | local-mode auth + invitations. |
| `POST /auth/sync` | `auth.py` | Clerk-mode user sync. |
| `GET /api/health` | `health.py` | readiness — `200` healthy / `503` when ClickHouse or Postgres is unreachable. |

Every read/write is scoped by `project_id`, resolved from the `Authorization: Bearer <ingest-key>` header (`auth.get_project_id`).

## Data schemas

- **ClickHouse** (`tracely/ch_migrations/*.up.sql`): `0001_events` — the wide span table (identifiers, timing, agent semantics as **first-class indexed columns** `agent_id/agent_run_id/turn_id/step_id/env`, tool edges, `usage_details`/`cost_details` Maps, `input`/`output`, full `metadata` Map), `ReplacingMergeTree(event_ts, is_deleted)`. `0002_scores` — the `scores` sink (`name, verdict, value, evaluation_level, observation_id, source, …`).
- **Postgres** (`migrations/versions/*`, Alembic): `0001` registry (projects/keys/agents/versions) · `0002` suites/cases/replays · `0003` gate runs/cases · `0004` failure clusters/members/embeddings · `0005` FI extensions · `0006` gate metric columns (latency/tokens/warnings) · `0007` evaluators (user-defined: kind, config, score_name, level, enabled, target_agent/env, sampling) · `0008` auth (users, memberships, invitations) · `0009` meta-analyses · `0010` rolling summaries (per-span accumulating summary) · `0011` conversation agents (SDK-declared catalog) · `0012` backfill `config.advisory` on the answer-quality judge.

## Run it

From the repo root (see the [root README](../README.md) for the full quickstart). Local dev (hot reload):
```bash
make infra-up         # clickhouse, postgres, redis, minio
make migrate          # ClickHouse DDL + Alembic (Postgres)
make seed             # default project + ingest key (tracely_dev_key)
make backend          # FastAPI on :8000 (OpenAPI at /docs)
make workers          # Celery worker (the async half of the write path)
make send-trace       # post a sample OTLP trace
make test             # OTLP-mapper + evaluator unit tests (no infra needed)
```
In Docker, the `backend` and `worker` services run this package off a **source volume-mount** (editable install), so a Python edit needs only `docker compose restart backend worker` — **the Celery worker does not hot-reload**, so always restart it after changing worker/eval/FI/mapping code. New Alembic migrations apply via the mounted `migrate` one-shot.

## Tests
`backend/tests/` — unit tests for the OTLP→event mapper, evaluators (all output types, level dispatch, sequential chaining, targeting/sampling), output schema compilation, the `@VARIABLE` template resolver, the advisory verdict policy, the gate/eval contract, rolling summary, meta-analysis statistics, conversation agents, the readiness probe, and SSE streaming. Run with `make test` (no infra needed). CI also runs `ruff check` + this suite + `next build` on every PR (`.github/workflows/ci.yml`).

## Key decisions (and why)

1. **One package, three roles (API · domain · tasks).** The API, the Celery worker, and the CLI all import the same `tracely` domain — no duplicated mapping/DB logic, no drift. (`workers/` is a thin runtime shim.)
2. **Blob-first ingestion.** Durable S3 write *before* enqueue → zero-loss; the queue only ever points at data that already exists.
3. **Server-side batching, not in-process.** `async_insert` instead of Langfuse's in-process writer buffer — correct for a multi-process Celery deployment.
4. **Agent semantics are columns, not metadata.** `agent_id/agent_run_id/conversation_id/turn_id/step_id/env` are indexed ClickHouse columns, so agent-level queries/gating are first-class (Langfuse reconstructs these from strings at read time). [Why](../design/part2-tracely/03-agent-and-trace-data-model.md)
5. **Idempotent writes everywhere.** Deterministic ids + `ReplacingMergeTree` mean re-ingesting a trace or re-evaluating it converges instead of duplicating.
6. **The recorded run is the test.** A regression case = a real trace + its fixture bundle + reference trajectory + fail-to-pass contract — no hand-authored datasets. [Why](../design/part2-tracely/05-regression-testing.md)
7. **Hermetic replay by default.** Fixtures record each tool/LLM call's args, output, and error, replayed FIFO so CI is deterministic, offline, and free. `--live` opts out.
8. **Fail-to-pass is the only hard gate.** Cost/latency/token deltas are advisory warnings — they inform without blocking, avoiding flaky gates. [Why](../design/part2-tracely/08-cicd-architecture.md)
9. **Graceful degradation.** No LLM key (`OPENROUTER_API_KEY` / `OPENAI_API_KEY`) → the LLM judge and failure-intelligence agents are skipped (lazy imports), and the rest of the pipeline runs unchanged.
10. **All LLM calls through one provider.** `infrastructure/llm/provider.py` is the single entry point for every LLM call — OpenRouter as the primary backend (any model), OpenAI as fallback — so model/routing changes need one file, not a dozen.
