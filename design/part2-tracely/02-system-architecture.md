# Tracely — DOC 02: Proposed System Architecture

> **Trace-native CI/CD for AI agents.** Production Trace → Failure Detection → Regression Test → CI/CD Gate. This document defines the V1 service topology, stateful stores, the two core data flows (PRODUCTION LOOP + CI LOOP), the external integration surface, and the deployment/scaling model. It is the spine all sibling docs build on.
>
> **Reuse posture.** Tracely is built on the Langfuse v3.177.1 substrate *literally*: TypeScript monorepo (`web` Next.js + `worker` Express + `packages/shared`), Postgres, ClickHouse (the wide OTel-shaped `events_full` span table), Redis+BullMQ, S3/MinIO, pgvector. The async write path is reused verbatim. Every component below is tagged **REUSED AS-IS** / **EXTENDED** / **NEW** against Langfuse, citing `file:line` for the reused parts. Author opinions are tagged **[Synthesis]**.
>
> Canonical entities (verbatim, used across all docs): Agent, AgentVersion, AgentRun, Trace, Conversation, Turn, Step, ToolCall, LLMCall, SubAgentCall, EvaluationSuite, EvaluationCase, FailureCluster, Score, GateRun.

---

## 0. The one-paragraph architecture

Tracely keeps Langfuse's **two-process split** (Next.js `web` for ingestion + reads + UI; Express `worker` for all async processing) and its **five stateful services**, and adds exactly one new long-lived service — the **CI Gate Orchestrator** — plus several **new BullMQ worker queues** and **new Postgres tables** for the agent registry, suites, cases, clusters, and gate runs. The single most important reuse is the **S3-as-source-of-truth → Redis → worker read-then-merge → batched ClickHouse insert** write path (`processEventBatch.ts:104`, `IngestionService/index.ts`, `ClickhouseWriter/index.ts`), writing one immutable span row per event into the wide `events_full` table (`dev-tables.sh:137-281`). Everything downstream of a stored trace — online evaluation, failure detection, clustering, RCA, regression-test generation, and the CI gate — is a **derive/intelligence layer** that reads from, and is re-runnable against, that same durable event log. The trace is the source of truth; suites, cases, clusters, scores, and gate verdicts are all derived.

---

## 1. Service topology

### 1.1 Process inventory

Three deployable process *types*. Two are reused Langfuse processes (extended); one is new. They are independently scalable containers sharing `packages/shared`.

| Process | Langfuse origin | Posture | Role in Tracely |
|---|---|---|---|
| `tracely-web` | `langfuse-web` (Next.js :3000) | **EXTENDED** | Ingestion front door (native batch + OTLP/OpenInference), tRPC + public REST reads, the UI (trace explorer, failure clusters, suites, gate runs). Runs DB migrations on boot. |
| `tracely-worker` | `langfuse-worker` (Express :3030) | **EXTENDED** | Hosts all BullMQ consumers: ingestion (reused), derive/intelligence (new), eval/replay (extended). One image, per-queue enable flags. |
| `tracely-gate` | — | **NEW** | The CI Gate Orchestrator: an Express service that owns the GitHub App webhook receiver + `GateRun` state machine, fans replay jobs to `tracely-worker`, aggregates verdicts, and posts the PR comment / commit status. Synchronous-ish control plane that must NOT inherit the 15s ingestion delay. |

> **[Synthesis] Why a separate `tracely-gate` service and not just another worker queue?** A CI gate is a *control-plane* concern with hard latency expectations (a PR check that takes the 15s ingestion delay + 1s batch interval + queue backlog feels broken — see Part 1 doc 02 §"Open infra decisions"). It must hold short-lived gate state, talk to GitHub synchronously (check-run create/update), and survive worker autoscaling churn. We keep it thin: it *orchestrates* (state + GitHub I/O) but delegates the heavy replay+eval compute to the worker pool. In a one-container dev deploy it can be folded into `tracely-worker`; in prod it is its own replica set.

### 1.2 Logical service decomposition (the worker is many pools)

`tracely-worker` is a single image whose `app.ts` registers queue consumers gated by `QUEUE_CONSUMER_*_IS_ENABLED` flags — the exact Langfuse pattern (`worker/src/app.ts:128-634`, `worker/src/queues/workerManager.ts:127-185`). You deploy the same image multiple times with different flag sets to get **dedicated worker pools** (Part 1 doc 09 §1). Tracely defines these logical pools:

| Logical worker pool | Queues consumed | Posture | What it does |
|---|---|---|---|
| **Ingestion worker(s)** | `IngestionQueue`, `OtelIngestionQueue` (+ secondaries) | **REUSED AS-IS** | S3 download → read-then-merge → write `events_full`. Verbatim `ingestionQueueProcessorBuilder` (`worker/src/queues/ingestionQueue.ts:29`). |
| **Derive/intelligence worker(s)** | `AgentRunComplete` (new), `FailureDetectQueue` (new), `ClusteringQueue` (new), `RcaQueue` (new), `TestGenQueue` (new) | **NEW** (shell EXTENDED from `TraceUpsert`) | Online failure detection, ingest-time Drain3 templating + MinHash dedup, batch BERTopic clustering, first-failing-step RCA, regression-test generation. |
| **Eval/replay worker(s)** | `EvaluationExecution` (extended), `LLMAsJudgeExecution` (reused), `CodeEvalExecution` (reused), `ReplayQueue` (new) | **EXTENDED** | Run trajectory match + LLM-judge evals; **hermetic replay** of an EvaluationCase against an AgentVersion using recorded fixtures. |
| **Gate-support worker(s)** | `GateRunQueue` (new, orchestrator), `ReplayQueue` (shared), `WebhookQueue` (reused) | **EXTENDED** | Orchestrates a GateRun (select suites, fan out, decide) and executes the per-case replays it fans out; delivers the GitHub `repository_dispatch` / check-run updates via reused webhook machinery (`worker/src/queues/webhooks.ts:486-570`). |

Mapping to the prompt's requested services:
- *web/API* → `tracely-web` (EXTENDED).
- *ingestion worker(s)* → Ingestion pool (REUSED).
- *derive/intelligence worker(s)* → Derive pool (NEW).
- *eval/replay workers* → Eval/replay pool (EXTENDED).
- *CI gate orchestrator service* → `tracely-gate` (NEW) + Gate-support pool.

### 1.3 Control plane vs data plane

- **Data plane** (high volume, async, eventually-consistent): SDK/OTLP → `tracely-web` ingestion → S3 → Redis → Ingestion workers → ClickHouse `events_full`. Then Derive workers read spans and write `Score`, `FailureCluster`, `EvaluationCase` candidates. This is throughput-bound and reuses Langfuse wholesale.
- **Control plane** (low volume, latency-sensitive, strongly-consistent in Postgres): the agent registry CRUD, suite/case authoring, and the **GateRun state machine** (`tracely-gate`). A GateRun's lifecycle (`PENDING → RUNNING → PASS/FAIL/ERROR`, GateStatus) lives in Postgres with a `GateCase` row per case; the actual replay compute is dispatched to the data plane (Eval/replay workers) but the *verdict aggregation and GitHub I/O* are control plane.

```mermaid
flowchart TB
    SDK["Agent SDK / OTel exporter\n(LangGraph, Agno, OpenAI Agents SDK, custom OTLP)"]
    GH["GitHub App + Action\n(PR opened / push / repository_dispatch)"]

    subgraph WEB["tracely-web (Next.js :3000) — EXTENDED"]
        ING["/api/public/ingestion\n/api/public/otel/v1/traces"]
        TRPC["tRPC + public REST (reads)"]
        UI["UI: trace explorer, clusters,\nsuites, cases, gate runs"]
        PEB["processEventBatch()"]
    end

    subgraph WORKER["tracely-worker (Express :3030) — EXTENDED"]
        direction TB
        IWP["Ingestion pool — REUSED\nS3 merge → events_full"]
        DWP["Derive/intelligence pool — NEW\nfailure-detect, cluster, RCA, test-gen"]
        EWP["Eval/replay pool — EXTENDED\ntrajectory match, LLM-judge, replay"]
    end

    subgraph GATE["tracely-gate (Express) — NEW"]
        GHR["GitHub webhook receiver"]
        ORCH["GateRun state machine\n(fan-out → aggregate → verdict)"]
        STATUS["check-run / PR comment writer"]
    end

    S3[("S3 / MinIO — REUSED\nraw span blobs +\nreplay fixtures")]
    REDIS[("Redis + BullMQ — REUSED\nqueues + caches")]
    CH[("ClickHouse — EXTENDED\nevents_full (wide spans) + scores")]
    CHRO[("ClickHouse read replica\n(optional)")]
    PG[("Postgres — EXTENDED\nAgent/Version registry,\nSuites, Cases, Clusters, GateRuns")]
    PGV[("pgvector — NEW\nfailure embeddings")]

    SDK -->|POST batch / OTLP| ING --> PEB
    PEB -->|1 upload span JSON| S3
    PEB -->|2 enqueue pointer job| REDIS
    REDIS --> IWP
    IWP -->|read blobs| S3
    IWP -->|read-then-merge SELECT| CH
    IWP -->|INSERT JSONEachRow| CH
    IWP -->|AgentRunComplete| REDIS --> DWP
    DWP -->|read spans| CH
    DWP -->|embeddings| PGV
    DWP -->|clusters, candidate cases| PG
    DWP -->|online scores| CH
    DWP -->|replay fixtures| S3

    GH -->|webhook| GHR --> ORCH
    ORCH -->|create GateRun + cases| PG
    ORCH -->|enqueue ReplayQueue| REDIS --> EWP
    EWP -->|load case + fixtures| S3
    EWP -->|hermetic replay → trajectory| CH
    EWP -->|GateCase verdict| PG
    ORCH -->|aggregate| PG
    STATUS -->|check-run + PR comment| GH

    UI --> TRPC
    TRPC -->|read| CHRO
    TRPC -->|metadata| PG
    CHRO -.replicates.-> CH
```

---

## 2. Stateful stores — what each is for and why it exists

Five physical stores (pgvector rides inside Postgres). Each is reused from Langfuse; the *contents* differ where Tracely adds first-class agent/eval entities.

### 2.1 Postgres — OLTP registry & control plane (EXTENDED)

**Why:** strongly-consistent, relational metadata that must support transactions, foreign keys, and the GateRun state machine. Langfuse already puts orgs/projects/auth/`JobConfiguration`/`JobExecution`/datasets here (`schema.prisma`). Tracely **reuses** the org/project/auth/API-key tables verbatim, **reuses** `EvalTemplate`/`JobConfiguration`/`JobExecution` for the eval-execution plumbing (`schema.prisma:917-1051`), and **adds** the agent-first registry. `project_id` is the tenancy key everywhere (same as Langfuse).

New Prisma models (see DOC for the data model for full DDL; sketch here so siblings agree on names):

```prisma
// NEW — Tracely agent registry
model Agent {
  id          String   @id @default(cuid())
  projectId   String   @map("project_id")
  name        String                                  // stable agent identity
  framework   String?                                 // "langgraph" | "agno" | "openai-agents" | "otel"
  createdAt   DateTime @default(now())
  @@unique([projectId, name])
  @@index([projectId])
}

model AgentVersion {
  id            String   @id @default(cuid())
  projectId     String   @map("project_id")
  agentId       String   @map("agent_id")
  versionLabel  String   @map("version_label")        // git sha / semver / release tag
  gitSha        String?  @map("git_sha")
  gitRef        String?  @map("git_ref")
  metadata      Json?                                  // model ids, prompt hashes, config snapshot
  createdAt     DateTime @default(now())
  @@unique([projectId, agentId, versionLabel])
  @@index([projectId, agentId])
}

// NOTE: AgentRun has NO Postgres table. It is ClickHouse-only (= the root/is_app_root
// span, keyed by agent_run_id). Run-level facts are read-time aggregates over spans
// (LIMIT 1 BY / argMaxIf). See 00-canonical-decisions.md §2 and doc 03/09.

model EvaluationSuite {
  id          String   @id @default(cuid())
  projectId   String   @map("project_id")
  agentId     String   @map("agent_id")                // a suite belongs to an Agent
  name        String
  isActive    Boolean  @default(true)
  @@unique([projectId, agentId, name])
}

model EvaluationCase {
  id                       String   @id @default(cuid())
  projectId                String   @map("project_id")
  suiteId                  String   @map("suite_id")
  // provenance (the whole point — derived from a production trace)
  sourceTraceId            String   @map("source_trace_id")          // ClickHouse, no FK
  sourceAgentRunId         String?  @map("source_agent_run_id")
  failureClusterId         String?  @map("failure_cluster_id")
  agentVersionFirstFailed  String?  @map("agent_version_first_failed")
  // captured replay material (pointers into S3)
  inputBlobKey             String   @map("input_blob_key")           // captured trace input/prefix
  fixtureBundleKey         String   @map("fixture_bundle_key")       // recorded tool/LLM outputs
  referenceTrajectoryKey   String   @map("reference_trajectory_key")
  // match config (agentevals taxonomy)
  trajectoryMatchMode      String   @map("trajectory_match_mode")    // strict|unordered|subset|superset
  toolArgsMatchMode        String   @map("tool_args_match_mode")     // exact|ignore|subset|superset
  toolArgsOverrides        Json?    @map("tool_args_overrides")
  judgeRubric              Json?    @map("judge_rubric")             // optional G-Eval rubric
  // FAIL-TO-PASS contract
  failsOnVersionId         String?  @map("fails_on_version_id")      // must FAIL here
  passesOnVersionId        String?  @map("passes_on_version_id")     // expected PASS here
  state                    String   @default("candidate")           // candidate|active|quarantined
  @@index([projectId, suiteId])
  @@index([projectId, failureClusterId])
}

model FailureCluster {
  id              String   @id @default(cuid())
  projectId       String   @map("project_id")
  agentId         String?  @map("agent_id")
  label           String                                 // c-TF-IDF / MAST / TRAJECT-Bench label
  taxonomyBucket  String?  @map("taxonomy_bucket")       // MAST: spec | inter-agent | verification
  drainTemplateId String?  @map("drain_template_id")     // ingest-time first-pass key
  medoidTraceId   String?  @map("medoid_trace_id")
  occurrenceCount Int      @default(0)
  firstSeenAt     DateTime @map("first_seen_at")
  lastSeenAt      DateTime @map("last_seen_at")
  status          String   @default("open")              // open|triaged|promoted|ignored
  @@index([projectId, agentId, status])
}

// Canonical GateRun shape (full DDL is in doc 09 — schema of record; canonical: 00-canonical-decisions.md §2/§7.5).
// Do NOT redefine a competing shape: it keys the candidate via agentVersionId, the baseline via
// baselineVersionId, and the suites it covers via selectedSuiteIds[] (no single suiteId).
model GateRun {
  id                String   @id @default(cuid())
  projectId         String   @map("project_id")
  agentId           String   @map("agent_id")
  agentVersionId    String   @map("agent_version_id")     // the candidate version under test
  baselineVersionId String?  @map("baseline_version_id")  // env=prod baseline for deltas
  selectedSuiteIds  String[] @map("selected_suite_ids")   // suites this gate ran
  // GitHub linkage
  repoFullName    String   @map("repo_full_name")        // "owner/repo"
  prNumber        Int?     @map("pr_number")
  headSha         String   @map("head_sha")
  checkRunId      String?  @map("check_run_id")          // GitHub check-run id
  installationId  String?  @map("installation_id")       // GitHub App install
  status          String   @default("PENDING")           // GateStatus: PENDING|RUNNING|PASS|FAIL|ERROR
  trigger         String   @default("PULL_REQUEST")      // GateTrigger: PULL_REQUEST|MANUAL|SCHEDULED|API
  totalCases      Int      @default(0)
  passedCases     Int      @default(0)
  failedCases     Int      @default(0)
  createdAt       DateTime @default(now())
  finishedAt      DateTime?
  @@index([projectId, agentVersionId])
  @@index([repoFullName, headSha])
}

// Per-case verdict/cost/latency for the decision engine + PR comment (canonical entity: GateCase).
model GateCase {
  id               String   @id @default(cuid())
  gateRunId        String   @map("gate_run_id")
  evaluationCaseId String   @map("evaluation_case_id")
  verdict          String   @default("SKIP")              // Verdict: PASS|FAIL|SKIP
  scoreId          String?  @map("score_id")              // ClickHouse scores.id
  replayTraceId    String?  @map("replay_trace_id")       // hermetic replay's own trace
  @@unique([gateRunId, evaluationCaseId])
}
```

### 2.2 ClickHouse — OLAP span store + scores (EXTENDED)

**Why:** append-heavy, time-partitioned, columnar — the right home for billions of spans and the trajectory-shaped reads Tracely's evals need. Tracely uses **one wide immutable OTel-shaped span table** modeled on Langfuse `events_full` (`dev-tables.sh:137-281`), `ENGINE = ReplacingMergeTree(event_ts, is_deleted)`, `PARTITION BY toYYYYMM(start_time)`, `ORDER BY (project_id, toStartOfMinute(start_time), xxHash32(trace_id), span_id, start_time)` — which **co-locates all spans of a trace** so reconstructing a full trajectory is a contiguous range scan. Plus the `scores` table (`0003_scores.up.sql` + `0030`), reused for eval/gate verdicts.

The **EXTENSION** vs Langfuse is the addition of Tracely first-class semantic columns to `events_full`, so Agent/Conversation/Turn/Step are NOT reconstructed from `metadata['langgraph_node']` at read time (the core gap — see Part 1 doc 01 §9.8, `traces.ts:1572-1608`). Added columns (full DDL in the storage doc; named here for coherence):

```sql
-- EXTENDED: Tracely first-class semantic columns on events_full
agent_id           String,          -- denormalized onto every span
agent_version_id   String,
agent_run_id       String,
conversation_id    String,
turn_id            String,
turn_index         UInt32,          -- turn ordering within a conversation
step_id            String,
step_name          String,
env                LowCardinality(String) DEFAULT 'prod',  -- {prod,staging,ci,dev} — THE GATING AXIS (canonical: 00-canonical-decisions.md §5)
-- typed edges
tool_call_id       String,          -- links an LLMCall tool-call request to the TOOL span that executed it
caller_agent_id    String,          -- handoff edge: who handed off
callee_agent_id    String,          -- handoff edge: who received
edge_type          LowCardinality(String),  -- handoff|delegate|sub-agent
-- provenance (Tracely meaning; reuses the Langfuse denormalization trick)
evaluation_case_id String,
gate_run_id        String,
failure_cluster_id String,
INDEX idx_agent_run_id  agent_run_id  TYPE bloom_filter(0.01) GRANULARITY 1,
INDEX idx_conversation  conversation_id TYPE bloom_filter(0.01) GRANULARITY 1
-- NOTE: the base events_full dataset experiment_* block and prompt_id/prompt_name/prompt_version
-- are DROPPED (thesis hygiene); replaced by the provenance columns above. Langfuse free-string
-- `environment` is KEPT (OTel compat) alongside the Tracely `env` enum. (canonical: 00-canonical-decisions.md §5)
```

These reuse the existing `type LowCardinality(String)` column whose enum already covers `AGENT, TOOL, CHAIN, RETRIEVER, EVALUATOR, EMBEDDING, GUARDRAIL` (`observations.ts:5-16`) — so ToolCall/LLMCall/SubAgentCall map to span `type` + `parent_span_id` + the new edge columns. Score addressing reuses Langfuse verbatim (a `Score` targets any of trace/observation/session via nullable address columns + `execution_trace_id`, `scores.ts` / `0030`) and Tracely extends the addressing *semantically* to conversation/turn/step/tool/run by writing those targets into the score's `observation_id`/metadata and the new columns.

`events_core` (the truncated 200-char projection via `events_core_mv`, `dev-tables.sh:414-482`) is reused as the fast list/dashboard table. Read replica via `CLICKHOUSE_READ_ONLY_URL` / `CLICKHOUSE_EVENTS_READ_ONLY_URL` (`client.ts:109-125`) — REUSED.

### 2.3 Redis + BullMQ — queues & caches (REUSED AS-IS)

**Why:** durable job state + the sharding/overflow machinery that isolates noisy workloads. Reused verbatim: `WorkerManager.register` (`workerManager.ts:127-185`), `getShardIndex` SHA-256 sharding (`sharding.ts:9-20`), primary/secondary overflow lanes with self-healing redirect (`ingestionQueue.ts:108-133`), `RetryBaggage` 24h LLM rate-limit requeue (`retry-handler.ts`), cron-singleton scheduling. `--maxmemory-policy noeviction` is mandatory (queues are durable, not a cache — `docker-compose.yml:136-137`). Tracely **adds new queue names** to the `QueueName` enum (§3.3) but reuses every queue primitive.

### 2.4 S3 / MinIO — raw blobs + replay fixtures (EXTENDED)

**Why:** the durable **source of truth**. Every ingested span is written to S3 *before* enqueue (`processEventBatch.ts:268-272`, fail-closed); ClickHouse is derived and rebuildable from S3 (Part 1 doc 05 §10). Reused verbatim for raw spans (`events/` prefix). **EXTENDED** with a new prefix family for Tracely's regression material:

```
events/<proj>/<entityType>/<entityId>/<key>.json        # REUSED: raw span event log
otel/<proj>/<yyyy/mm/dd/hh/mm>/<uuid>.json              # REUSED: raw OTLP payloads
fixtures/<proj>/<caseId>/tools/<toolCallId>.json        # NEW: recorded tool outputs (hermetic replay)
fixtures/<proj>/<caseId>/llm/<llmCallId>.json           # NEW: recorded LLM outputs (optional)
fixtures/<proj>/<caseId>/reference-trajectory.json      # NEW: gold trajectory
fixtures/<proj>/<caseId>/input-prefix.json              # NEW: captured trace input/prefix
```

The fixture bundle is what makes a regression test **deterministic and hermetic**: replaying an EvaluationCase against a new AgentVersion serves recorded tool/LLM outputs instead of calling real tools/models, so the test isolates the agent logic. Reuse `StorageService.uploadJson` (`StorageService.ts:715-731`) and the multi-cloud factory (`StorageService.ts:206-257`) as-is.

### 2.5 pgvector — failure embeddings (NEW)

**Why:** failure clustering needs nearest-neighbor search over sentence embeddings of failing traces. **[Synthesis]** We put embeddings in pgvector (a Postgres extension) rather than a separate vector DB to keep V1's store count at five and to co-locate embeddings with the `FailureCluster` rows they belong to. The batch BERTopic path (sentence-embeddings → UMAP → HDBSCAN → c-TF-IDF, per techniques doc §2.1) runs in a Derive worker; the embedding lives on the `ClusterMember` membership join (one embedding store — there is no separate `FailureEmbedding` table; canonical: 00-canonical-decisions.md §6):

```prisma
// NEW — membership join; holds the embedding + medoid flag (canonical: 00-canonical-decisions.md)
model ClusterMember {
  clusterId   String                @map("cluster_id")
  traceId     String                @map("trace_id")        // ClickHouse, no FK
  projectId   String                @map("project_id")
  agentRunId  String?               @map("agent_run_id")
  isMedoid    Boolean  @default(false) @map("is_medoid")
  embedding   Unsupported("vector(1024)")                     // 1024-d sentence embedding (bge-large-en-v1.5 / text-embedding-3-large@1024)
  @@id([clusterId, traceId])
  @@index([projectId, clusterId])
}
// + an hnsw index on embedding for ANN search
```

Drain3 `template_id` + MinHash-LSH dedup (techniques §2.2/§2.4) run **at ingest time** (cheap, no embedding) to give a free first-pass cluster key and occurrence counting; pgvector ANN is the *batch* semantic pass.

---

## 3. The two data flows

### 3.1 PRODUCTION LOOP — ingest → store → online eval/failure-detect → cluster → candidate regression test

This is the data plane. Stages 1–7 below: stages 1–4 are **REUSED AS-IS** from Langfuse; stages 5–7 are the **NEW** derive/intelligence layer.

1. **Ingest (web).** SDK/OTLP POSTs to `/api/public/ingestion` or `/api/public/otel/v1/traces`. `processEventBatch` validates (Zod), groups by `${entityType}-${body.id}`, uploads each group's span JSON to S3 **fail-closed**, then enqueues a pointer-only job (no bodies) to a sharded `IngestionQueue` with a small delay. REUSED: `processEventBatch.ts:104-349`.
2. **Merge (worker).** Ingestion pool downloads all S3 files for the entity, reads the current ClickHouse row (`SELECT … ORDER BY event_ts DESC LIMIT 1 BY id, project_id`), merges field-level LWW with immutable keys pinned, sets `event_ts = now()`, and buffers into `ClickhouseWriter`. REUSED: `IngestionService/index.ts`, `ClickhouseWriter/index.ts`.
3. **Store.** `ClickhouseWriter` flushes batches (size or interval) into `events_full` via `async_insert=1` JSONEachRow; `events_core_mv` auto-populates the truncated table; `ReplacingMergeTree` dedups on background merge. REUSED: `dev-tables.sh:137-482`, `client.ts:203-204`.
4. **Run-complete trigger.** On the *root span* of a run settling, the worker enqueues an **`AgentRunComplete`** job — the Tracely analog of Langfuse's `TraceUpsert` (`IngestionService/index.ts:705-734`). **EXTENDED**: the sharding/debounce key becomes `projectId-agentRunId` (or `projectId-conversationId`) rather than `projectId-traceId`, so all turns/steps of one run land on one shard and one debounce window (Part 1 doc 09 §9, recommended). Keep the producer-side `delay: 30_000` debounce so a multi-turn / multi-agent trace is fully assembled before evals run (`traceUpsert.ts:80`).
5. **Online failure detection (Derive).** `FailureDetectQueue` consumer reads the run's spans from `events_full` (one contiguous range scan), walks the span tree, and applies: (a) **deterministic signals** — span `level = ERROR` (`observations.ts:32-43`), tool error strings, unhandled exceptions, TRAJECT-Bench tool-failure modes (techniques §1.3); (b) **online evaluators** — reuse the `createEvalJobs` → `JobExecution(PENDING)` → `EvaluationExecution` spine (`evalService.ts:180-389`) but **EXTENDED** with a trajectory-shaped variable extractor (the single-observation extractor is replaced — verified-facts §"REPLACE/EXTEND"). Verdicts are written as `Score` rows (`source: EVAL`, deterministic ids via `uuidv5`, `evalScoreIds.ts`) addressed at run/turn/step level. The first-failing-step is localized on the span tree (techniques §3.1) and recorded as a `Score`/marker addressed at the `agent_run_id` (AgentRun is ClickHouse-only — no Postgres row).
6. **Cluster (Derive).** At ingest time the run's normalized error/log fields get a Drain3 `template_id` + MinHash-LSH dedup key (cheap, online). A **`ClusteringQueue`** batch job (cron-singleton, nightly) embeds failing traces (sentence-transformers → pgvector), runs UMAP → HDBSCAN → c-TF-IDF labels (BERTopic), and upserts `FailureCluster` rows with medoid + occurrence counts (techniques §2). HDBSCAN noise = candidate *novel* failures, surfaced separately.
7. **Candidate regression test (Derive).** `TestGenQueue` consumer turns a triaged cluster's medoid into a **candidate `EvaluationCase`**: mine exact inputs/tool-args from the failing trace (BRMiner-style), record tool/LLM outputs to the S3 fixture bundle, extract the reference trajectory, set a default match mode (`unordered` + `exact` args — techniques §1.5), optionally attach a G-Eval rubric, and write the FAIL-TO-PASS contract (`fails_on_version_id` = `agent_version_first_failed`). The case starts `state = candidate`; a human confirms it into a suite (test-gen is candidate drafting, not autonomous authoring — techniques §3.3). RCA (`RcaQueue`) runs the first-failing-step localization + an LLM RCA agent over the localized sub-trace to attach a root-cause hypothesis.

```mermaid
flowchart LR
    subgraph DP["DATA PLANE (async, high volume)"]
        direction TB
        A["SDK / OTLP"] -->|POST| B["web: processEventBatch\nREUSED"]
        B -->|"1 upload (fail-closed)"| S3[("S3 spans\nREUSED")]
        B -->|"2 pointer job"| Q1(["IngestionQueue\nREUSED"])
        Q1 --> C["Ingestion worker\nread-then-merge\nREUSED"]
        C -->|INSERT| CH[("events_full\nEXTENDED")]
        C -->|"3 AgentRunComplete\n(key=agentRunId, delay 30s)"| Q2(["AgentRunComplete\nEXTENDED"])
        Q2 --> D["FailureDetect worker\nNEW"]
        D -->|"deterministic + online evals"| SC[("scores\nREUSED")]
        D -->|"first-failing-step marker\n(keyed agent_run_id)"| SC
        D -->|template_id + minhash| Q3(["ClusteringQueue\nNEW"])
        Q3 --> E["Cluster worker (nightly)\nembed→UMAP→HDBSCAN→cTFIDF\nNEW"]
        E -->|embeddings| PGV[("pgvector\nNEW")]
        E -->|clusters+medoid| FC[("FailureCluster\nNEW")]
        FC --> F["TestGen + RCA worker\nNEW"]
        F -->|"mine inputs, record fixtures"| S3
        F -->|candidate EvaluationCase| EC[("EvaluationCase\nNEW")]
    end
    subgraph CP["CONTROL PLANE (low volume)"]
        H["Human triage in UI\nconfirm cluster → promote case"]
    end
    FC -.surfaced.-> H
    EC -.confirm.-> H
    H -->|activate| EC
```

### 3.2 CI LOOP — PR → new AgentVersion → gate orchestrator → replay suites on workers → PASS/FAIL → PR comment

This is the control plane (`tracely-gate`) driving the data plane (Eval/replay workers). The headline primitive Langfuse has no analog for.

1. **PR / push (GitHub).** A developer opens/updates a PR that changes an agent. The **Tracely GitHub Action** (`.github/workflows/tracely.yml`) calls the Tracely API to register a new `AgentVersion` (git sha + ref) and request a gate; *or* the **GitHub App** receives a `pull_request` / `push` webhook directly. Either way `tracely-gate`'s receiver lands the event.
2. **Create GateRun (gate).** `tracely-gate` resolves the Agent + active `EvaluationSuite`, creates a `GateRun` (`status=PENDING`), one `GateCase` per active `EvaluationCase`, and **immediately creates a GitHub check-run** (`status=in_progress`) so the PR shows "Tracely / regression-gate — running" within seconds. State in Postgres.
3. **Fan out replays (gate → workers).** `tracely-gate` enqueues one `ReplayQueue` job per case (payload carries `caseId`, `gateRunId`, `agentVersionId`, fixture bundle key). Bypasses the ingestion delay entirely — this is a control-plane dispatch, not telemetry.
4. **Hermetic replay (Eval/replay worker).** Each worker loads the case's `input-prefix.json` + `fixtureBundle` from S3, runs the **target AgentVersion** with tool/LLM calls served from the recorded fixtures (deterministic), captures the produced trajectory as its own trace in `events_full` (so replays are themselves observable), then scores it: deterministic **trajectory match** (`agentevals` modes: strict|unordered|subset|superset × tool-args exact|ignore|subset|superset, per-tool overrides — techniques §1.2) first, LLM-judge rubric (G-Eval + bias mitigations: position-swap, cross-provider, reference-guided) only where structure can't decide. Writes a `Score` and the `GateCase.verdict`. The verdict honors the **FAIL-TO-PASS contract**: a case is meaningful only if it *fails* on `fails_on_version_id`.
5. **Aggregate verdict (gate).** As `GateCase` rows complete, `tracely-gate` aggregates: `GateRun.status = PASS` iff all required cases pass (configurable threshold + quarantine handling for flaky cases). Updates counts.
6. **Report (gate).** On completion `tracely-gate` updates the GitHub check-run (`conclusion=success|failure`) and posts a PR comment with per-case verdicts + score deltas vs the baseline version (the proven Braintrust UX — competitive doc §"steal these"). Delivery reuses the Langfuse webhook machinery: GitHub `repository_dispatch` client with HMAC signing + 64KB payload truncation (`webhooks.ts:486-570`), via `WebhookQueue` (REUSED), or a direct check-run API call from `tracely-gate`.

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Developer
    participant GH as GitHub (App + Action)
    participant Gate as tracely-gate (orchestrator)
    participant PG as Postgres (GateRun)
    participant RQ as Redis (ReplayQueue)
    participant W as Eval/replay worker
    participant S3 as S3 (fixtures)
    participant CH as ClickHouse (events_full + scores)

    Dev->>GH: open / update PR (agent changed)
    GH->>Gate: webhook (pull_request) OR Action → POST /api/gate
    Gate->>PG: upsert AgentVersion(gitSha); create GateRun(status=queued)
    Gate->>PG: create GateCase per active EvaluationCase
    Gate->>GH: create check-run (in_progress)  %% <5s, control plane
    loop per EvaluationCase
        Gate->>RQ: enqueue ReplayQueue{caseId, gateRunId, versionId}
    end
    RQ->>W: deliver replay job (no ingestion delay)
    W->>S3: load input-prefix + fixture bundle
    W->>W: run target AgentVersion with hermetic fixtures
    W->>CH: write replay trajectory (own trace)
    W->>W: trajectory match (agentevals) → LLM-judge if needed
    W->>CH: write Score (source=EVAL, deterministic id)
    W->>PG: set GateCase.verdict + scoreId + replayTraceId
    Note over W,PG: verdict respects FAIL-TO-PASS contract
    Gate->>PG: poll/subscribe: all cases done?
    Gate->>PG: GateRun.status = passed|failed (threshold)
    Gate->>GH: update check-run (success|failure)
    Gate->>GH: PR comment (per-case verdicts + score deltas)
    GH-->>Dev: merge blocked/allowed by required check
```

---

## 4. External integration surface

Four front doors. Two reused, two new.

### 4.1 OTLP / OpenInference ingestion front door (REUSED AS-IS)

`POST /api/public/otel/v1/traces` — OTLP/HTTP only (protobuf + JSON, gzip), Basic-Auth public/secret key pair (`otel/v1/traces/index.ts:79-159`). Raw `resourceSpans` go to S3, an `OtelIngestionJob` is enqueued; `OtelIngestionProcessor` maps spans → events with the full `ObservationTypeMapperRegistry` (10 priority mappers covering OpenInference, OTel GenAI, Vercel AI SDK, LangGraph/LiveKit/Genkit — `ObservationTypeMapper.ts:165-489`). This is how Tracely stays **framework-agnostic** (LangGraph, Agno, OpenAI Agents SDK, custom OTel — product vision requirement). **[Synthesis]** Tracely *adds* recognition of a small set of new span attributes (`tracely.agent.id`, `tracely.agent_version.id`, `tracely.conversation.id`, `tracely.turn.id`, `tracely.turn.index`, `tracely.step.id`, `tracely.handoff.callee`) so the first-class semantic columns (§2.2) are populated from instrumentation rather than reconstructed — mirroring the `LangfuseOtelSpanAttributes` pattern (`attributes.ts`). Absent those, Tracely falls back to deriving turn/step from the span tree + timing (the Langfuse `buildStepData` heuristic).

### 4.2 SDK contract (EXTENDED)

The Langfuse SDKs target `/api/public/otel/v1/traces` via OTLP (verified-facts §sdk-frontend). Tracely's SDK contract is a **thin OTel wrapper** that emits the Tracely semantic attributes above and provides ergonomic spans for `agent_run`, `turn`, `step`, `tool_call`, `llm_call`, `handoff`. **[Synthesis]** Keep the wire protocol = OTLP (do not invent a proprietary protocol — competitive doc §"build ingestion on this, not a proprietary SDK"); the SDK is sugar over OTLP that guarantees the typed-edge attributes (`tool_call_id` linkage, handoff caller/callee) are present so trajectory evals get clean inputs.

### 4.3 GitHub App + Action (NEW)

- **GitHub App** — installed on the customer's repo/org. Receives `pull_request`, `push`, and `installation` webhooks at `tracely-gate`. Holds the installation token (encrypted in Postgres, reusing Langfuse's `encrypt`/`decrypt` — `webhooks.ts:554`) to create/update **check-runs** and post PR comments. This is what makes the gate a **required status check** that blocks merge.
- **GitHub Action** (`tracely/gate-action@v1`) — a thin Action the customer adds to their workflow. On PR, it (a) registers the built `AgentVersion` (git sha + ref + config snapshot), (b) calls `POST /api/gate` to request a GateRun, (c) polls/streams the verdict, (d) sets the job's exit code. **[Synthesis]** Offer both: the App for zero-config gating on customers who can install it; the Action for customers who prefer explicit workflow control or self-hosted runners. Reuse Langfuse's `repository_dispatch` + HMAC signing machinery (`webhooks.ts:486-570`) for the App→repo dispatch direction.

### 4.4 Public API (EXTENDED)

Reuse Langfuse's tRPC (UI) + public REST (`/api/public/*`) surface and its project-scoped API-key auth (`ApiAuthService`, `ingestion.ts:76-94`). Tracely **adds** REST resources for the new entities: `POST/GET /api/public/agents`, `/agent-versions`, `/suites`, `/cases`, `GET /failure-clusters`, `POST /api/gate` (request a GateRun), `GET /api/gate/{id}` (poll verdict). Scores read API is reused. A "scores-only" key scope already exists for delegated eval writes (`processEventBatch.ts:358-374`) — reused.

---

## 5. Deployment & scaling

### 5.1 docker-compose for V1

Reuse Langfuse's reference compose (`docker-compose.yml`) verbatim for the stateful tier and the two app images; add `tracely-gate`. Single-node defaults: `CLICKHOUSE_CLUSTER_ENABLED=false`, `REDIS_CLUSTER_ENABLED=false`, all `*_SHARD_COUNT=1` (sharding only pays off on Redis Cluster — Part 1 doc 09 §"Simplify"). pgvector via the `pgvector/pgvector:pg17` image (drop-in for `postgres:17`).

```yaml
# docker-compose.yml (V1, abbreviated — stateful tier REUSED from Langfuse)
x-tracely-env: &tracely-env
  DATABASE_URL: postgresql://postgres:postgres@postgres:5432/tracely
  CLICKHOUSE_URL: http://clickhouse:8123
  CLICKHOUSE_CLUSTER_ENABLED: "false"
  REDIS_HOST: redis
  REDIS_AUTH: ${REDIS_AUTH}
  LANGFUSE_S3_EVENT_UPLOAD_BUCKET: tracely
  LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT: http://minio:9000
  LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE: "true"
  TRACELY_FIXTURE_BUCKET: tracely
  ENCRYPTION_KEY: ${ENCRYPTION_KEY}          # 64 hex chars (REUSED constraint)

services:
  tracely-web:                                # EXTENDED langfuse-web
    image: tracely/web:1
    ports: ["3000:3000"]
    environment: { <<: *tracely-env, NEXTAUTH_SECRET: ${NEXTAUTH_SECRET} }
    depends_on: [postgres, clickhouse, redis, minio]

  tracely-worker:                             # EXTENDED langfuse-worker
    image: tracely/worker:1
    ports: ["3030:3030"]
    environment:
      <<: *tracely-env
      QUEUE_CONSUMER_INGESTION_QUEUE_IS_ENABLED: "true"
      TRACELY_CONSUMER_DERIVE_IS_ENABLED: "true"      # NEW pool flags
      TRACELY_CONSUMER_EVAL_REPLAY_IS_ENABLED: "true"
    depends_on: [postgres, clickhouse, redis, minio]

  tracely-gate:                               # NEW
    image: tracely/gate:1
    ports: ["3060:3060"]
    environment:
      <<: *tracely-env
      TRACELY_GITHUB_APP_ID: ${TRACELY_GITHUB_APP_ID}
      TRACELY_GITHUB_APP_PRIVATE_KEY: ${TRACELY_GITHUB_APP_PRIVATE_KEY}
      TRACELY_GITHUB_WEBHOOK_SECRET: ${TRACELY_GITHUB_WEBHOOK_SECRET}
    depends_on: [postgres, redis]

  postgres:  { image: pgvector/pgvector:pg17, ... }     # EXTENDED: pgvector
  clickhouse:{ image: clickhouse/clickhouse-server:24.3, ... }   # REUSED
  redis:     { image: redis:7, command: --requirepass ${REDIS_AUTH} --maxmemory-policy noeviction }  # REUSED
  minio:     { image: cgr.dev/chainguard/minio, ... }   # REUSED
```

The `tracely-web` container is the **migration runner** (Prisma + golang-migrate ClickHouse, gated by `LANGFUSE_AUTO_*_MIGRATION_DISABLED`) — REUSED behavior (Part 1 doc 02 §1.1). New ClickHouse columns ship as additive `ALTER TABLE … ADD COLUMN` migrations in the `clustered/`+`unclustered/` dirs (same toggle pattern).

### 5.2 k8s / Helm (later)

No Helm in scope for V1 (Langfuse itself ships none in-repo — Part 1 doc 02 §4). The scaling primitives are exactly what a future Helm chart parametrizes: stateless `tracely-web`/`tracely-worker`/`tracely-gate` Deployments + HPA, the stateful tier as managed services (RDS+pgvector / ClickHouse Cloud / ElastiCache / S3). Run DB migrations as a one-shot Job, disable on serving replicas.

### 5.3 Horizontal scaling

| Tier | Lever | Posture |
|---|---|---|
| `tracely-web` | Stateless; add replicas behind LB. `--keepAliveTimeout 110000`. | REUSED |
| `tracely-worker` | Two axes: replicas (BullMQ distributes) + per-queue `*_CONCURRENCY`. **Selective consumers**: dedicate replica sets per pool via enable-flags (a fleet that only ingests; a fleet that only clusters; a fleet that only replays). | REUSED pattern, NEW pools |
| `tracely-gate` | Stateless control plane; add replicas. GateRun state in Postgres, so any replica can resume aggregation. | NEW |
| Redis | single-node ↔ cluster as a pure toggle; cluster enables hash-tag prefixes + consistent-hash sharding of the 9+ hot queues. | REUSED |
| ClickHouse | `CLICKHOUSE_CLUSTER_ENABLED` = HA replication (NOT sharding — zero `Distributed` tables in Langfuse). Read scaling via `CLICKHOUSE_READ_ONLY_URL` replica. **[Synthesis] Tracely must plan real sharding (ClickHouse Cloud or `Distributed` tables) explicitly for high per-tenant span volume — do not inherit scale-out from Langfuse.** | EXTENDED |
| S3 | Provider-elastic; app-side concurrency caps. | REUSED |

### 5.4 Multi-tenancy

`project_id` is the tenancy boundary on **every** ClickHouse row (it leads every sort/primary key — `dev-tables.sh:268-273`), every Postgres table, and every S3 path prefix. Reused verbatim. The new Postgres entities (Agent/AgentVersion/Suite/Case/Cluster/ClusterMember/GateRun) all carry `project_id` and index on it (AgentRun is ClickHouse-only and carries `project_id` on its spans). Redis multi-tenant isolation via `REDIS_KEY_PREFIX`. The GitHub App installation is bound to a `project_id` so a repo's GateRuns are tenant-scoped.

---

## 6. Component-by-component contrast with Langfuse

| Component | Langfuse | Tracely posture | Notes / file:line |
|---|---|---|---|
| `web` Next.js process | UI + ingestion + reads | **EXTENDED** | + cluster/suite/case/gate UI; + Tracely OTel attributes; + new REST resources |
| `worker` Express process | BullMQ consumers | **EXTENDED** | + Derive and Eval/replay pools (new queues) |
| CI Gate Orchestrator | — | **NEW** | `tracely-gate`; GateRun state machine + GitHub check-runs |
| `processEventBatch` write path | S3-first → queue | **REUSED AS-IS** | `processEventBatch.ts:104-349` |
| `IngestionService` merge | read-then-merge LWW | **REUSED AS-IS** | `IngestionService/index.ts` |
| `ClickhouseWriter` | batch buffer + RMT | **REUSED AS-IS** | `ClickhouseWriter/index.ts` |
| OTLP ingestion + mapper | OpenInference/GenAI mappers | **REUSED AS-IS** (+ new attrs) | `OtelIngestionProcessor.ts`, `ObservationTypeMapper.ts:165-489` |
| `events_full` span table | OTel-shaped, metadata-string agent/turn | **EXTENDED** | + first-class `agent_id/agent_version_id/agent_run_id/conversation_id/turn_id/step_id` + `env` (gating axis) + typed edges + provenance (`evaluation_case_id/gate_run_id/failure_cluster_id`); drops `experiment_*`/`prompt_*` (`dev-tables.sh:137-281`) |
| `scores` table + addressing | trace/obs/session targets | **REUSED AS-IS** (+ semantic targets) | `scores.ts`, `0030`; add conv/turn/step/tool/run addressing |
| `TraceUpsert` eval trigger | trace-level, key=traceId | **EXTENDED** | → `AgentRunComplete`, key=agentRunId, 30s debounce (`traceUpsert.ts:80`) |
| `createEvalJobs` spine | config-fetch + filter, single-obs extractor | **EXTENDED** | reuse PENDING-job spine (`evalService.ts:180-389`); replace single-obs variable extractor with trajectory extractor |
| `completeEvalExecution` | deterministic score write | **REUSED AS-IS** | `evalCompletion.ts:21`; add `verdict` for gate semantics |
| `JobConfiguration`/`JobExecution` | eval plumbing | **REUSED** (+ verdict, + agent-run inputs) | `schema.prisma:977-1051`; add `jobInputAgentRunId` |
| Dataset/DatasetItem/Run pillar | dataset-first eval | **REPLACED** | by EvaluationSuite/EvaluationCase derived from production failures |
| `WebhookQueue` + GitHub dispatch | repository_dispatch + HMAC | **REUSED AS-IS** | `webhooks.ts:486-570` — literal "→ CI gate" edge |
| `WorkerManager`/sharding/overflow | BullMQ skeleton | **REUSED AS-IS** | `workerManager.ts`, `ingestionQueue.ts:108-133`, `sharding.ts:9-20` |
| Postgres registry | orgs/projects/auth/configs | **EXTENDED** | + Agent/Version/Suite/Case/Cluster/ClusterMember/GateRun/GateCase (AgentRun is CH-only) |
| pgvector | — | **NEW** | failure embeddings for clustering |
| S3 prefixes | `events/`, `media/`, `exports/` | **EXTENDED** | + `fixtures/<proj>/<caseId>/…` for hermetic replay |
| Dataset/experiment queues | DatasetRunItemUpsert, ExperimentCreate | **DROPPED** | dataset-first model Tracely rejects |
| Cloud billing/integration queues | PostHog/Mixpanel/Stripe/metering | **DROPPED** | not on-thesis |

### 3.3 New BullMQ queues (added to `QueueName` enum)

```ts
// EXTENDED enum — Tracely additions (reuse all queue primitives)
AgentRunComplete   = "agent-run-complete-queue"   // EXTENDED TraceUpsert; key=projectId-agentRunId
FailureDetectQueue = "failure-detect-queue"        // NEW: deterministic + online failure signals
ClusteringQueue    = "clustering-queue"            // NEW: nightly cron-singleton BERTopic batch
RcaQueue           = "rca-queue"                    // NEW: first-failing-step + LLM RCA agent
TestGenQueue       = "test-gen-queue"              // NEW: failing trace → candidate EvaluationCase
GateRunQueue       = "gate-run-queue"             // NEW: orchestrate a GateRun (select suites, fan out, decide)
ReplayQueue        = "replay-queue"               // NEW: per-case hermetic replay vs an AgentVersion → GateCase
// REUSED as-is: IngestionQueue, OtelIngestionQueue (+secondaries), EvaluationExecution,
//               LLMAsJudgeExecution, CodeEvalExecution, WebhookQueue
```

`ReplayQueue` payload (typed in `TQueueJobTypes`, EXTENDED): `{ projectId, gateRunId, caseId, agentVersionId, fixtureBundleKey }`. `AgentRunComplete` payload: `{ projectId, agentRunId, conversationId?, rootTraceId }`.

---

## 7. Cross-cutting concerns (reused)

- **Idempotency / out-of-order / partial-update.** All inherited from the event-sourced write path: re-list+re-merge S3 → identical merged row → `ReplacingMergeTree` collapse; immutable keys pinned; deterministic SHA-256 sampling; "recently-processed" Redis cache (Part 1 doc 05 §9). Tracely's replays and eval scores use the same deterministic-id pattern (`uuidv5`, `evalScoreIds.ts`) so re-runs are idempotent.
- **Replay/recompute as a product surface.** **[Synthesis]** Langfuse's S3→ClickHouse rebuild is a maintenance script; Tracely promotes it to a first-class capability — "recompute evals/metrics over trace range X" and "promote production trace → regression case" are core APIs because *that is the product* (Part 1 doc 05 §10). The durable event log already supports it.
- **DLQ.** Reuse `getFailed()`/`retry()` (`dlqRetryService.ts`). **[Synthesis]** Add Tracely's new compute queues (`ReplayQueue`, `TestGenQueue`) to a typed DLQ with a per-failure-cluster replay UI — failed regression runs are themselves signal.
- **Distributed tracing of Tracely itself.** Reuse the BullMQ producer→consumer span linkage (`useProducerSpanAsConsumerParent: true`, `instrumentation.ts:68`); evals are themselves traced via `execution_trace_id = createW3CTraceId(jobExecutionId)` (`evalService.ts:860`) — so a GateRun's replays + judge calls are observable in Tracely's own trace explorer.
- **Graceful shutdown.** Reuse the exact ordering (`shutdown.ts:22-86`): stop workers → **flush `ClickhouseWriter`** → disconnect Redis/Prisma/ClickHouse. Critical so buffered spans/scores aren't lost on deploy.

---

## 8. Assumptions sibling docs MUST honor

1. **Storage stack is fixed**: Postgres (+pgvector), ClickHouse (one wide `events_full` span table + `scores`), Redis+BullMQ, S3. No alternative stores. The span table is `ReplacingMergeTree(event_ts, is_deleted)` modeled on Langfuse `events_full`.
2. **First-class semantic columns** on `events_full`: `agent_id, agent_version_id, agent_run_id, conversation_id, turn_id, turn_index, step_id, step_name, env, tool_call_id, caller_agent_id, callee_agent_id, edge_type` plus provenance `evaluation_case_id, gate_run_id, failure_cluster_id`. `env {prod,staging,ci,dev}` is the gating axis. Agent/Conversation/Turn/Step are NOT metadata strings. The storage/data-model doc owns the full DDL; these names are load-bearing.
3. **Canonical entity → store mapping**: Agent/AgentVersion/EvaluationSuite/EvaluationCase/FailureCluster/ClusterMember/GateRun/GateCase live in **Postgres**; AgentRun (the root/`is_app_root` span) plus spans (Trace/Conversation/Turn/Step/ToolCall/LLMCall/SubAgentCall) and Score live in **ClickHouse**; fixtures + raw blobs in **S3**; failure embeddings on **pgvector** (a column on `ClusterMember`).
4. **EvaluationCase = captured input/prefix + S3 fixture bundle (hermetic) + reference trajectory + match mode (agentevals taxonomy) + optional G-Eval rubric + FAIL-TO-PASS contract + provenance** (`source_trace_id`, `failure_cluster_id`, `agent_version_first_failed`). The eval doc must use these field names.
5. **Eval trigger is `AgentRunComplete`** (extends `TraceUpsert`), keyed `projectId-agentRunId`, 30s debounce. Online evals reuse the `createEvalJobs → JobExecution(PENDING) → EvaluationExecution` spine with a trajectory-shaped extractor.
6. **CI gate = `tracely-gate` (new service) + `ReplayQueue` (workers) + GitHub App/Action + reused webhook dispatch.** GateRun state lives in Postgres; verdicts honor FAIL-TO-PASS.
7. **OTLP/OpenInference is the wire protocol**; the SDK is a thin OTel wrapper emitting Tracely semantic attributes. No proprietary ingestion protocol.
8. **Multi-tenancy via `project_id`** on every row/path; it leads every ClickHouse key.
