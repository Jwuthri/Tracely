# DOC 07 — Failure Intelligence

> **Spine position:** `Production Trace → [Failure Detection → Cluster → Root-Cause → Suggest Fix → Auto-Generate Regression Test] → CI/CD Gate`. This document owns the bracketed middle. The trace is the **source of truth**; every artifact here — a detected failure, a cluster, an RCA hypothesis, a suggested fix, a candidate `EvaluationCase` — is **derived from the trace**.
>
> **Grounding:** heavily built on `91-techniques-references.md` (TRAJECT-Bench, MAST, BERTopic, Drain3, MinHash-LSH, LIBRO/Issue2Test/BRMiner, first-failing-step RCA) and the verified Langfuse facts in `92-langfuse-verified-facts.md`. When we say "reuse this," we cite the Langfuse `file:line` from the verified-facts pack. `[Synthesis]` marks author opinion.
>
> **Canonical entities used verbatim:** Agent, AgentVersion, AgentRun, Trace, Conversation, Turn, Step, ToolCall, LLMCall, SubAgentCall, EvaluationSuite, EvaluationCase, FailureCluster, Score, GateRun. This doc **defines** `FailureCluster` and the `EvaluationCase` *provenance/draft* fields; sibling docs (06 eval-model, 08 gate) must honor those columns.

---

## 0. TL;DR & decisions

1. **Detection is multi-signal, not just `level=ERROR`.** We enumerate 7 signal classes (span error, failed online-eval verdict, trajectory anomaly per TRAJECT-Bench, tool error, latency/cost blowup, explicit negative user feedback, novel-cluster membership). Each produces a `FailureSignal` row keyed to a span. `[Synthesis]`
2. **Detection reuses the `TraceUpsert` trigger verbatim** (`92:783`, `IngestionService/index.ts:710-734`), with the producer-side **30s debounce** kept (`traceUpsert.ts:80`) so a multi-turn / multi-agent trace is fully assembled before we judge its trajectory. Sharding key becomes `projectId-conversationId` (fallback `agentRunId`). `[Synthesis from 92 REUSE notes]`
3. **Clustering is two-stage.** Ingest-time: **Drain3 `template_id` + MinHash-LSH dedup** → cheap online grouping + occurrence counting (`91 §2.2, §2.4`). Batch (nightly): **embeddings → UMAP → HDBSCAN → c-TF-IDF labels** = BERTopic (`91 §2.1`). HDBSCAN **noise = novel-failure candidates** (`91 §2.6`). Embeddings live in **pgvector**.
4. **RCA v1 = first-failing-step localization on the span tree + an LLM RCA agent** that reads the localized sub-trace and emits a hypothesis **citing a `span_id`** (`91 §3.1`). MAST distribution prioritizes where to look in multi-agent traces.
5. **Test-gen = understand → generate → validate (fail-to-pass) → refine** (LIBRO / Issue2Test, `91 §3.2`), mining exact inputs/tool-args from the failing trace (BRMiner). Output is a **human-confirmed draft** `EvaluationCase`, never auto-promoted.
6. **Two product versions.** **V1** inputs = traces + prompts + tool schemas + tool outputs + agent graph. **V2** adds the **customer codebase** (span→source mapping via stack frames / tool bindings → concrete code diffs). §9 is explicit about what each can and cannot do.
7. **Human stays in the loop** for cluster labels (open/axial coding, `91 §2.5`) and for promoting a draft `EvaluationCase` into an `EvaluationSuite`.

---

## 1. Pipeline overview (mermaid DAG)

```mermaid
flowchart TD
    subgraph Ingest["Ingestion (reused verbatim from Langfuse)"]
      OTLP["SDK / OTLP spans"] --> S3[("S3 raw blobs")]
      S3 --> ING["ingestion-queue (sharded)"]
      ING --> EF[("ClickHouse events_full<br/>ReplacingMergeTree(event_ts,is_deleted)")]
      EF --> TU["trace-upsert (sharded by projectId-conversationId)<br/>30s debounce"]
    end

    TU -->|AgentRunComplete| Q1["fi-detect-queue"]

    subgraph FI["Failure Intelligence (this doc)"]
      Q1 -->|FailureSignal[]| DET{any signal<br/>fires?}
      DET -- no --> END1["no-op (healthy trace)"]
      DET -- yes --> Q2["fi-cluster-online-queue"]

      Q2 -->|Drain3 template_id<br/>+ MinHash-LSH dedup| FC[("Postgres FailureCluster<br/>+ pgvector embeddings")]
      FC -->|occurrence++ / first_seen / last_seen| Q3["fi-rca-queue"]

      Q3 -->|first-failing-step localize<br/>+ LLM RCA agent| RCA["RootCauseHypothesis<br/>(cites span_id, MAST bucket)"]
      RCA --> Q4["fi-suggest-fix-queue"]
      Q4 --> FIX["SuggestedFix (V1: prompt/schema/graph;<br/>V2: code diff)"]
      FIX --> Q5["fi-testgen-queue"]

      Q5 -->|understand→generate→validate→refine| TG["candidate EvaluationCase (DRAFT)"]
      TG -->|fail-to-pass replay| VAL{fails on<br/>failing version?}
      VAL -- no --> SHELVE["mark draft 'unreproducible'"]
      VAL -- yes --> DRAFT[("EvaluationCase status=DRAFT")]
    end

    subgraph Batch["Nightly batch (fi-cluster-batch-queue)"]
      EMB["sentence-embeddings"] --> UMAP --> HDB["HDBSCAN"] --> CTFIDF["c-TF-IDF labels"]
      HDB -->|noise points| NOVEL["novel-failure surfacing"]
      CTFIDF --> FC
    end
    FC -.nightly re-embed.-> EMB

    subgraph Human["Human-in-the-loop"]
      FC --> REVIEW["open/axial coding:<br/>confirm label + MAST bucket"]
      DRAFT --> PROMOTE["confirm → add to EvaluationSuite"]
    end
    PROMOTE --> SUITE[("EvaluationSuite → GateRun (doc 08)")]
```

`[Synthesis]` The whole pipeline is a chain of small BullMQ workers (§3–§8), each reading the previous stage's output from Postgres/ClickHouse and writing the next. This mirrors Langfuse's "separate queue = separate worker pool, no noisy-neighbor starvation" principle (`09-queue-worker.md:138`).

---

## 2. Entity schemas

### 2.1 `FailureCluster` (Postgres — registry/OLTP)

`[Synthesis]` Clusters are **registry state** (mutable, human-curated labels, occurrence counters) → Postgres, not ClickHouse. The cluster *members* (which spans belong to it) are addressed by `(trace_id, span_id)` into `events_full`; we do **not** copy span bodies into Postgres. Embeddings go in a pgvector column for ANN lookup at detect-time ("is this the same failure we've seen?").

```prisma
// packages/shared/prisma/schema.prisma  (Tracely additions)

model FailureCluster {
  id                String   @id @default(cuid())
  projectId         String   @map("project_id")
  agentId           String?  @map("agent_id")            // null = cross-agent cluster

  // ---- Identity / dedup keys (ingest-time, cheap) ----
  clusterKey        String   @map("cluster_key")         // derived: drainTemplateId + ':' + (bertopicTopicId ?? 'none') — the natural key (canonical: 00-canonical-decisions.md §2/§8)
  drainTemplateId   String   @map("drain_template_id")   // Drain3 fixed-depth-tree template
  drainTemplate     String   @map("drain_template") @db.Text // the "<*>"-masked template string
  minhashSignature  Bytes    @map("minhash_signature")   // 128-perm MinHash (datasketch-compatible)

  // ---- Semantic clustering (batch, BERTopic) ----
  bertopicTopicId   Int?     @map("bertopic_topic_id")   // -1 == HDBSCAN noise (novel candidate)
  centroidEmbedding Unsupported("vector(1024)")? @map("centroid_embedding") // pgvector
  medoidTraceId     String?  @map("medoid_trace_id")     // representative trace (closest to centroid)
  medoidSpanId      String?  @map("medoid_span_id")

  // ---- Human-curated labels (open/axial coding) ----
  label             String?                              // null until a human (or LLM-proposed) names it
  labelSource       LabelSource @default(UNLABELED)      // UNLABELED | LLM_PROPOSED | HUMAN_CONFIRMED
  mastBucket        MastBucket?                          // SPEC_DESIGN | INTER_AGENT | TASK_VERIFICATION
  trajectBenchMode  TrajectBenchMode?                    // 4 tool-failure modes (nullable)
  signalClasses     FailureSignalClass[] @default([])    // which detectors contributed

  // ---- Counters / lifecycle ----
  occurrenceCount   Int      @default(1) @map("occurrence_count")
  distinctTraceCount Int     @default(1) @map("distinct_trace_count")
  firstSeen         DateTime @map("first_seen")
  lastSeen          DateTime @map("last_seen")
  agentVersionFirstFailed String? @map("agent_version_first_failed") // FK-by-id to AgentVersion (no DB FK; ClickHouse-addressed)
  status            ClusterStatus @default(OPEN)         // OPEN | PROMOTED | IGNORED | MERGED (canonical: 00-canonical-decisions.md §3)

  // ---- Derived artifacts (1:1 latest) ----
  rootCauseHypothesis Json?  @map("root_cause_hypothesis") // RootCauseHypothesis (§5)
  suggestedFix        Json?  @map("suggested_fix")         // SuggestedFix (§6)

  members           ClusterMember[]
  evaluationCases   EvaluationCase[]                       // tests drafted/promoted from this cluster

  createdAt         DateTime @default(now()) @map("created_at")
  updatedAt         DateTime @updatedAt @map("updated_at")

  @@unique([projectId, agentId, clusterKey])           // canonical key; clusterKey derived from drainTemplateId + bertopicTopicId (00-canonical-decisions.md §2/§8)
  @@index([projectId, status])
  @@index([projectId, lastSeen])
  // pgvector ANN index created out-of-band (Prisma can't express ivfflat/hnsw):
  //   CREATE INDEX ON "FailureCluster" USING hnsw (centroid_embedding vector_cosine_ops);
}

model ClusterMember {
  id           String   @id @default(cuid())
  projectId    String   @map("project_id")
  clusterId    String   @map("cluster_id")
  traceId      String   @map("trace_id")           // → events_full.trace_id (ClickHouse)
  spanId       String   @map("span_id")            // → events_full.span_id (the first-failing span)
  agentRunId   String?  @map("agent_run_id")
  conversationId String? @map("conversation_id")
  isMedoid     Boolean  @default(false) @map("is_medoid")
  isDiverseVariant Boolean @default(false) @map("is_diverse_variant") // k-center-greedy pick
  distanceToCentroid Float? @map("distance_to_centroid")
  embedding    Unsupported("vector(1024)")? @map("embedding") // pgvector — the canonical per-member embedding store (00-canonical-decisions.md §6; one store, no separate FailureEmbedding table)
  occurredAt   DateTime @map("occurred_at")
  cluster      FailureCluster @relation(fields: [clusterId], references: [id], onDelete: Cascade)

  @@unique([clusterId, traceId, spanId])
  @@index([projectId, traceId])
  // pgvector ANN index created out-of-band (Prisma can't express hnsw):
  //   CREATE INDEX ON "ClusterMember" USING hnsw (embedding vector_cosine_ops);
}

enum LabelSource        { UNLABELED LLM_PROPOSED HUMAN_CONFIRMED }
enum MastBucket         { SPEC_DESIGN INTER_AGENT TASK_VERIFICATION } // 92 prior: ~42% / ~37% / ~21%
enum TrajectBenchMode   { SIMILAR_TOOL_CONFUSION PARAMETER_BLIND REDUNDANT_CALL INTENT_MISINTERPRET }
// ClusterStatus is canonical (00-canonical-decisions.md §3). The §10 HITL flow's finer lifecycle
// maps onto these values: TRIAGED→OPEN (with label set), TEST_DRAFTED/TEST_PROMOTED→PROMOTED,
// RESOLVED→IGNORED, dedup-merge→MERGED.
enum ClusterStatus      { OPEN PROMOTED IGNORED MERGED }
enum FailureSignalClass { SPAN_ERROR ONLINE_EVAL_FAIL TRAJECTORY_ANOMALY TOOL_ERROR LATENCY_BLOWUP COST_BLOWUP NEGATIVE_FEEDBACK NOVEL }
```

### 2.2 `FailureSignal` (ClickHouse — OLAP, immutable, one row per detected signal)

`[Synthesis]` Detection output is high-volume and append-only → ClickHouse, same engine family as `events_full` (`92:177`). One signal = one (trace, span, detector) tuple. This becomes the analytic substrate for "how many traces failed on detector X this week" and feeds the clustering input.

> **Schema-of-record note:** the `failure_signals` DDL below is the canonical definition; `09-database-schema.md` ports it **verbatim** into the ClickHouse inventory (00-canonical-decisions.md §8). The fenced block is self-contained and copy-pasteable as-is.

```sql
-- migration 0040_failure_signals.up.sql  (Tracely, modeled on scores/events_full DDL)
-- ===== BEGIN failure_signals (canonical DDL — copy verbatim into 09-database-schema.md) =====
CREATE TABLE failure_signals
(
    project_id        String,
    trace_id          String,
    span_id           String,                       -- the span that triggered the signal
    parent_span_id    String,
    agent_id          String,
    agent_version_id  String,
    agent_run_id      String,
    conversation_id   String,
    turn_id           String,
    step_id           String,

    signal_class      LowCardinality(String),       -- FailureSignalClass enum string
    detector_name     LowCardinality(String),       -- e.g. "span_level_error", "trajectory.unordered_mismatch"
    severity          LowCardinality(String),       -- INFO | WARN | ERROR | CRITICAL
    -- normalized free-text used by Drain3 + embeddings (status_message, tool error, judge reasoning…)
    failure_text      String CODEC(ZSTD(3)),
    -- structured detail (e.g. {expected_tool, actual_tool, latency_ms, cost_usd, score_name, verdict})
    detail            String CODEC(ZSTD(3)),        -- JSON
    online_score_id   String,                       -- if produced by a Score verdict (links to scores.id)

    -- dedup/version columns (same pattern as events_full)
    event_ts          DateTime64(6),
    is_deleted        UInt8,
    created_at        DateTime64(6) DEFAULT now(),
    INDEX idx_trace_id trace_id   TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_run_id   agent_run_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_signal_class signal_class TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_fts_failure lower(failure_text) TYPE text(tokenizer = splitByNonAlpha)
)
ENGINE = ReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(created_at)
PRIMARY KEY (project_id, toStartOfMinute(created_at), xxHash32(trace_id))
ORDER BY    (project_id, toStartOfMinute(created_at), xxHash32(trace_id), span_id, detector_name);
-- ===== END failure_signals =====
```

Read with `LIMIT 1 BY (trace_id, span_id, detector_name) ORDER BY event_ts DESC` to dedup, the manual-dedup pattern Langfuse uses to keep skip-indexes usable (`92:432`).

### 2.3 `EvaluationCase` — provenance & draft fields (owned here; full shape in doc 06)

`[Synthesis]` Doc 06 owns the *executable* parts of `EvaluationCase` (fixtures, reference trajectory, match mode, judge rubric, fail-to-pass contract). **This doc defines the provenance/draft lifecycle fields that the test-gen stage writes**, and which doc 06 / doc 08 must read.

```prisma
// Fields THIS doc contributes to the EvaluationCase model (doc 06 owns the rest):
model EvaluationCase {
  // ... (fixtures, referenceTrajectory, trajectoryMatchMode, toolArgsMatchMode, judgeRubric — doc 06) ...

  // ---- Provenance (mined by the test-gen stage) ----
  sourceTraceId            String  @map("source_trace_id")     // the failing trace this was born from
  sourceSpanId             String? @map("source_span_id")      // first-failing span
  failureClusterId         String? @map("failure_cluster_id")
  agentVersionFirstFailed  String  @map("agent_version_first_failed")

  // ---- Draft lifecycle ----
  status                   CaseStatus @default(DRAFT)          // DRAFT | PROMOTED | QUARANTINED | ARCHIVED | UNREPRODUCIBLE
  failToPassValidated      Boolean @default(false) @map("fail_to_pass_validated")
  validationExecutionTraceId String? @map("validation_execution_trace_id") // the replay trace (self-traced)
  origin                   CaseOrigin @default(GENERATED)       // PROMOTED_CLUSTER | MANUAL | GENERATED
  createdBy                String? @map("created_by")          // author identity (user id / "system"); replaces GeneratedBy enum
  promotedByUserId         String? @map("promoted_by_user_id")
  promotedAt               DateTime? @map("promoted_at")

  failureCluster           FailureCluster? @relation(fields: [failureClusterId], references: [id])
}
// CaseStatus + CaseOrigin are canonical (00-canonical-decisions.md §3); drift map: ACTIVE→PROMOTED, MUTED→QUARANTINED, RETIRED→ARCHIVED; AUTODRAFT→GENERATED, HUMAN→MANUAL.
enum CaseStatus  { DRAFT PROMOTED QUARANTINED ARCHIVED UNREPRODUCIBLE }
enum CaseOrigin  { PROMOTED_CLUSTER MANUAL GENERATED }
```

> **Sibling contract (doc 06 & 08 must honor):** an `EvaluationCase` is only eligible for an `EvaluationSuite` / `GateRun` when `status = PROMOTED` **and** `failToPassValidated = true`. A `DRAFT` never gates a PR. The `Score` produced by running a case **reuses Langfuse score addressing** (`92:354`) plus `execution_trace_id` (`92:1080`) — evals are themselves traced.

---

## 3. Stage 1 — WATCH (reuse `TraceUpsert`)

**Reuse, do not rebuild.** Langfuse already fires `createEvalJobs` on every trace upsert (`92:783`, `IngestionService/index.ts:710-734`). Tracely renames the semantic to **`AgentRunComplete → run failure intelligence`** and adds a `sourceEventType = "agent-run-complete"` arm as the verified-facts pack recommends (`92:1078`).

Two changes from Langfuse, both `[Synthesis]` from `09-queue-worker.md:328`:

1. **Sharding/dedup key = `projectId-conversationId`** (fallback `projectId-agentRunId`), not `projectId-traceId`, so every Turn/Step of a multi-turn run lands on one shard and **one 30s debounce window** → we only run detection once the whole conversation/run is assembled.
2. **Keep the producer-side `delay: 30_000`** (`traceUpsert.ts:80`). Multi-agent traces with handoffs settle slowly; judging a half-written trajectory manufactures false failures.

```ts
// worker/src/queues/traceComplete.ts  (port of Langfuse trace-upsert)
export const traceCompleteProcessor = async (job: Job<AgentRunCompleteEvent>) => {
  const { projectId, conversationId, agentRunId, traceId } = job.data.payload;
  // infinite-loop guard, verbatim pattern from evalService.ts:243-253 (92:777):
  // skip traces whose environment startsWith "tracely-" (our own replay/judge traces)
  if (job.data.environment?.startsWith("tracely-")) return;
  await DetectQueue.getInstance({ shardingKey: `${projectId}-${conversationId ?? agentRunId}` })
    .add(QueueJobs.FiDetect, { payload: { projectId, traceId, conversationId, agentRunId } });
};
```

BullMQ definition (mirrors `traceUpsert.ts:76-85`, `92:1123` job-options):

```ts
new Queue<AgentRunCompleteEvent>(QueueName.AgentRunComplete, {
  defaultJobOptions: {
    attempts: env.TRACELY_TRACE_COMPLETE_ATTEMPTS ?? 2,
    delay: 30_000,                       // debounce: let the conversation settle
    removeOnComplete: 100,
    removeOnFail: 100_000,               // no native DLQ; kept in failed set (09:211)
    backoff: { type: "exponential", delay: 5_000 },
  },
});
```

---

## 4. Stage 2 — DETECT failures

`[Synthesis]` **A failure is any of 7 signal classes firing on any span of the trace.** Detection reads the assembled trace from `events_full` (root span via `parent_span_id='' OR is_app_root=true`, `92:435`) plus the trace's `scores` rows, and emits 0..N `FailureSignal` rows.

### 4.1 Signal catalog

| # | `FailureSignalClass` | Source columns / inputs | Detector logic |
|---|---|---|---|
| 1 | `SPAN_ERROR` | `events_full.level` (`ObservationLevel` enum, `92:214`), `status_message` | any span with `level='ERROR'` and non-empty `status_message`. Treat `''` and NULL the same (`92:86`). |
| 2 | `ONLINE_EVAL_FAIL` | `scores` where `source='EVAL'` (`92:222`), `value`/`string_value`, `comment` (judge reasoning) | a live judge/assertion verdict that fails its threshold/rubric. `failure_text = comment`, `online_score_id = scores.id`. |
| 3 | `TRAJECTORY_ANOMALY` | `tool_call_names Array(String)` (`92:120`), `tool_calls`, Step/Turn ordering, agent graph | TRAJECT-Bench modes (`91 §1.3`): similar-tool confusion, parameter-blind selection, redundant call, intent-misinterpret. Computed against the AgentVersion's declared tool schemas + (if present) a prior good reference trajectory. |
| 4 | `TOOL_ERROR` | `ToolCall` spans (`type='TOOL'`, `92:208`), their `output`/`status_message` | tool returned an error payload, threw, or violated its output schema. |
| 5 | `LATENCY_BLOWUP` | `start_time`/`end_time` (µs, `92:72`) per span; rolling p95 per (agent_version, span name) | span or whole-run duration > k·p95 baseline. Baseline computed in batch, cached in Redis. |
| 6 | `COST_BLOWUP` | `cost_details` / `calculated_total_cost` (`92:111`) | run cost > k·p95 baseline, or token-loop detected (same LLMCall repeated > N). |
| 7 | `NEGATIVE_FEEDBACK` | `scores` where `source='ANNOTATION'` or `'API'` with negative value/category | explicit thumbs-down / low rating / human correction attached to the trace, turn, or step. |
| (8) | `NOVEL` | assigned downstream by clustering when HDBSCAN returns topic `-1` (`91 §2.6`) | not a detector per se — a label promoted onto the cluster; surfaced separately. |

### 4.2 `FailureSignal` shape (TS)

```ts
interface FailureSignal {
  projectId: string;
  traceId: string; spanId: string; parentSpanId: string;
  agentId: string; agentVersionId: string; agentRunId: string;
  conversationId?: string; turnId?: string; stepId?: string;
  signalClass: FailureSignalClass;
  detectorName: string;                 // "span_level_error" | "trajectory.redundant_call" | ...
  severity: "INFO" | "WARN" | "ERROR" | "CRITICAL";
  failureText: string;                  // normalized, feeds Drain3 + embeddings
  detail: Record<string, unknown>;      // {expectedTool?, actualTool?, latencyMs?, costUsd?, scoreName?, verdict?}
  onlineScoreId?: string;
}
```

### 4.3 Worker

```ts
// worker/src/features/failure-intelligence/detect.ts
export const detectProcessor = async (job: Job<FiDetectEvent>) => {
  const { projectId, traceId, conversationId, agentRunId } = job.data.payload;
  const spans = await fetchTraceSpans(projectId, traceId);            // events_full, FINAL or LIMIT 1 BY
  const scores = await fetchTraceScores(projectId, traceId);          // scores table
  const agentVersion = await getAgentVersionForRun(agentRunId);       // Postgres registry
  const baselines = await getLatencyCostBaselines(projectId, agentVersion.id); // Redis cache

  const signals: FailureSignal[] = [
    ...detectSpanErrors(spans),
    ...detectOnlineEvalFails(scores),
    ...detectTrajectoryAnomalies(spans, agentVersion),               // TRAJECT-Bench modes
    ...detectToolErrors(spans),
    ...detectLatencyBlowups(spans, baselines),
    ...detectCostBlowups(spans, baselines),
    ...detectNegativeFeedback(scores),
  ];
  if (signals.length === 0) return;                                   // healthy trace, no-op
  await writeFailureSignals(signals);                                 // ClickHouseWriter (92:1116)
  // hand the worst (lowest-depth, highest-severity) signal to clustering
  const primary = pickPrimarySignal(signals);                        // first-failing-step heuristic (91 §3.1)
  await ClusterOnlineQueue.getInstance({ shardingKey: `${projectId}-${traceId}` })
    .add(QueueJobs.FiClusterOnline, { payload: { projectId, traceId, primarySignal: primary } });
};
```

`[Synthesis]` `pickPrimarySignal` applies the **first-failing-step rule** (`91 §3.1`) with the canonical tie-break (00-canonical-decisions.md §7.6): among signals, choose the one on the erroring span with **min depth (shallowest)**, then **min `start_time` (earliest)**, then **lexicographically smallest `span_id`**, because upstream errors cause downstream noise. For linked cross-service sub-agent runs, the child run's first-failing step rolls up to its `SubAgentCall` edge in the parent. That span becomes the cluster member and the RCA localization seed.

**BullMQ:** `fi-detect-queue` — sharded by `projectId-conversationId`; `attempts: 3`; `removeOnFail: 100_000`. Payload: `{ projectId, traceId, conversationId?, agentRunId? }`.

---

## 5. Stage 3 — CLUSTER (two-stage)

### 5.1 Online (ingest-time, cheap) — Drain3 + MinHash-LSH

`[Synthesis from 91 §2.2/§2.4/§2.6]` Per primary signal, at trace time:

1. **Normalize** `failure_text` (mask IDs/UUIDs/numbers/timestamps → `<*>`, the Drain3 preprocessing step).
2. **Drain3** `add_log_message(normalized)` → `template_id`. Drain3 is streaming, bounded-memory (LRU `max_clusters`), persisted to **Redis** (its native backend) — perfect for the ingest path (`91 §2.2`).
3. **MinHash-LSH** over `(template tokens + ordered tool_call_names + first-failing tool name)` → query LSH for an existing near-duplicate cluster (Jaccard ≥ τ). If found → that cluster; else new.
4. **Upsert `FailureCluster`**: bump `occurrenceCount`, `distinctTraceCount`, `lastSeen`; set `firstSeen`/`agentVersionFirstFailed` on create; append a `ClusterMember` for `(traceId, primarySpanId)`.

```ts
// worker/src/features/failure-intelligence/cluster-online.ts
export const clusterOnlineProcessor = async (job: Job<FiClusterOnlineEvent>) => {
  const { projectId, traceId, primarySignal } = job.data.payload;
  const norm = normalizeFailureText(primarySignal.failureText);                 // mask variables → <*>
  const { templateId, template } = await drain3.addLogMessage(projectId, norm); // Redis-persisted Drain3
  const sig = minhash([...tokenize(template), ...primarySignal.detail.toolSeq ?? []]);
  const existing = await lshQuery(projectId, sig, /*jaccard*/ 0.8);             // datasketch-style LSH

  const cluster = await upsertFailureCluster({
    projectId, agentId: primarySignal.agentId, drainTemplateId: templateId, drainTemplate: template,
    minhashSignature: sig, existingClusterId: existing?.id,
    member: { traceId, spanId: primarySignal.spanId, occurredAt: new Date(),
              agentRunId: primarySignal.agentRunId, conversationId: primarySignal.conversationId },
    signalClass: primarySignal.signalClass,
    agentVersionFirstFailed: primarySignal.agentVersionId,
  });

  // only kick RCA the FIRST time a cluster is seen (or when re-opened) — dedup by status
  if (cluster.justCreated || cluster.status === "OPEN") {
    await RcaQueue.getInstance().add(QueueJobs.FiRca, { payload: { projectId, clusterId: cluster.id } });
  }
};
```

`[Synthesis]` The "kick RCA only on first sighting" guard mirrors Langfuse's dedup of `JobExecution` creation (`92:793`) — we don't re-RCA the same cluster on every recurrence; we just increment counters.

**BullMQ:** `fi-cluster-online-queue` — sharded by `projectId-traceId`; `attempts: 5`; idempotent on `(clusterId, traceId, spanId)` via the `@@unique` on `ClusterMember`.

### 5.2 Batch (nightly, high quality) — BERTopic

`[Synthesis from 91 §2.1/§2.3]` A cron-scheduled scheduler→processing pair (Langfuse's "dual-queue cron," `09-queue-worker.md:89`) re-clusters the last N days of `FailureSignal` per project:

```
fi-cluster-batch-scheduler (repeat cron 03:00, concurrency 1)
   → for each active project: enqueue onto fi-cluster-batch-queue
fi-cluster-batch-queue (concurrency 2, rate-limited):
   1. pull distinct failure_text for project window from failure_signals (ClickHouse)
   2. embed (sentence-transformers, 1024-d) → write/refresh pgvector
   3. UMAP reduce (high-dim cosine is uninformative — 91 §2.1)
   4. HDBSCAN cluster (no k, variable density, noise=-1)
   5. c-TF-IDF → propose label per topic (labelSource = LLM_PROPOSED after LLM rewrite)
   6. reconcile: map BERTopic topics onto existing online FailureClusters by member overlap;
      set bertopicTopicId, centroidEmbedding, medoid (closest-to-centroid, 91 §2.5),
      and 2-3 diverse variants via k-center-greedy (isDiverseVariant=true)
   7. topic == -1 → mark members' clusters signalClass NOVEL → surface in "novel failures" view
```

`[Synthesis]` **Watch HDBSCAN memory past ~hundreds-of-thousands of points** (`91 §2.1` cites OOM ~500k). Mitigations: always UMAP first; cluster on **deduped templates** (Drain3 already collapsed near-dups) not raw rows; cap the window; consider GPU HDBSCAN later. Online clusters give continuity; the nightly pass gives stable boundaries + good labels.

**Representative selection (both stages feed this):** medoid = closest to centroid (`91 §2.5`); plus 2–3 **diverse boundary cases** via k-center-greedy so a human reviewer sees the typical failure *and* its variants before promoting to a test.

---

## 6. Stage 4 — ROOT-CAUSE (first-failing-step + LLM RCA agent)

`[Synthesis from 91 §3.1]` **The span tree IS the causal graph** — don't reinvent micro-service causal inference. RCA v1 has two steps.

### 6.1 Deterministic localization

```ts
// the trace's span tree already encodes parent→child causality (trace_id/span_id/parent_span_id)
function localizeFirstFailingStep(spans: Span[]): { rootSpan: Span; subtree: Span[] } {
  const failing = spans.filter(isErroring);                  // level=ERROR | tool error | failed verdict
  // canonical tie-break (00-canonical-decisions.md §7.6): min depth (shallowest),
  // then min start_time (earliest), then lexicographically smallest span_id.
  const earliest = minBy(failing, s => [depth(s), s.start_time, s.span_id]);
  return { rootSpan: earliest, subtree: descendantsOf(earliest, spans) };
}
// Cross-service sub-agent runs: a linked child run's first-failing step rolls up to its
// SubAgentCall edge in the parent run (the child does not win over the parent's own edge).
// (00-canonical-decisions.md §7.6)
```

### 6.2 LLM RCA agent

Reads **only the localized sub-trace** (token-bounded: the first-failing span + its parent + its descendants + the relevant LLMCall I/O and ToolCall args/results). Emits a structured hypothesis that **must cite a `span_id`**. MAST distribution (`92` prior: spec/design ~42%, inter-agent ~37%, task-verification ~21%) is injected as a prior to bias the bucket.

```ts
interface RootCauseHypothesis {
  clusterId: string;
  citedSpanId: string;                 // REQUIRED — the span the hypothesis blames
  mastBucket: "SPEC_DESIGN" | "INTER_AGENT" | "TASK_VERIFICATION";
  trajectBenchMode?: TrajectBenchMode; // if a tool-failure mode applies
  hypothesis: string;                  // human-readable, e.g. "planner emitted search() with empty query…"
  confidence: number;                  // 0..1
  evidenceSpanIds: string[];           // supporting spans
  executionTraceId: string;            // the RCA agent run is itself traced (92:1080)
}
```

This RCA agent is **itself a traced Tracely agent** running in environment `tracely-rca` (so the §3 infinite-loop guard skips it). Reuse `executionTraceId = createW3CTraceId(jobExecutionId)` (`92:779`).

**BullMQ:** `fi-rca-queue` — `attempts: 3`; LLM-rate-limit handling via the **24h self-requeue + `RetryBaggage`** pattern (`09-queue-worker.md:330`, `92:1111`), not BullMQ attempts, because the RCA agent makes LLM calls.

Output written to `FailureCluster.rootCauseHypothesis` (Json), then enqueue `fi-suggest-fix`.

---

## 7. Stage 5 — SUGGEST FIX

`[Synthesis]` The suggested fix is conditioned on the RCA hypothesis and the **product version** (§9). Stored on `FailureCluster.suggestedFix`. Framed as a recommendation for a human, never auto-applied.

```ts
interface SuggestedFix {
  clusterId: string;
  version: "V1" | "V2";
  kind: SuggestedFixKind;              // see table below
  rationale: string;                   // ties back to RootCauseHypothesis.citedSpanId
  // V1 artifacts:
  promptPatch?: { agentVersionId: string; before: string; after: string; targetMessageRole: string };
  toolSchemaPatch?: { toolName: string; jsonSchemaDiff: object };  // tighten args, add enum, etc.
  graphPatch?: { description: string };                            // "add verification node after planner"
  // V2 artifacts (codebase available):
  codeDiff?: { filePath: string; unifiedDiff: string; confidence: number };
  confidence: number;
  executionTraceId: string;
}
enum SuggestedFixKind {
  PROMPT_EDIT, TOOL_SCHEMA_TIGHTEN, ADD_GUARDRAIL, ADD_VERIFICATION_STEP,
  REORDER_TRAJECTORY, RETRY_POLICY, CODE_DIFF
}
```

| MAST bucket | Typical V1 fix kind | Typical V2 fix kind |
|---|---|---|
| `SPEC_DESIGN` (~42%) | `PROMPT_EDIT`, `TOOL_SCHEMA_TIGHTEN` | `CODE_DIFF` to prompt template / tool binding |
| `INTER_AGENT` (~37%) | `ADD_VERIFICATION_STEP`, `REORDER_TRAJECTORY`, graph patch | `CODE_DIFF` to orchestration / handoff code |
| `TASK_VERIFICATION` (~21%) | `ADD_GUARDRAIL`, `RETRY_POLICY` | `CODE_DIFF` to the verifier / assertion |

**BullMQ:** `fi-suggest-fix-queue` — `attempts: 3`; LLM 24h self-requeue. On completion, enqueue `fi-testgen`.

---

## 8. Stage 6 — AUTO-GENERATE a candidate regression test

`[Synthesis from 91 §3.2]` The payoff stage. **understand → generate → validate (fail-to-pass) → refine**, mining exact inputs/tool-args from the failing trace (BRMiner). Output is a **DRAFT `EvaluationCase`**, surfaced for human confirmation — never auto-promoted.

### 8.1 Algorithm

```
1. UNDERSTAND  — read the failing trace + RootCauseHypothesis + cluster medoid.
                 Extract: the input prefix (the Turn/Step that led to failure),
                 the agent graph slice, the reference (good) trajectory if one exists.
2. MINE (BRMiner-analog) — pull EXACT values straight from events_full:
                 - tool args from tool_calls[] (92:661), tool outputs to record as FIXTURES,
                 - LLMCall inputs/outputs (optionally recorded as fixtures for hermetic replay),
                 - turn ordering, handoff edges.
3. GENERATE    — synthesize EvaluationCase:
                 input/prefix + recorded fixtures + reference trajectory
                 + trajectory match mode (agentevals: strict|unordered|subset|superset; default UNORDERED — 91 §1.5)
                 + tool_args match mode (exact|ignore|subset|superset)
                 + optional LLM-judge rubric (G-Eval CoT + bias mitigations) for free-text turns.
4. VALIDATE    — fail-to-pass contract (91 §3.2): replay the case against agentVersionFirstFailed.
                 MUST fail. If it does NOT fail → status=UNREPRODUCIBLE, shelve.
                 (We cannot assert "passes on the fix" yet — the fix is a suggestion, not deployed.)
5. REFINE      — if the replay errored for the wrong reason (flaky/env), feed execution output back
                 to the generator (LIBRO/Issue2Test loop), bounded to N=2 revisions.
6. PERSIST     — EvaluationCase status=DRAFT, failToPassValidated=true,
                 validationExecutionTraceId set, failureClusterId linked.
```

### 8.2 Worker

```ts
// worker/src/features/failure-intelligence/testgen.ts
export const testgenProcessor = async (job: Job<FiTestgenEvent>) => {
  const { projectId, clusterId } = job.data.payload;
  const cluster = await getFailureCluster(clusterId);                  // medoid + RCA + fix
  const trace = await fetchTraceSpans(projectId, cluster.medoidTraceId!);

  const mined = mineInputsAndFixtures(trace, cluster.medoidSpanId!);   // BRMiner-analog (92:661 tool_calls)
  let draft = synthesizeEvaluationCase({ cluster, mined,
    trajectoryMatchMode: "UNORDERED",   // default relaxed — Inclusion > EM (91 §1.5)
    toolArgsMatchMode: "subset" });

  for (let attempt = 0; attempt <= 2; attempt++) {                     // refine loop (Issue2Test)
    const replay = await replayAgainstVersion(draft, cluster.agentVersionFirstFailed!); // doc 06 replay engine
    if (replay.failed) {                                               // FAIL-TO-PASS satisfied on broken version
      return persistDraftCase({ ...draft, status: "DRAFT", failToPassValidated: true,
        validationExecutionTraceId: replay.executionTraceId,
        failureClusterId: clusterId, sourceTraceId: cluster.medoidTraceId,
        sourceSpanId: cluster.medoidSpanId, agentVersionFirstFailed: cluster.agentVersionFirstFailed });
    }
    if (replay.erroredForWrongReason && attempt < 2) { draft = refine(draft, replay); continue; }
    break;
  }
  await markClusterTestUnreproducible(clusterId);                      // status=UNREPRODUCIBLE
};
```

`[Synthesis]` **Expectations** (`91 §3.3`): SoTA reproduces ~30–33% of *text-issue* failures (Issue2Test 30.4%, LIBRO 33%). Tracely starts from a **full trace** (exact inputs, tool args, intermediate state) — strictly more signal — so auto-reproduction should be meaningfully higher. Still: **frame as a draft a human confirms**, not autonomous authoring. Promotion (`status=DRAFT → PROMOTED`) is a human click (§10), which is the only thing that makes a case gate-eligible (sibling contract, §2.3).

**BullMQ:** `fi-testgen-queue` — `attempts: 3`; the replay step uses doc 06's deterministic, fixture-driven hermetic replay; LLM steps use 24h self-requeue.

---

## 9. V1 vs V2 — capabilities (be explicit)

`[Synthesis]` Two product versions differ **only in inputs**, which gates how deep RCA and fixes can go.

### V1 — inputs: traces + prompts + tool schemas + tool outputs + agent graph

**Can do:**
- All detection signals (§4) — they need only the trace + scores.
- Full clustering (§5) — Drain3/MinHash + BERTopic on trace-derived text.
- RCA localization to a **span** + an LLM hypothesis citing that span + MAST bucket (§6). "The planner called `search()` with an empty `query`; the tool schema allows empty strings."
- Fixes that live in the **trace's own vocabulary**: `PROMPT_EDIT`, `TOOL_SCHEMA_TIGHTEN`, `ADD_GUARDRAIL`, `ADD_VERIFICATION_STEP`, `REORDER_TRAJECTORY`, `RETRY_POLICY`.
- **Full test generation** — inputs/tool-args/fixtures are all in the trace; fail-to-pass replay needs only the agent endpoint + recorded fixtures.

**Cannot do:**
- Point at a **line of source code** as the cause, or propose a **code diff**. It can say "the tool that validates X is too permissive," not "edit `validators/order.py:42`."
- Distinguish "the prompt is wrong" from "the code that *builds* the prompt is wrong" — both surface as a `PROMPT_EDIT` suggestion against the rendered prompt.
- Reason about exceptions thrown **inside** customer code that never reached a span (only what was instrumented is visible).

### V2 — also: the customer codebase

**Adds:**
- **Span→source mapping.** Two mechanisms: (a) **stack frames** captured on error spans (file:line) — map directly to source; (b) **tool bindings** — map a `ToolCall` span's tool name to the function/handler that implements it (registry/decorator metadata).
- **Concrete code diffs** (`SuggestedFixKind.CODE_DIFF`) with a unified diff + confidence, generated by a code-aware RCA/fix agent that reads the localized sub-trace **and** the mapped source.
- **Deeper RCA**: the hypothesis can blame a specific function, read its body, and explain the bug mechanistically ("`build_query()` drops the filter when `tags` is empty").
- **Better fail-to-pass**: with the codebase, we can run the *fixed* version locally to also assert the test **passes on the fix** (the full fail-to-pass contract, `91 §3.2`), not just fails on the broken one — making promoted tests stronger.

**Still cannot do (honest limits):**
- Fix bugs whose root cause is in a **third-party dependency** or an external service the codebase only calls.
- Guarantee a proposed diff compiles/passes the project's own tests without running them (so V2 diffs remain human-reviewed drafts).

> **Sibling contract:** V2's span→source mapping requires the SDK to optionally attach **stack frames on error spans** and **tool-binding metadata**. That is an *ingestion/SDK* concern (docs 02/05/11), flagged here so it isn't forgotten. V1 ships without it.

---

## 10. Human-in-the-loop (open/axial coding)

`[Synthesis from 91 §2.5]` Automation does the heavy lifting (clustering = axial grouping); humans own **labels** and **promotion**. Two touchpoints, both backed by `FailureCluster.status` transitions:

1. **Cluster triage / labeling.** UI lists clusters sorted by `occurrenceCount` × recency, each showing the **medoid + 2–3 diverse variants** (§5.2), the RCA hypothesis, and the LLM-proposed label. A human confirms/edits the `label`, sets `mastBucket` (the cluster stays `status=OPEN` during triage; or → `IGNORED`). `labelSource: LLM_PROPOSED → HUMAN_CONFIRMED`. The LLM only **proposes** names — it lacks the team's tribal knowledge (`91 §2.5`).
2. **Test promotion.** Once test-gen has produced a DRAFT `EvaluationCase`, the human reviews it (input/fixtures/reference trajectory/match mode/rubric), edits if needed, and clicks **Promote** → `EvaluationCase.status = PROMOTED`, `promotedByUserId` set, cluster `status → PROMOTED`, case added to an `EvaluationSuite`. Only now is it gate-eligible (§2.3, doc 08).

Status lifecycle (canonical `ClusterStatus = {OPEN, PROMOTED, IGNORED, MERGED}`, 00-canonical-decisions.md §3; the labels below the arrows are the human-workflow stages, not enum values):

```
OPEN ──triage (label + mastBucket)──▶ OPEN ──testgen ok + human promote──▶ PROMOTED
  │                                                  │
  └──ignore──▶ IGNORED            testgen fails──▶ (stays OPEN, case=UNREPRODUCIBLE)
deduped into another cluster ──▶ MERGED
PROMOTED ──fix deployed & gate green over time──▶ IGNORED (resolved)
```

---

## 11. BullMQ queue/job summary

`[Synthesis]` All new queues follow the Langfuse `WorkerManager.register` skeleton (`92:1112`): one dedicated Redis connection per queue, `metricWrapper`, enable-flag per queue, no native DLQ (failed set + cron retry, `09-queue-worker.md:211`). Add new `QueueName`/`QueueJobs` enum values alongside the existing 35 (`92:822`).

| Queue (`QueueName`) | Value | Trigger | Sharded by | Concurrency | Payload | Retry model |
|---|---|---|---|---|---|---|
| `AgentRunComplete` | `agent-run-complete` | reuse `TraceUpsert` (`92:783`) | `projectId-conversationId` | 25 | `{projectId, traceId, conversationId?, agentRunId?}` | BullMQ `attempts:2`, `delay:30_000` |
| `FiDetect` | `fi-detect-queue` | from `AgentRunComplete` | `projectId-conversationId` | 20 | `{projectId, traceId, conversationId?, agentRunId?}` | BullMQ `attempts:3` |
| `FiClusterOnline` | `fi-cluster-online-queue` | from `FiDetect` | `projectId-traceId` | 20 | `{projectId, traceId, primarySignal}` | BullMQ `attempts:5`, idempotent on member unique |
| `FiClusterBatchScheduler` | `fi-cluster-batch-scheduler` | cron 03:00 | — | 1 | `{}` | repeat cron |
| `FiClusterBatch` | `fi-cluster-batch-queue` | from scheduler | — | 2 (rate-limited) | `{projectId, windowDays}` | BullMQ `attempts:2` |
| `FiRca` | `fi-rca-queue` | from `FiClusterOnline` (first sighting) | — | 5 | `{projectId, clusterId}` | **24h self-requeue + RetryBaggage** (`92:1111`) |
| `FiSuggestFix` | `fi-suggest-fix-queue` | from `FiRca` | — | 5 | `{projectId, clusterId}` | 24h self-requeue |
| `FiTestgen` | `fi-testgen-queue` | from `FiSuggestFix` | — | 3 | `{projectId, clusterId}` | 24h self-requeue (LLM) + BullMQ for replay |

```ts
// packages/shared/src/server/queues.ts — additions (mirrors 92:822 enum)
export enum QueueName {
  // ... existing 35 ...
  AgentRunComplete           = "agent-run-complete",
  FiDetect                = "fi-detect-queue",
  FiClusterOnline         = "fi-cluster-online-queue",
  FiClusterBatchScheduler = "fi-cluster-batch-scheduler",
  FiClusterBatch          = "fi-cluster-batch-queue",
  FiRca                   = "fi-rca-queue",
  FiSuggestFix            = "fi-suggest-fix-queue",
  FiTestgen               = "fi-testgen-queue",
}
// Typed payloads added to TQueueJobTypes (92:1110), e.g.:
export const FiDetectEventSchema = z.object({
  payload: z.object({
    projectId: z.string(), traceId: z.string(),
    conversationId: z.string().nullish(), agentRunId: z.string().nullish(),
  }),
});
```

`[Synthesis]` LLM-driven stages (`FiRca`, `FiSuggestFix`, `FiTestgen`'s LLM calls) **reuse the 24h application-level rate-limit requeue** (`09-queue-worker.md:330`, `92:1111` `RetryBaggage`) rather than BullMQ `attempts`, because 429/5xx from the judge/RCA model are the common failure and should retry over a day with growing delay, decoupled from the attempt cap.

---

## 12. Worked example — one `FailureCluster`

`[Synthesis]` A realistic multi-agent cluster, end to end (whitespace compressed).

```json
{
  "id": "fc_8Qx2…", "projectId": "proj_acme", "agentId": "agent_support_orchestrator",
  "label": "Planner calls refund_tool with empty order_id after handoff from triage",
  "labelSource": "HUMAN_CONFIRMED", "mastBucket": "INTER_AGENT", "trajectBenchMode": "PARAMETER_BLIND",
  "signalClasses": ["TOOL_ERROR", "TRAJECTORY_ANOMALY"], "bertopicTopicId": 7,
  "drainTemplateId": "T-412", "drainTemplate": "ToolError refund_tool: order_id must be non-empty, got <*>",
  "occurrenceCount": 134, "distinctTraceCount": 121,
  "firstSeen": "2026-05-20T11:03:00Z", "lastSeen": "2026-06-02T08:41:00Z",
  "agentVersionFirstFailed": "agentver_3f1c (v12)", "status": "PROMOTED",

  "representatives": {
    "medoid": { "traceId": "tr_aa11", "spanId": "sp_refund_07", "summary": "triage→planner handoff; planner emits refund_tool(order_id='')" },
    "diverseVariants": [
      { "traceId": "tr_bb22", "spanId": "sp_refund_03", "summary": "order_id=null (not empty string)" },
      { "traceId": "tr_cc33", "spanId": "sp_refund_19", "summary": "order_id from wrong turn's context" } ] },

  "rootCauseHypothesis": {
    "citedSpanId": "sp_handoff_06", "confidence": 0.81, "executionTraceId": "tracely-rca:9b2e…",
    "evidenceSpanIds": ["sp_handoff_06", "sp_llm_planner_06", "sp_refund_07"],
    "hypothesis": "On triage→planner handoff (sp_handoff_06) order_id is dropped from shared state; planner then calls refund_tool by description, ignoring the missing required arg." },

  "suggestedFix": {
    "version": "V1", "kind": "TOOL_SCHEMA_TIGHTEN", "confidence": 0.74, "executionTraceId": "tracely-rca:9b2e…",
    "rationale": "order_id required but schema allows empty string; tighten to minLength:1 + add verification after handoff.",
    "toolSchemaPatch": { "toolName": "refund_tool", "jsonSchemaDiff": { "properties": { "order_id": { "minLength": 1 } }, "required": ["order_id"] } },
    "graphPatch": { "description": "Insert verification node after triage→planner handoff asserting order_id propagated." } },

  "candidateTest": {
    "evaluationCaseId": "ec_77aa", "status": "PROMOTED", "sourceTraceId": "tr_aa11", "sourceSpanId": "sp_refund_07",
    "failureClusterId": "fc_8Qx2…", "agentVersionFirstFailed": "agentver_3f1c (v12)",
    "input": { "conversationPrefix": [ { "role": "user", "content": "I want a refund for my last order" } ] },
    "fixtures": { "triage_lookup": { "order_id": "ORD-5582", "status": "delivered" } },
    "referenceTrajectory": ["triage_lookup", "handoff(triage→planner)", "refund_tool(order_id='ORD-5582')"],
    "trajectoryMatchMode": "UNORDERED", "toolArgsMatchMode": "subset",
    "toolArgsMatchOverrides": { "refund_tool": { "fields": ["order_id"], "mode": "exact" } }, "judgeRubric": null,
    "failToPassValidated": true, "validationExecutionTraceId": "tracely-replay:c4d1…", "promotedByUserId": "user_julien" }
}
```

Reading: 134 occurrences across 121 distinct traces since v12; first-failing step localized to the **handoff span** (not the tool span where the error surfaced — first-failing-step rule, `91 §3.1`); MAST = inter-agent (the ~37% bucket); the fix tightens the tool schema **and** suggests a verification node; the promoted test fails on v12 with `order_id=''` and is expected to pass on the fixed version — and now gates every PR that touches `agent_support_orchestrator` (doc 08).

---

## 13. Reuse ledger (what we port from Langfuse vs build new)

| Concern | Reuse from Langfuse (`file:line` via 92) | Build new for Tracely |
|---|---|---|
| Production-trace trigger | `createEvalJobs` on `TraceUpsert` (`92:783`); 30s debounce (`traceUpsert.ts:80`) | rename → `AgentRunComplete`; shard by `conversationId` |
| BullMQ skeleton | `WorkerManager.register` + `metricWrapper` (`92:1112-1114`); no-DLQ failed-set + cron retry (`09:211`) | 8 new queues (§11) |
| LLM-call retry | 24h self-requeue + `RetryBaggage` (`92:1111`, `09:330`) | apply to RCA/fix/testgen |
| Self-traced evals | `executionTraceId = createW3CTraceId(jobExecutionId)` (`92:779`); env infinite-loop guard (`92:777`) | `tracely-rca` / `tracely-replay` envs |
| Deterministic idempotent writes | `uuidv5` score-id formula (`92:780`); `ReplacingMergeTree` + `LIMIT 1 BY` (`92:432`) | `failure_signals` table (§2.2) |
| Score addressing | nullable trace/turn/step/run targets + `execution_trace_id` (`92:354`, `92:1080`) | extend targets to `agent_run/turn/step` (`92:1090`) |
| Span model | `events_full` first-class cols, tool_calls/tool_call_names (`92:120`, `92:661`) | read trajectory + tool args from these |
| Detection / clustering / RCA / test-gen | — (Langfuse has none of this) | **all of §4–§8** (Drain3, MinHash-LSH, BERTopic, first-failing-step, LIBRO/Issue2Test/BRMiner) |

---

## 14. Open questions for siblings

1. **Doc 06 (eval-model):** owns `EvaluationCase` executable fields + the **replay engine** (`replayAgainstVersion`, fixture injection). This doc assumes hermetic, deterministic replay exists. Confirm the fixture contract matches §8's mined fixtures.
2. **Doc 08 (gate):** must honor `status=PROMOTED ∧ failToPassValidated=true` as gate-eligibility (§2.3). `GateRun` consumes `EvaluationSuite`s built here.
3. **Docs 02/05/11 (infra/ingestion/SDK):** V2 needs **stack frames on error spans** + **tool-binding metadata** for span→source mapping (§9). Out of scope for V1.
4. **`[Synthesis]` embedding model + dimension** (1024-d assumed) and pgvector index type (`hnsw` vs `ivfflat`) — pin in the infra doc; affects the `FailureCluster.centroidEmbedding` column.
