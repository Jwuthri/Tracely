# Tracely — Canonical Decisions (Single Source of Truth)

> **Status: AUTHORITATIVE.** This document adjudicates every naming/keys/enum/store conflict across the Part 2 design docs (01–10) that the adversarial review surfaced. **Where any sibling doc disagrees with this file, this file wins; for full copy-pasteable DDL, `09-database-schema.md` is the schema of record and has been reconciled to this file.** Read this first, then `03-agent-and-trace-data-model.md` (entities) and `09-database-schema.md` (DDL).
>
> Why this exists: docs 01–10 were drafted in parallel by independent authors. They agree on architecture and thesis but drifted on ~16 surface details (entity keys, enum values, queue names, one store placement, two under-specified algorithms). None require redesign. This file is the one adjudication pass.

---

## 0. How to use

1. **Entity, key, enum, queue, or column name** → this file (§2–§6).
2. **Full DDL / Prisma models** → `09-database-schema.md` (reconciled to this file).
3. **The two load-bearing algorithms** (`config_hash`, replay shim) and the canonical `Trajectory` type → §7 here.
4. **Why a conflict was resolved this way** → §8 resolution log.

---

## 1. North star (unchanged)

The trace is the source of truth; everything (eval, regression test, failure cluster, suggested fix, gate verdict, quality metric) is **derived** from it. Trace-native, agent-first CI/CD. NOT prompt management, NOT dataset-first eval, NOT Datadog-for-LLMs. The product spine: **Production Trace → Failure Detection → Regression Test → CI/CD Gate.**

---

## 2. Canonical entity glossary

| Entity | Store | Natural key | One-liner |
|---|---|---|---|
| **Project** | Postgres | `id` | Tenant boundary (`project_id` everywhere). |
| **Agent** | Postgres | `@@unique([projectId, slug])` | A logical agent. SDK wire attribute `tracely.agent.id` carries the **slug**; ingest upserts Agent by `(projectId, slug)`. |
| **AgentVersion** | Postgres | `@@unique([agentId, configHash])` | Immutable, content-addressed config snapshot. **The thing CI gates.** |
| **AgentRun** | **ClickHouse only** | `agent_run_id` (= root/`is_app_root` span) | One execution. **No Postgres table.** Run-level facts are read-time aggregates over spans. |
| **Conversation** | Postgres (thin) | `@@id([id, projectId])` | Multi-turn grouping shell (id + counters + status), upserted at ingest like Langfuse `trace_sessions`. |
| **Turn** | **ClickHouse only** | `turn_id` + `turn_index` columns on spans | A user↔agent exchange. **No Postgres table** (avoid write amplification). |
| **Step / ToolCall / LLMCall / SubAgentCall** | **ClickHouse** | span rows + `edges` table | Trajectory primitives; typed via `type` + `edges`. No PG tables. |
| **EvaluationSuite** | Postgres | `@@unique([projectId, agentId, slug])` | Named collection of cases bound to an agent (or null `agentId` for cross-agent E2E suites). |
| **EvaluationSuiteCase** | Postgres (join) | `@@id([suiteId, caseId])` | Many-to-many membership with optional `pinnedCaseVersion`. |
| **EvaluationCase** | Postgres | `@@unique([projectId, agentId, inputDigest])` | A regression test derived from a trace. Has a `level`. Fixtures in S3. |
| **Evaluator** | Postgres | `@@unique([projectId, key])` | Registered evaluator (structural / code / llm-judge). |
| **Score** | **ClickHouse** (reused, extended) | `(project_id, …, id)` | The verdict/measurement sink. Reused from Langfuse + new columns (§5). |
| **FailureCluster** | Postgres | `@@unique([projectId, agentId, clusterKey])` | A grouped, deduped failure mode. |
| **ClusterMember** | Postgres (+pgvector) | `@@id([clusterId, traceId])` | Membership join; holds the embedding + medoid flag. |
| **GateRun** | Postgres | `id` | One CI gate execution against a candidate AgentVersion. |
| **GateCase** | Postgres | `@@unique([gateRunId, evaluationCaseId])` | Per-case verdict/cost/latency for the decision engine + PR comment. |

**Store rule of thumb:** control-plane registry/metadata that is read transactionally and rarely → Postgres. High-volume append-only telemetry and verdicts → ClickHouse. Replay fixtures → S3. Failure embeddings → pgvector (a column on `ClusterMember`).

---

## 3. Canonical enums

| Enum | Canonical values | Notes / drift mapping |
|---|---|---|
| **AgentKind** (topology) | `SINGLE`, `MULTI_AGENT`, `WORKFLOW` | Describes the *shape* of the system. |
| **AgentRole** (role in a multi-agent system) | `SUPERVISOR`, `WORKER`, `PLANNER`, `EXECUTOR`, `GENERIC` | Separate field from `kind`. **Impact analysis branches on `role === 'SUPERVISOR'`** (doc 06). Replaces doc 06's overloaded `kind`. |
| **CaseLevel** | `CONVERSATION`, `TURN`, `STEP`, `TOOL_CALL`, `AGENT_RUN`, `MULTI_AGENT` | The scope a case asserts on; the gate uses it to scope replay. Required on every EvaluationCase. |
| **CaseStatus** | `DRAFT`, `PROMOTED`, `QUARANTINED`, `ARCHIVED`, `UNREPRODUCIBLE` | **Gate selects `PROMOTED ∧ failToPassValidated`.** Drift map: `ACTIVE→PROMOTED`, `MUTED→QUARANTINED`, `RETIRED→ARCHIVED`. |
| **CaseOrigin** | `PROMOTED_CLUSTER`, `MANUAL`, `GENERATED` | Where the case came from. Drift map: `AUTODRAFT→GENERATED`, `HUMAN→MANUAL`. Author identity lives in `createdBy` (string), not an enum. |
| **SuiteKind** | `REGRESSION`, `EVAL`, `E2E` | REGRESSION = promoted failures; EVAL = curated quality metrics; E2E = cross-agent. |
| **MatchMode** (trajectory) | `strict`, `unordered`, `subset`, `superset` | From `agentevals`. Default `unordered` (Inclusion > EM empirically). |
| **ArgsMode** (tool args) | `exact`, `ignore`, `subset`, `superset` | Per-tool overrides allowed; per-field exact lists; custom comparator fn. |
| **Verdict** | `PASS`, `FAIL`, `SKIP` | First-class `verdict` column on Score and GateCase. **Replaces the proposed `PASS_FAIL` `data_type` value — do NOT add `PASS_FAIL` to `data_type`.** |
| **ScoreDataType** (Langfuse, unchanged) | `NUMERIC`, `CATEGORICAL`, `BOOLEAN`, `CORRECTION`, `TEXT` | Reused verbatim. Gate/regression results use `BOOLEAN` (1/0) **plus** the `verdict` column. |
| **ScoreSource** (Langfuse, unchanged) | `API`, `EVAL`, `ANNOTATION` | Reused. Tracely eval/gate verdicts use `EVAL`. |
| **EvaluatorFamily** | `STRUCTURAL`, `CODE`, `LLM_JUDGE` | Selects the executor. |
| **GateStatus** | `PENDING`, `RUNNING`, `PASS`, `FAIL`, `ERROR` | |
| **GateTrigger** | `PULL_REQUEST`, `MANUAL`, `SCHEDULED`, `API` | |
| **ClusterStatus** | `OPEN`, `PROMOTED`, `IGNORED`, `MERGED` | |
| **SpanKind / observation `type`** | Reuse Langfuse 10-value `ObservationType`: `SPAN, EVENT, GENERATION, AGENT, TOOL, CHAIN, RETRIEVER, EVALUATOR, EMBEDDING, GUARDRAIL` | Plus Tracely typed `edges` for handoffs (§5). |
| **EnvKind** (`env` column) | `prod`, `staging`, `ci`, `dev` | The gating axis. Distinct from Langfuse free-string `environment` (kept for OTel compat). |

---

## 4. Canonical queue names (BullMQ)

Exactly one name per logical queue. All aliases are removed by the rename pass.

| Canonical queue | Was also called | Purpose |
|---|---|---|
| `IngestionQueue` (+ shards) | — | Reused from Langfuse: S3-merge ingestion. |
| `OtelIngestionQueue` | — | Reused: OTLP spans → events. |
| **`AgentRunComplete`** | `AgentRunUpsert`, `TraceComplete`, (Langfuse `TraceUpsert`) | Fires when a run finishes/debounces; fans out failure detection + online eval. |
| `FailureDetectQueue` | — | Per-run failure-signal extraction. |
| `ClusteringQueue` | — | Batch BERTopic re-cluster + medoid selection. |
| `RcaQueue` | — | First-failing-step localization + LLM RCA agent. |
| `TestGenQueue` | — | Auto-draft candidate EvaluationCase from a cluster. |
| `EvaluationExecution` | — | Reused from Langfuse: run one evaluator (online path). |
| **`GateRunQueue`** | `GateRunOrchestrator` | Orchestrates a GateRun: select suites, fan out replays, decide. |
| **`ReplayQueue`** | `RegressionReplayQueue`, `TrajectoryReplayQueue`, `GateCaseExecution`, `gate-case-queue` | Executes one case replay (record-replay or live) and emits a GateCase. |

---

## 5. The `events` span table — canonical Tracely additions

Take Langfuse `events_full` **verbatim** (see `92-langfuse-verified-facts.md` for the exact base DDL) and apply the following. Full DDL lives in `09-database-schema.md`.

**ADD — first-class semantic columns** (all `String`/`LowCardinality(String)` unless noted; `''` ≡ absent):
- `agent_id`, `agent_version_id`, `agent_run_id`
- `conversation_id`, `turn_id`, `turn_index UInt32`
- `step_id`, `step_name`
- `env LowCardinality(String) DEFAULT 'prod'` — `{prod,staging,ci,dev}` (the gating axis)

**ADD — typed-edge columns** (the common cases; richer edges go in the `edges` table, §below):
- `tool_call_id` — links a `TOOL` span to the LLM tool-call request that asked for it
- `caller_agent_id`, `callee_agent_id`, `edge_type` — handoff/delegation/sub-agent

**ADD — provenance columns:**
- `evaluation_case_id`, `gate_run_id`, `failure_cluster_id` (reuse the Langfuse denormalization trick that put dataset linkage on the row — but with Tracely meaning)

**DROP from the base `events_full` (thesis hygiene):**
- The entire dataset `experiment_*` block (`experiment_id`, `experiment_dataset_id`, `experiment_name`, `experiment_item_id`, `experiment_item_expected_output`, `experiment_item_root_span_id`, …). Replaced by the provenance columns above.
- `prompt_id`, `prompt_name`, `prompt_version` (prompt-management surface; if ever needed, lives in `metadata`).

**KEEP** Langfuse `environment` (free string, OTel-mapper compat) **and** add `env` (Tracely enum). `env` defaults from the SDK attr `tracely.env` or falls back to mapping `environment`.

**The `edges` table** (typed trajectory edges that don't fit a single column): `(project_id, trace_id, from_span_id, to_span_id, edge_type LowCardinality(String) {tool_call,handoff,delegate,retrieve,next_turn}, edge_provenance LowCardinality(String) {explicit,inferred}, …)`. DDL in doc 03/09.

**Score table (CH) extensions** — additive `ALTER`s (one column per migration, Langfuse convention), **not** a table rewrite:
- `verdict LowCardinality(String)` — `{PASS,FAIL,SKIP}` (NOT a new `data_type` value)
- `gate_run_id String`, `evaluation_case_id String`, `evaluation_level LowCardinality(String)`
- bloom-filter skip-indexes on `gate_run_id`, `evaluation_case_id`
- `execution_trace_id` already exists in Langfuse (migration 0030) — reused for self-tracing evals.

---

## 6. Embeddings

- **Dimension: `vector(1024)` everywhere.** (Resolves the 384 vs 1024 split.)
- Model: a 1024-d sentence embedding (e.g. `bge-large-en-v1.5` or `text-embedding-3-large` truncated to 1024). Drop all `all-MiniLM-L6-v2`/384 references.
- Stored as a `pgvector` column on `ClusterMember` (HNSW index). One embedding store; no separate `FailureEmbedding` table.

---

## 7. The two load-bearing algorithms + the canonical Trajectory type

### 7.1 `config_hash` (the gate's content address)

```
config_hash = sha256( RFC8785_canonical_json({
  models:        sortedBy(id)([{ id, params }]),          // resolved model ids + decode params
  promptHashes:  sortedBy(name)([{ name, hash }]),         // see prompt-hash rule below
  toolSchemas:   sortedBy(name)([{ name, schemaHash }]),   // JSON-schema sha256 per tool
  graphHash,                                               // see graph rule below
  framework:     { name, majorMinor }                      // fold patch version
}) )
```

- **Prompt-hash rule.** Hash the **template string + the sorted list of variable names**, *not* the rendered prompt. If only a rendered prompt is available, redact detected interpolations to `{{var}}` and hash that; if not detectable, hash raw and set `configHashDegraded=true`.
- **graphHash serialization** (was unspecified):
  ```
  graphHash = sha256( RFC8785_canonical_json({
    nodes: sortedBy(id)([{ id, kind, role? }]),
    edges: sortedBy([from,to,type])([{ from, to, type, condition? }])
  }) )
  ```
  - LangGraph **conditional edges** → one edge per branch with `type:"conditional"`, `condition: <branchKey>`.
  - Agno **team** → members as nodes, delegations as edges `type:"delegate"`.
  - Single agent → one node, no edges.
- **MCP-backed tool schemas** are fetched at hash time. On fetch failure use the last-known cached schema and set `configHashDegraded=true`; the gate emits a warning (a degraded hash may produce false "unchanged" verdicts).

### 7.2 The canonical `Trajectory` type (consumed by the matcher)

Defined once here and in `03-agent-and-trace-data-model.md`. Docs 04/05 reference it; do not redefine with different field names.

```ts
type StepKind = "llm" | "tool" | "agent" | "subagent" | "step" | "retriever" | "guardrail" | "other";

type ToolCallView = { name: string; argsCanonical: unknown; argsHash: string };

type TrajectoryStep = {
  spanId: string;
  parentSpanId: string | null;
  kind: StepKind;
  name: string;                  // tool name / model name / node name
  toolCalls?: ToolCallView[];    // tool-call REQUESTS emitted by an llm step
  output?: unknown;
  status: "ok" | "error";
  level: "DEBUG" | "DEFAULT" | "WARNING" | "ERROR";
  startTime: string; endTime?: string;
  agentId?: string; turnId?: string; stepId?: string;
};

type Trajectory = { traceId: string; agentRunId: string; steps: TrajectoryStep[] };

type ReferenceTrajectory = Trajectory & {
  matchMode: MatchMode;          // strict | unordered | subset | superset
  toolArgsMode: ArgsMode;        // exact | ignore | subset | superset
  perToolOverrides?: Record<string, ArgsMode>;
};
```

`buildTrajectory(spans): Trajectory` is the single builder (lives in doc 03). The matcher signature is `diffTrajectory(produced: Trajectory, reference: ReferenceTrajectory): TrajectoryDiff`.

### 7.3 `argsMatch` and `diffTrajectory`

- `argsMatch(produced, reference, mode)`: `exact` = deep-equal of canonical JSON; `ignore` = `true`; `subset` = produced ⊇ reference (every ref key/value present in produced); `superset` = reference ⊇ produced. `numeric_tolerance` comparator: `|a−b| ≤ tol`. Per-tool override and per-field exact lists apply before the mode.
- `diffTrajectory`: align produced vs reference steps by **LCS over identity key = `(kind, name, argsHash-for-tools)`**, then for each matched pair apply `argsMatch` + output assertions. Report `{ missingSteps, extraSteps, argMismatches, outputFailures }`. Mode semantics: `strict` = same steps, same order, allowing content diffs; `unordered` = same tool-call multiset, any order; `subset` = no extra tools beyond reference; `superset` = all reference tools present, extras allowed.

### 7.4 Replay shim (the determinism boundary)

```ts
interface FixtureEntry { keyHash: string; request: unknown; response: unknown; stream?: unknown[] }
interface FixtureBundle { tools: Record<string /*toolName*/, FixtureEntry[]>; llm: FixtureEntry[] }

interface ReplayShim {
  install(opts: { fixtures: FixtureBundle; mode: "record" | "replay" }): Disposable;
}

function canonicalHash(args: unknown): string; // RFC8785 canonical JSON → sha256
```

- **Lookup key** = `canonicalHash(args)`. Repeated identical calls consume successive `FixtureEntry`s from the per-key queue (supports N identical tool calls and concurrent calls within a step).
- **Streaming** LLM responses: replay concatenates `stream[]` chunks (and re-emits them as a stream if the caller streams).
- **Adapters** (one per framework, ship LangGraph first): LangGraph wraps `ToolNode` + `BaseChatModel.invoke/stream`; OpenAI Agents SDK patches tool executors + the model client; Agno wraps tool + model callables; custom frameworks use the Tracely SDK's `wrapTool()` / `wrapModel()` or an OTLP-aware HTTP proxy.
- **record mode** captures fixtures live (used to build a case from a trace when raw IO wasn't retained); **replay mode** is the CI default.

### 7.5 Baseline + `decide_gate` read path

- **Baseline** = the AgentVersion currently deployed at `env=prod` for the agent. Its reference results = that version's **most recent green GateRun on the overlapping suites** (query: latest `GateRun` with `status=PASS` and `agentVersionId = baselineVersionId` covering the same `selectedSuiteIds`).
- Per-case baseline verdicts are read from that GateRun's **`GateCase` rows** (Postgres).
- Aggregate eval scores are read from ClickHouse: `SELECT name, avg(value) FROM scores WHERE gate_run_id = ? GROUP BY name`.
- `decide_gate` combines: (1) regression — every selected `PROMOTED` case's `GateCase.verdict` must be `PASS` (fail-to-pass); (2) eval thresholds — absolute + delta-vs-baseline; (3) cost delta; (4) latency delta. **Only (1) is a hard gate by default**; (2)–(4) are configurable and start as warnings.

### 7.6 First-failing-step tie-break

Among `level=ERROR` spans within a run (`agent_run_id`): pick **min depth (shallowest)**, then **min `start_time` (earliest)**, then lexicographically smallest `span_id`. For linked cross-service sub-agent runs, the child run's first-failing-step rolls up to its `SubAgentCall` edge in the parent.

### 7.7 Run-list reads (no AggregatingMergeTree)

Do **not** add an `AggregatingMergeTree` rollup for the run list/dashboards (Langfuse tried trace-rollup AMTs and reverted — see `part1-langfuse/03` and `01-steal-and-do-not-copy.md §B7`). Use an `events_core`-style lightweight projection MV (truncated IO) for lists + read-time `LIMIT 1 BY` / `argMaxIf` for run aggregates.

---

## 8. Resolution log (the 16 conflicts)

| # | Conflict | Decision |
|---|---|---|
| 1/3-store | `AgentRun` Postgres model (doc 02) vs ClickHouse-only (03/09) | **ClickHouse-only.** Delete `model AgentRun` from doc 02. |
| 2 | `AgentVersion` id: `configHash` vs `fingerprint` | **`configHash`** (doc 08 formula, §7.1). Rename doc 06 `fingerprint→configHash`. |
| 3 | `GateRun` shape (3 variants) | **Adopt doc 08:** `agentVersionId` + `baselineVersionId` + `selectedSuiteIds[]`. Delete doc 03 & doc 06 variants. |
| 4 | `GateCase` table vs scores-only | **Keep Postgres `GateCase`** for per-case verdict/cost/latency; detailed scores still also land in CH `scores` (with `gate_run_id`). Add `gate_cases` to doc 09. |
| 5 | `EvaluationCase` shape (`slug` vs `level`+`inputDigest`) | **Add `level`; key on `@@unique([projectId, agentId, inputDigest])`; drop `slug`** (use non-unique `title`). |
| 6 | `CaseStatus` (3 sets) | **`{DRAFT, PROMOTED, QUARANTINED, ARCHIVED, UNREPRODUCIBLE}`** (§3). |
| 7 | `CaseOrigin` (3 sets) | **`{PROMOTED_CLUSTER, MANUAL, GENERATED}`**; author in `createdBy`. |
| 8 | `Agent` key (`slug`/`key`/`name`) | **`slug`** (`@@unique([projectId, slug])`); `tracely.agent.id` carries slug. |
| 9 | `AgentKind` (2 sets) | **Two fields:** `kind {SINGLE,MULTI_AGENT,WORKFLOW}` + `role {SUPERVISOR,WORKER,PLANNER,EXECUTOR,GENERIC}`. |
| 10 | `FailureCluster` key + member table name | Key `@@unique([projectId, agentId, clusterKey])` with `clusterKey = drainTemplateId + ':' + (bertopicTopicId ?? 'none')`; keep both source columns. Member table = **`ClusterMember`**. |
| 11 | pgvector 384 vs 1024 | **`vector(1024)`** everywhere; one table `ClusterMember`. |
| 12 | Trigger queue (3 names) | **`AgentRunComplete`.** |
| 13 | Replay/gate queue (4 names) | **`ReplayQueue`** (per-case) + **`GateRunQueue`** (orchestrator). |
| 14 | Score verdict (`PASS_FAIL` data_type vs `verdict`) | **`verdict` column** `{PASS,FAIL,SKIP}`; do not add `PASS_FAIL` to `data_type`. |
| 15 | Suite membership (FK vs join) | **`EvaluationSuiteCase` join table** (many-to-many + `pinnedCaseVersion`). |
| 16 | `env` vs `environment` | **Add `env` enum column** (gating axis); keep `environment` (OTel compat). |

**Thesis-drift fixes:** drop dataset `experiment_*` columns and `prompt_*` columns from the `events` table (§5); no AggregatingMergeTree run-list rollup (§7.7); cost/latency gates default to warnings, regression fail-to-pass is the only hard gate (§7.5).

**Concreteness fills:** `config_hash`/graphHash serialization (§7.1); canonical `Trajectory` type (§7.2); `argsMatch`/`diffTrajectory` (§7.3); replay shim interface (§7.4); baseline read path (§7.5); first-failing-step tie-break (§7.6); `failure_signals` ClickHouse table is added to doc 09's inventory.
