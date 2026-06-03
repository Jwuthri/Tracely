# Langfuse v3 Trace Ingestion Pipeline & Event Lifecycle (Native API)

> **TL;DR.** Langfuse ingestion is an **event-sourced, last-write-wins pipeline**. The public `/api/public/ingestion` endpoint validates a batch, writes each entity's raw events as JSON to **S3/blob storage (the durable source of truth)**, and enqueues one lightweight Redis/BullMQ job *per entity* (`projectId-eventBodyId`). A sharded worker downloads **all** S3 event files for that entity, reads the current ClickHouse row, deep-merges everything field-by-field (immutable keys protected), and upserts a single derived row into a `ReplicatedReplacingMergeTree` keyed on `(project_id, …, id)` with `event_ts` as the version and `is_deleted` as the delete marker. ClickHouse is explicitly **derived/rebuildable** from the S3 log; idempotency, out-of-order updates, and partial updates all fall out of "re-list all events + re-merge + ReplacingMergeTree dedup".

This document traces **one batch of events end-to-end**, citing the actual v3.177.1 source.

---

## 0. Where the code lives (map)

| Stage | File |
|---|---|
| HTTP endpoint (auth, size, batch parse) | `web/src/pages/api/public/ingestion.ts` |
| Core batch processor (validate, S3 upload, enqueue) | `packages/shared/src/server/ingestion/processEventBatch.ts` |
| Event Zod schemas + `eventTypes` | `packages/shared/src/server/ingestion/types.ts` |
| Trace-id sampling | `packages/shared/src/server/ingestion/sampling.ts` |
| Score validation/inflation | `packages/shared/src/server/ingestion/validateAndInflateScore.ts` |
| `eventType → entityType` mapping | `packages/shared/src/server/clickhouse/schemaUtils.ts` |
| BullMQ ingestion queue (sharded) | `packages/shared/src/server/redis/ingestionQueue.ts` |
| Worker job consumer (S3 download + dispatch) | `worker/src/queues/ingestionQueue.ts` |
| Merge engine | `worker/src/services/IngestionService/index.ts` |
| Field-merge primitive | `worker/src/services/IngestionService/utils.ts` (`overwriteObject`) |
| Buffered ClickHouse writer | `worker/src/services/ClickhouseWriter/index.ts` |
| S3 PutObject / List / Get | `packages/shared/src/server/services/StorageService.ts` |
| Queue names + job types | `packages/shared/src/server/queues.ts` |
| Worker registration / concurrency | `worker/src/app.ts`, `worker/src/queues/workerManager.ts` |
| ClickHouse table DDL | `packages/shared/clickhouse/migrations/clustered/0001_traces.up.sql` (+ `0002`, `0003`, `0011`) |
| Blob-log ref table queries | `packages/shared/src/server/repositories/blobStorageLog.ts` |
| DLQ retry cron | `worker/src/services/dlq/dlqRetryService.ts` |

The endpoint header comment itself describes the three-stage design: **(1) Validation, (2) Async Processing — S3 upload + queue, (3) Sync fallback** (`ingestion.ts:34-49`).

---

## 1. The public ingestion endpoint

`web/src/pages/api/public/ingestion.ts` is a Next.js API route. Key facts:

- **Body size limit: 4.5 MB.** `config.api.bodyParser.sizeLimit = "4.5mb"` (`ingestion.ts:26-32`). This is the hard request ceiling; larger SDK batches must be split client-side.
- **Method gate:** non-`POST` → `MethodNotAllowedError` (`ingestion.ts:73`).
- **Auth:** `ApiAuthService(prisma, redis).verifyAuthHeaderAndReturnScope(req.headers.authorization)` (`ingestion.ts:76-79`). It requires a *project*-scoped key:
  - `!authCheck.validKey` → `UnauthorizedError` (`:81-83`).
  - `!authCheck.scope.projectId` → `"Missing projectId in scope. Are you using an organization key?"` (`:84-88`). Org-level keys cannot ingest.
  - `authCheck.scope.isIngestionSuspended` → `ForbiddenError("Ingestion suspended: Usage threshold exceeded…")` (`:90-94`).
- **Rate limiting:** `RateLimitService.getInstance().rateLimitRequest(authCheck.scope, "ingestion")` (`:104-108`). Notably it **fails open** — if the limiter itself throws, the error is logged and processing continues (`:113-117`).
- **Batch envelope:** the body must be `{ batch: z.array(z.unknown()), metadata: jsonSchema.nullish() }` (`:119-122`). The per-event shape is NOT validated here — only that `batch` is an array. Deep validation happens in `processEventBatch`.
- **Response code: HTTP 207 (Multi-Status).** `res.status(207).json(result)` where `result = { successes, errors }` (`:135-139`). This is the partial-success contract: one bad event does not fail the batch; each event gets its own status.

```
POST /api/public/ingestion
Authorization: Basic <pk:sk>
{ "batch": [ {id,type,timestamp,body}, ... ], "metadata": {...} }
   → 207 { successes:[{id,status:201}], errors:[{id,status,message,error}] }
```

### Authorization is per-event-type

Inside `processEventBatch`, `isAuthorized()` (`processEventBatch.ts:358-374`) refines access:
- `SDK_LOG` → always allowed.
- `SCORE_CREATE` → allowed for `accessLevel === "scores"` **or** `"project"`.
- everything else → requires `accessLevel === "project"`.

This means a **"scores-only" API key** can post scores but not traces/observations — relevant for delegating eval/annotation writes.

---

## 2. Event types (the wire protocol)

`eventTypes` (`types.ts:259-279`) is the discriminator. Every ingestion event is `{ id, timestamp (ISO8601), metadata?, type, body }` (the `base` schema, `types.ts:597-601`). Types:

| `type` string | Body schema | ClickHouse entity (`getClickhouseEntityType`) |
|---|---|---|
| `trace-create` | `TraceBody` | `trace` |
| `event-create` | `CreateEventEvent` | `observation` (type=`EVENT`) |
| `span-create` / `span-update` | `CreateSpanBody` / `UpdateSpanBody` | `observation` (type=`SPAN`) |
| `generation-create` / `generation-update` | `CreateGenerationBody` / `UpdateGenerationBody` | `observation` (type=`GENERATION`) |
| `agent-create`, `tool-create`, `chain-create`, `retriever-create`, `evaluator-create`, `embedding-create`, `guardrail-create` | `CreateGenerationBody` | `observation` (type=`AGENT`/`TOOL`/`CHAIN`/`RETRIEVER`/`EVALUATOR`/`EMBEDDING`/`GUARDRAIL`) |
| `score-create` | `ScoreBody` (discriminated on `dataType`) | `score` |
| `dataset-run-item-create` | `DatasetRunItemBody` | `dataset_run_item` |
| `sdk-log` | `SdkLogEvent` | `sdk_log` |
| `observation-create` / `observation-update` | `LegacyObservationBody` | `observation` (legacy, back-compat) |

Mapping in `schemaUtils.ts:17-50`. The full discriminated union is `ingestionEvent` (`types.ts:699-719`).

**Agent-first relevance, observed directly:** Langfuse v3 already has **first-class observation subtypes for agentic systems** — `AGENT_CREATE`, `TOOL_CREATE`, `CHAIN_CREATE`, `RETRIEVER_CREATE`, `EVALUATOR_CREATE`, `GUARDRAIL_CREATE`, `EMBEDDING_CREATE` (`types.ts:267-273`, observation-type switch at `IngestionService/index.ts:1531-1571`). All of them reuse `CreateGenerationBody`, so they carry model/usage/cost/prompt. The trajectory shape (agent → tool → llm) is captured via `parentObservationId` (`types.ts:432`) — a flat list of observations linked by parent pointers, *not* a nested tree on the wire.

Notable schema details:
- **`id` max length is 800 chars** specifically to leave room inside the 1024-byte S3 object-key limit (`types.ts:10-16`) — the entity id literally becomes part of the storage path.
- **Create vs Update**: `*-create` and `*-update` are *separate event types*, but they target the same entity row. Updates are how end-times, outputs, usage, etc. arrive after the span opened. There is no required ordering on the wire; ordering is reconstructed at merge time (§6).
- **Usage** is normalized through several transforms (OpenAI Completion/Response formats, `promptTokens`→`input`, etc.) at `types.ts:45-223`.
- Score bodies are validated lazily; a bad score is **dropped silently** at merge time (see §5).

---

## 3. Batch processing: validation, grouping, sampling

`processEventBatch(input, authCheck, options)` (`processEventBatch.ts:104`) is the shared core (reused by the OTel path and the legacy `/scores` endpoint).

**3a. Per-event validation** (`:155-186`). Each raw event is `ingestionSchema.safeParse`d.
- Parse failure → pushed to `validationErrors` (→ HTTP 400 in the response), event dropped from the batch.
- Auth failure (`isAuthorized`) → `authenticationErrors` (→ 401), dropped.
- `sdk-log` events are logged and removed from further processing (`:179-186`).
- The schema is environment-aware: `createIngestionEventSchema(isLangfuseInternal)` picks public vs internal env-name validation (`types.ts:820-824`).

**3b. Sort** (`sortBatch`, `:379-398`): non-update events first (sorted by ts asc), then update events (sorted by ts asc). So within one HTTP batch, creates are processed before updates.

**3c. Group by entity** (`:192-221`): events are bucketed into `sortedBatchByEventBodyId`, keyed by `` `${getClickhouseEntityType(type)}-${body.id}` ``. **This is the unit of work for the rest of the pipeline** — all events for one (entity-type, entity-id) within this batch are stored and enqueued together. Events without `body.id` are skipped (`:205-207`).

**3d. Sampling** (`sampling.ts`): `isTraceIdInSample({projectId, event})` (`:6-28`). Only active if the project is in `LANGFUSE_INGESTION_PROCESSING_SAMPLED_PROJECTS`. Decision is **deterministic by trace id**: `SHA-256(traceId)`, take first 8 hex chars → 32-bit int → normalize to [0,1), keep if `< sampleRate` (`sampling.ts:30-53`). Trace id is extracted via `parseTraceId` (`:55-59`: `body.id` for traces, else `body.traceId`). Sampling happens at enqueue time, *after* the S3 write — so the durable log can retain more than what's processed into ClickHouse. Out-of-sample entities simply skip the `queue.add` (`processEventBatch.ts:305-311`).

---

## 4. The S3 event log (the durable source of truth) + Redis enqueue

This is the heart of the "trace is the source of truth" claim.

**4a. S3 upload (blocking, but the real persistence step).** `processEventBatch.ts:226-265`:
- For each entity group, all its events are uploaded **as a JSON array** to:
  ```
  {LANGFUSE_S3_EVENT_UPLOAD_PREFIX}{projectId}/{entityType}/{eventBodyId}/{key}.json
  ```
  (`:237`). `key` is the first event's `id` (`:213`), so each *write* of a batch lands in its own object — multiple updates to the same span across different batches produce multiple JSON files under the same `…/{entityType}/{eventBodyId}/` prefix.
- Upload is `getS3StorageServiceClient(bucket).uploadJson(bucketPath, data)`. `uploadJson` issues an S3 `PutObjectCommand` with `Body: JSON.stringify(body)`, `ContentType: "application/json"` (`StorageService.ts:715-731`).
- **Failure handling: fail-closed for S3.** Uploads run via `Promise.allSettled`; if *any* rejects, `s3UploadErrored = true` and the whole function `throw`s `"Failed to upload events to blob storage, aborting event processing"` (`:268-272`). The endpoint then returns 500 and the SDK retries. **The design refuses to enqueue work it hasn't durably persisted first** — this is what makes S3 the source of truth, not an afterthought.
- S3 `SlowDown` (throttling) errors additionally flag the project via `markProjectS3Slowdown(projectId)` to divert it to a secondary queue (`:248-258`).

**4b. Redis enqueue (one job per entity).** `processEventBatch.ts:281-349`:
- Sharding key: `` `${projectId}-${eventBodyId}` `` (`:284`). `IngestionQueue.getInstance({ shardingKey })` hashes it to a shard (only when `REDIS_CLUSTER_ENABLED`; otherwise shard 0) (`ingestionQueue.ts:45-92`). Same entity → same shard → serialized processing.
- The job payload is **tiny — it carries no event bodies**, only a *pointer*:
  ```ts
  payload: { data: { type, eventBodyId, fileKey: key, skipS3List, forwardToEventsTable },
             authCheck: { scope: { projectId, accessLevel } } }
  ```
  (`:328-343`). The worker re-reads bodies from S3. This keeps Redis small and makes S3 authoritative.
- **`skipS3List` optimization** (`:287-298`): for OTel observations / configured projects, the producer knows the exact file and tells the worker to `download` it directly instead of `listFiles`-ing the whole prefix. Dataset-run-items always skip the list.
- **Job delay** (`getDelay`, `:62-82`): default branch returns `min(5000, LANGFUSE_INGESTION_QUEUE_DELAY_MS)` for API events (so ~5 s) — a deliberate small delay so that rapid create+update bursts for the same entity are more likely to be merged in one pass. Around the UTC midnight boundary (23:45–00:15) it uses the full `LANGFUSE_INGESTION_QUEUE_DELAY_MS` (default **15 000 ms**, `env.ts:125-128`) to avoid duplicate rows across the daily date-partition boundary.

**4c. BullMQ queue config** (`ingestionQueue.ts:69-83`):
```ts
new Queue("ingestion-queue"…, { defaultJobOptions: {
    removeOnComplete: true,
    removeOnFail: 100_000,   // keep last 100k failed jobs = the DLQ
    attempts: 6,
    backoff: { type: "exponential", delay: 5000 },
}})
```
Queue name `ingestion-queue` (+ `-N` per shard); enum at `queues.ts:336`. Job name `QueueJobs.IngestionJob = "ingestion-job"` (`queues.ts:376`). Shard count = `LANGFUSE_INGESTION_QUEUE_SHARD_COUNT` (default 1, `env.ts:129`).

### Two storage records, do not confuse them
- **The S3 objects** = the event log payloads (raw JSON event arrays). Authoritative.
- **`blob_storage_file_log`** (ClickHouse table) = a *reference index* of which S3 files exist per entity, for retention/deletion bookkeeping. Written by the worker (§5), queried in `repositories/blobStorageLog.ts`. It does **not** store event bodies — only `bucket_name`, `bucket_path`, `entity_type`, `entity_id`, etc. (DDL `0011_add_blob_storage_file_log.up.sql:1-21`).

---

## 5. The worker: consume → fetch-all → merge → upsert

`worker/src/queues/ingestionQueue.ts` (`ingestionQueueProcessorBuilder`). Worker registered in `worker/src/app.ts:364-372` with concurrency `LANGFUSE_INGESTION_QUEUE_PROCESSING_CONCURRENCY` (default **20**, `worker/src/env.ts:81-84`), one BullMQ `Worker` per shard.

Per job:

1. **Write blob-log reference** (if `LANGFUSE_ENABLE_BLOB_STORAGE_FILE_LOG === "true"`): enqueue a `BlobStorageFileLog` row (the S3 path index) to the ClickhouseWriter (`ingestionQueue.ts:62-81`).

2. **"Recently processed" idempotency cache** (if `LANGFUSE_ENABLE_REDIS_SEEN_EVENT_CACHE === "true"`): check Redis key
   ```
   langfuse:ingestion:recently-processed:{projectId}:{type}:{eventBodyId}:{fileKey}
   ```
   If it exists → **skip the whole job** (`:84-106`). This dedups the case where the same `fileKey` is enqueued twice within the 5-minute TTL.

3. **Secondary-queue redirect** (`:108-133`): if the project is in `LANGFUSE_SECONDARY_INGESTION_QUEUE_ENABLED_PROJECT_IDS` *or* has a live S3-slowdown flag (`hasS3SlowdownFlag`), the job is re-added to `secondary-ingestion-queue` and this handler returns. Isolates noisy-neighbor / throttled projects (concurrency default 5, `env.ts:85-88`).

4. **Download ALL events for the entity** (`:149-206`):
   - `s3Prefix = {PREFIX}{projectId}/{entityType}/{eventBodyId}/`.
   - If `skipS3List`: download the single `fileKey` object.
   - Else: `s3Client.listFiles(s3Prefix)` → download every file, in batches of `LANGFUSE_S3_CONCURRENT_READS` (default **50**, `worker/src/env.ts:342`). Each file is a JSON array; all are flattened into one `events: IngestionEventType[]`. The comment notes 5k events ≈ 100 s — this is an explicit O(n events per entity) re-read on every update.
   - **This is the key event-sourcing move: the worker reconstructs the entity's *entire* event history from S3 on every job**, not just the delta. Idempotency and out-of-order tolerance follow directly.
   - If zero events found → warn and return (`:231-236`).

5. **Refresh the recently-processed cache** for all downloaded files (TTL 5 min) (`:238-261`).

6. **Dispatch to `IngestionService.mergeAndWrite(...)`** (`:273-285`), passing entity type, projectId, eventBodyId, `firstS3WriteTime` (min `createdAt` of the S3 files, used as the canonical `created_at`), the events, and `forwardToEventsTable`.

### Error / retry / DLQ at the worker level
- On any throw, the handler logs, `traceException`s, re-marks S3 slowdown if applicable, and **re-throws** (`ingestionQueue.ts:286-303`) → BullMQ retries up to **6 attempts** with exponential backoff (delay 5 s). After exhausting attempts, the job lands in the **failed set (`removeOnFail: 100_000`)** = the de-facto DLQ for ingestion.
- **Important caveat:** `DlqRetryService` (`worker/src/services/dlq/dlqRetryService.ts`) auto-retries failed jobs every 10 min, but its `retryQueues` list is **only** `ProjectDelete, TraceDelete, ScoreDelete, BatchActionQueue, DataRetentionProcessingQueue` (`dlqRetryService.ts:9-15`). **`IngestionQueue` is NOT in that list** — failed ingestion jobs are *not* auto-retried by the cron; they sit in the failed set for manual replay (there's a dedicated `worker/src/scripts/replayIngestionEvents/s3-ingestion-event-replay.ts` that rebuilds events from S3 paths). The failed-set length is exported as a `…dlq_length` gauge (`workerManager.ts:83-87`).
- Generic worker `failed`/`error` handlers (metrics + Sentry) live in `workerManager.ts:161-184`.

---

## 6. The merge: last-write-wins, field-level, immutable-key-protected

`IngestionService` (`worker/src/services/IngestionService/index.ts`). `mergeAndWrite` switches on entity type (`:148-194`). Traces, observations, and scores all follow the same shape; I describe the **observation** path (most complex) and note differences.

**6a. Read current ClickHouse row** (`getClickhouseRecord`, `:1356-1486`). Query:
```sql
SELECT * FROM {table}
WHERE project_id = {projectId} AND id = {entityId} {extra filters}
ORDER BY event_ts DESC
LIMIT 1 BY id, project_id
SETTINGS use_query_cache = false;
```
- `ORDER BY event_ts DESC … LIMIT 1 BY id, project_id` = "the latest version of this row" *without* needing `FINAL`. Extra filters narrow by `type` + `start_time >= minStartTime` (observations) or `timestamp >=` (traces/scores) to hit the right partition.
- This read can be **skipped** entirely via `ClickhouseReadSkipCache.shouldSkipClickHouseRead(projectId)` (`:1395-1405`) — for brand-new entities or configured projects, Langfuse skips the read and merges only the in-batch events (an insert-only fast path). Metric: `langfuse.ingestion.clickhouse_read_for_update{skipped}`.

**6b. Map events → records.** `mapObservationEventsToRecords` (`:1573-1694`) turns each event body into an `ObservationRecordInsertType`, computing `event_ts = new Date(event.timestamp).getTime()` per record, usage/cost details, type, etc. `toTimeSortedEventList` (`:1006-1019`) sorts by `timestamp` asc, breaking ties so **`*create` events sort before updates**.

**6c. Merge.** `mergeObservationRecords` (`:946-981`) builds `recordsToMerge = [clickhouseRecord, ...sortedEventRecords]` — **the existing CH row is the *first* (base) element**, then every event in time order. It calls `mergeRecords` (`:983-1004`), which folds the list left-to-right with `overwriteObject`.

`overwriteObject` (`utils.ts:56-97`) is the merge primitive:
```ts
mergeWith({}, a, b, (objValue, srcValue, key) => {
  if (nonOverwritableKeys.includes(key)        // immutable: keep base
      || srcValue === undefined                 // missing field: keep prior
      || (typeof srcValue === 'object' && srcValue !== null
          && Object.keys(srcValue).length === 0)) // empty {} (e.g. empty usage): keep prior
    return objValue;
  return srcValue;                               // otherwise: last write wins
});
// metadata: deep-merged (union) across a and b
// tags: set-union, sorted
```
So merge semantics are:
- **Last-write-wins per scalar field**, with later events overriding earlier — but an `undefined` field never clobbers an existing value (partial updates are safe). An empty object never clobbers populated usage/cost.
- **`metadata` accumulates** (deep merge), **`tags` union**. These two are *not* last-write-wins.
- **Immutable keys are pinned to the base** (the CH row / first event), never overwritten:
  - Traces: `id, project_id, timestamp, created_at, environment` (`index.ts:91-97`).
  - Scores: `id, project_id, timestamp, trace_id, created_at, environment` (`:98-105`).
  - Observations: `id, project_id, trace_id, start_time, created_at, environment` (`:106-113`).

  This is why an out-of-order *update* that arrives before the *create* still can't move `start_time`/`timestamp` backward incorrectly, and why `created_at` is stable across re-merges.

**6d. Input/Output special-casing** (`:806-822` observations, `:617-665` traces). Instead of merging giant I/O blobs field-wise (expensive), the merge takes the **last truthy `input`/`output`** scanning events newest-first, falling back to the CH row's value. Token counting / tool-call normalization run on the merged result (`normalizeToolsForObservation`, `getGenerationUsage`).

**6e. `event_ts` is overwritten to "now" on the merged record.** `mergeRecords` sets `result.event_ts = new Date().getTime()` (`:1001`). So the *written* row always has the freshest version stamp → it wins the ReplacingMergeTree dedup against whatever is already in CH. (Per-event `event_ts` was only used for sorting / `LIMIT 1 BY` reads.)

**6f. Schema-validate and enqueue write.** The merged object is parsed through `observationRecordInsertSchema` / `traceRecordInsertSchema` / `scoreRecordInsertSchema` (Zod) before `clickHouseWriter.addToQueue(TableName.Observations, finalRecord)` (`:873-876`). End-times before start-times are clamped (`:973-978`).

**6g. Side effects on trace merge** (`processTraceEventList`, `:592-735`):
- Upsert `trace_sessions` into **Postgres** if `sessionId` present (`:676-681`, `ON CONFLICT DO NOTHING`).
- Enqueue `TraceUpsert` job (for eval processing) — **unless** `hasNoEvalConfigsCache(projectId,"traceBased")` says the project has no evaluators (a cache to avoid useless queue churn) (`:705-734`).
- Backward-compat: an observation with no `trace_id` synthesizes a wrapper trace row (`:852-871`).

**Scores** additionally run `validateAndInflateScore` per event (`processScoreEventList`, `:489-590`) which resolves `configId` against Postgres, applies config name/range validation, and inflates `value`/`stringValue`/`dataType`. A score that fails validation is **caught and returns `null` → silently skipped** (`:558-565`) — bad scores never reach ClickHouse and never fail the batch.

---

## 7. The buffered ClickHouse writer + ReplacingMergeTree

`ClickhouseWriter` (`worker/src/services/ClickhouseWriter/index.ts`) is a singleton in-process buffer (one queue per table, `:50-59`).

- **Batched flush:** flush when a table queue reaches `LANGFUSE_INGESTION_CLICKHOUSE_WRITE_BATCH_SIZE` (default **1000**, `worker/src/env.ts:90-93`) or every `LANGFUSE_INGESTION_CLICKHOUSE_WRITE_INTERVAL_MS` (default **1000 ms**, `:94-97`) (`addToQueue` `:548-566`, `start` `:80-96`).
- **Write:** `client.insert({ table, format: "JSONEachRow", values: records })` (`writeToClickhouse`, `:568-602`).
- **Retries:** `backOff(..., { numOfAttempts: LANGFUSE_INGESTION_CLICKHOUSE_MAX_ATTEMPTS (default 3) })` (`:389-481`). Special error handlers: socket-hangup → retry; JS `"invalid string length"` → split the batch in half and retry/requeue (`handleStringLengthError`, `:172-206`); ClickHouse "size of JSON object … extremely large" → truncate oversized `input`/`output`/`metadata` fields to 500 KB and retry (`truncateOversizedRecord`, `:208-278`).
- **On final failure:** re-queue with incremented attempts; once `attempts >= maxAttempts` the record is **dropped** (logged with ids; metric `langfuse.queue.clickhouse_writer.rows_dropped`). There is an explicit `// TODO - Add to a dead letter queue in Redis rather than dropping` (`:516`). So the *ClickHouse write* layer has **no DLQ** today — but because S3 still holds the events, the row is recoverable via replay.

### Target tables & engines (the "derived" store)

`TableName` enum (`ClickhouseWriter/index.ts:605-614`): `traces`, `traces_null`, `scores`, `observations`, `observations_batch_staging`, `blob_storage_file_log`, `dataset_run_items_rmt`, `events_full`.

The three core entity tables are all **`ReplicatedReplacingMergeTree(event_ts, is_deleted)`**:

```sql
-- 0001_traces.up.sql
CREATE TABLE traces ON CLUSTER default ( id String, timestamp DateTime64(3), …,
    event_ts DateTime64(3), is_deleted UInt8, … )
ENGINE = ReplicatedReplacingMergeTree(event_ts, is_deleted)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (project_id, toDate(timestamp), id);
```
- **Version column = `event_ts`**, **delete column = `is_deleted`**. On background merges, ClickHouse keeps the row with the highest `event_ts` per sort key and drops rows where the surviving version has `is_deleted = 1`.
- `observations`: same engine, `PARTITION BY toYYYYMM(start_time)`, sort key `(project_id, …, id)` (`0002_observations.up.sql:35`).
- `scores`: same engine, `PARTITION BY toYYYYMM(timestamp)` (`0003_scores.up.sql:22`).
- `blob_storage_file_log`: `ReplicatedReplacingMergeTree(event_ts, is_deleted)`, `ORDER BY (project_id, entity_type, entity_id, event_id)` (`0011:15-21`).
- `event_log` (legacy/superseded by `blob_storage_file_log`): plain `MergeTree()` (`0007_add_event_log.up.sql:14`).

**Why this matters for idempotency/out-of-order:** because the writer always upserts a *full merged row* with a fresh `event_ts`, and the engine deduplicates by `(sort key, max event_ts)`, the system is naturally idempotent and order-insensitive at the storage layer. Reprocessing the same S3 events produces an identical merged row that ReplacingMergeTree collapses. Reads that must not see duplicates use `FINAL` (e.g. `blob_storage_file_log FINAL` in `blobStorageLog.ts:14-21`) or the `LIMIT 1 BY … ORDER BY event_ts DESC` trick (as in the ingestion read, §6a).

> `events_full` / `observations_batch_staging` / `traces_null` are part of an **experimental "events table" propagation path** gated by `forwardToEventsTable` / `LANGFUSE_EXPERIMENT_INSERT_INTO_EVENTS_TABLE` (`ingestionQueue.ts:269-271`, `IngestionService` `createEventRecord`/`writeEventRecord` `:211-393`). For the mainline trace/observation/score lifecycle they are a dual-write side-channel; treat as in-flux, not core.

---

## 8. End-to-end sequence diagram

```mermaid
sequenceDiagram
    autonumber
    participant SDK as SDK / OTel
    participant API as web: /api/public/ingestion
    participant PEB as processEventBatch (shared)
    participant S3 as S3 / Blob Storage (SOURCE OF TRUTH)
    participant RQ as Redis BullMQ (ingestion-queue, sharded by projectId-entityId)
    participant W as worker: ingestionQueueProcessor
    participant IS as IngestionService.mergeAndWrite
    participant CHR as ClickHouse (read latest row)
    participant CW as ClickhouseWriter (buffer, 1000 / 1s)
    participant CH as ClickHouse RMT (traces/observations/scores)

    SDK->>API: POST batch {batch:[...]}  (<=4.5MB)
    API->>API: auth (project-scoped key), rate-limit (fail-open), parse envelope
    API->>PEB: processEventBatch(batch, authCheck)
    PEB->>PEB: per-event Zod validate + isAuthorized (collect 400/401), drop sdk-log
    PEB->>PEB: group by entityType-bodyId; sort (creates before updates)
    PEB->>S3: PutObject {prefix}/{proj}/{entity}/{id}/{key}.json  (JSON array of events)
    alt any S3 upload fails
        S3-->>PEB: reject
        PEB-->>API: throw -> HTTP 500 (SDK retries; nothing enqueued)
    else all uploaded
        PEB->>PEB: sampling decision (deterministic by traceId)
        PEB->>RQ: add IngestionJob {type, eventBodyId, fileKey} (pointer only), delay ~5s
        PEB-->>API: aggregateBatchResult
        API-->>SDK: 207 {successes:[201], errors:[...]}
    end

    RQ->>W: IngestionJob (after delay), up to 6 attempts
    W->>CW: enqueue blob_storage_file_log ref row
    W->>RQ: (check redis "recently-processed" cache -> maybe skip)
    W->>S3: listFiles(prefix) + download ALL event files (concurrency 50)
    Note over W,S3: reconstruct entity's FULL event history from S3
    W->>IS: mergeAndWrite(entityType, proj, id, firstS3WriteTime, events)
    IS->>CHR: SELECT * ... ORDER BY event_ts DESC LIMIT 1 BY id,project_id (skippable)
    CHR-->>IS: current row (or null)
    IS->>IS: merge [chRow, ...timeSortedEvents] via overwriteObject\n(LWW per field; metadata deep-merge; tags union; immutable keys pinned)\nset merged.event_ts = now()
    IS->>CW: addToQueue(observations/traces/scores, mergedRow)
    opt trace has sessionId / evaluators
        IS->>IS: upsert trace_sessions (Postgres); enqueue TraceUpsert (eval)
    end
    CW->>CH: INSERT JSONEachRow (batched; retry x3; split/truncate on size errors)
    Note over CH: ReplacingMergeTree(event_ts, is_deleted)\nkeeps max(event_ts) per (project_id,...,id); is_deleted=1 tombstones
```

ASCII view of the durability boundary:

```
                 fail-closed                          re-read EVERYTHING
   SDK ──POST──► [API+PEB] ──PutObject──► (((  S3 EVENT LOG  )))  ◄──list+get── [WORKER]
                    │                         the source of truth                  │
                    └──pointer job (no body)──► [Redis BullMQ] ──delayed──► consume ┘
                                                                                    │ merge
   ClickHouse (traces/observations/scores)  ◄── batched INSERT (RMT upsert) ◄───────┘
        = DERIVED, rebuildable from S3 via replay script
```

---

## 9. Idempotency / out-of-order / partial-update / retry — consolidated

| Concern | Mechanism | Source |
|---|---|---|
| **Idempotency (same event twice)** | Worker re-lists & re-merges all S3 files → identical merged row; ReplacingMergeTree collapses by `(sort key, max event_ts)`. Plus Redis "recently-processed" cache short-circuits duplicate `fileKey` within 5 min. | `ingestionQueue.ts:84-106`; `index.ts:983-1004`; DDL engines |
| **Out-of-order (update before create)** | Events are time-sorted at merge (`toTimeSortedEventList`), and immutable keys (`start_time`,`timestamp`,`created_at`,`environment`,ids) are pinned to the base, so late/early arrival can't corrupt them. | `index.ts:1006-1019, 85-134` |
| **Partial update (only end_time set)** | `overwriteObject` skips `undefined` and empty-`{}` source fields → never clobbers existing values; `metadata` accumulates, `tags` union. | `utils.ts:56-97` |
| **Late update after row already in CH** | Read-back of current CH row is folded in as the merge base; merged row written with `event_ts = now()` so it wins dedup. | `index.ts:946-1004, 1356-1486` |
| **API/SDK retry** | S3 upload is fail-closed → on S3 error nothing is enqueued, SDK gets 500 and retries the whole batch safely (idempotent). | `processEventBatch.ts:268-272` |
| **Queue retry** | BullMQ `attempts:6`, exponential backoff 5 s; failures land in `removeOnFail:100_000` failed set. | `ingestionQueue.ts:73-81` |
| **DLQ** | Failed-set = de-facto DLQ; **not** auto-retried for ingestion (cron only covers delete/batch queues). Manual replay script rebuilds from S3. | `dlqRetryService.ts:9-15`; `scripts/replayIngestionEvents/` |
| **CH write failure** | ClickhouseWriter retries x3, splits on string-length errors, truncates on size errors; after max attempts **drops** the row (TODO: DLQ). Recoverable from S3. | `ClickhouseWriter/index.ts:356-546` |
| **Midnight partition boundary** | Larger queue delay (15 s) near 23:45–00:15 UTC to avoid cross-`toYYYYMM` duplicates. | `processEventBatch.ts:62-82` |

---

## 10. Relevance to Tracely (agent-first, trace-first, regression-from-production)

### Steal (architecture that directly serves a trace-native CI/CD product)

1. **S3-event-log-as-source-of-truth, ClickHouse-as-derived.** This is *exactly* the substrate Tracely needs: if production traces are your regression corpus, you must be able to **replay and recompute** them when an evaluator/metric/schema changes. Langfuse proves the pattern — fail-closed S3 write, tiny pointer jobs, worker re-reads everything, RMT upsert. For Tracely, "re-run the eval suite over historical traces" becomes "replay from the event log," and "schema migration" becomes "rebuild the derived store." Keep the boundary explicit (`processEventBatch.ts:268-272`, replay script).
2. **Per-entity event sourcing + field-level last-write-wins merge** (`overwriteObject`, immutable-key pinning, metadata-accumulate/tags-union). This lets long-running agent spans stream partial updates (tool started → tool finished → tokens) without ordering guarantees — essential for multi-turn / planner-executor / handoff traces where events arrive interleaved.
3. **First-class agentic observation subtypes already exist** (`AGENT/TOOL/CHAIN/RETRIEVER/EVALUATOR/GUARDRAIL/EMBEDDING`, `types.ts:267-273`). Tracely's entity model (Tool Call, LLM Call, Sub-Agent Call, Step) maps cleanly onto these. The wire format (flat observations + `parentObservationId`) is a proven way to encode trajectories; Tracely's trajectory evals can be computed by walking parent pointers.
4. **Sharded-by-entity queue + delayed merge window** (`projectId-eventBodyId` sharding, ~5 s delay). Guarantees serialized processing per entity and coalesces bursts — reuse verbatim for per-agent-run ingestion.
5. **Idempotency primitives**: deterministic SHA-256 trace sampling, ReplacingMergeTree dedup, "recently-processed" cache. All transferable.
6. **Partial-success 207 contract + per-event errors.** Good API ergonomics for high-volume agent telemetry.

### Adapt / strengthen for Tracely

- **Make replay/recompute a first-class product surface, not a script.** Langfuse's ingestion replay is a maintenance tool (`scripts/replayIngestionEvents/`); Tracely should expose "recompute evals/metrics over trace range X" and "promote production trace → regression case" as core APIs, since *that is the product*. The event log already supports it.
- **The eval trigger is bolted on, and it's trace-final, not trajectory-level.** Langfuse only enqueues a single `TraceUpsert` job for trace-based evals at trace-merge time (`index.ts:705-734`), gated by `hasNoEvalConfigsCache`. Tracely wants **multi-level, trajectory-aware** evaluation (conversation/turn/step/tool/agent/multi-agent). Design the ingestion→evaluation hand-off to fan out at *every* level the trace exposes, ideally from the durable log so evals are re-runnable — don't copy the single trace-level hook.
- **Close the DLQ gap.** Two places drop data on the floor: ingestion failed-set isn't auto-retried (`dlqRetryService.ts:9-15`), and ClickhouseWriter drops rows after 3 attempts (`ClickhouseWriter/index.ts:516` TODO). For a CI/CD gate product, dropped traces = silent gaps in your regression coverage. Because the S3 log persists, Tracely should add an automatic reconciliation/replay loop that detects derived-store gaps and rebuilds them.
- **Add a versioned, typed event schema for agent constructs.** Langfuse overloads `CreateGenerationBody` for all agentic types and stuffs tool calls into normalized I/O (`normalizeToolsForObservation`). Tracely will likely want explicit `ToolCall` / `SubAgentCall` / `Handoff` event bodies (with Agent Version linkage) so trajectory evals and failure-clustering have clean, typed inputs rather than reverse-engineered ones.

### Ignore (Langfuse-specific distractions for this mission)

- **Prompt management coupling** in the merge path (`PromptService` lookups, `prompt_id/name/version`, `index.ts:1021-1054, 226-238`) — out of scope; Tracely is not a prompt manager.
- **Token-count / cost / pricing-tier enrichment** (`getGenerationUsage`, `calculateUsageCosts`, `findModel`, Decimal64 clamping). Useful for an observability/billing product ("Datadog for LLMs") but orthogonal to regression-from-production. Strip or make optional.
- **Dataset-run-item ingestion** (`processDatasetRunItemEventList`, `dataset_run_items_rmt`) — this is the **dataset-first eval** path the mission explicitly rejects. Note it exists, then ignore.
- **The experimental `events_full`/`observations_batch_staging`/`traces_null` propagation** — in flux, env-gated, not core to the lifecycle.
- **Azure/GCS/multi-backend `StorageService` variants** and SSE/KMS plumbing — infra detail, pick one backend.

### Bottom line for Tracely

Langfuse's **ingestion + storage substrate is a strong fit and worth closely mirroring**: event log in object storage as source of truth, derived columnar store via idempotent ReplacingMergeTree upserts, per-entity sharded async merge. The divergence is *upward* of ingestion — Langfuse stops at "store the trace + maybe fire one trace-level eval," whereas Tracely's value is everything derived from the trace (multi-level trajectory evals, failure clusters, regression cases, CI gates). Build that derivation layer to read from, and be re-runnable against, the same durable event log.
