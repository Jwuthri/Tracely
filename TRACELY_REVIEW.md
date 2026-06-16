# Tracely — Product & Engineering Review (re-verified)

> Original review: **2026-06-13** (deep audit across frontend / backend / workers / SDK / infra / docs + a live walkthrough).
> Re-verified against the codebase: **2026-06-15**. Every claim below was re-checked against current `file:line`; items that have since been fixed are struck through and moved to **§0a Resolved**, with the remaining work kept in **§5**.
>
> You asked for no sugar-coating, and for the outdated parts to be removed. This version keeps the harsh-but-true analysis and deletes/annotates what's no longer accurate.

---

## 0a. Resolved since the original review (verified 2026-06-15)

The category-defining gaps from the first review have largely been closed. Verified in code:

| # | Original finding | Status | Evidence |
|---|---|---|---|
| 1 | **False-green gate** — all-SKIP returned PASS | ✅ Fixed | `_final_status` returns `NO_COVERAGE` when `passed==0 and total>0`; `gate_require_full_coverage` flag for partial coverage (`gate_service.py`, `config.py:89-93`). CLI exits non-zero on any non-PASS. |
| 2 | **Gate only caught crashes, not bad answers** | ✅ Fixed | Judge-in-the-gate: quality judges graded at promote (`regression_service.py:98-100`) and re-graded on the replayed answer at gate time (`gate_service.py:176-203`, `gate_quality_blocks`/`gate_quality_score_name` in `config.py:94-104`). |
| 3 | **Three contradictory FAIL computations** | ✅ Fixed | Unified into one `advisory`-aware policy (`domain/.../verdict.py` `is_failing`/`rollup_verdict`); list, trace-detail and session all pass the same advisory set (`async_reader.py`, `traces.py:62`, `sessions.py:62`). |
| 4 | **Fake eval cost/scope knobs** (`sampling`/`target_agent`/`target_env` stored but never read) | ✅ Fixed | Wired into the runner: `_apply_targeting` → `spec_applies` honors agent/env/deterministic sampling (`evaluation_service.py:241-262`, `domain/.../targeting.py`). |
| 5 | **Leaked ClickHouse async client / no lifespan / fake healthcheck / unconfigured logging** | ✅ Fixed | Pooled+closed client (`client.py`, lifespan in `main.py:37-45`); `/health` probes ClickHouse+Postgres → 503 (`health.py:23-46`); `configure_logging()` + global exception handler + request-id contextvars (`log_config.py`, `main.py:61-77`). |
| 6 | **No CI** | ✅ Fixed | `.github/workflows/ci.yml`: ruff + pytest, frontend build, prod Docker builds, `pip-audit`/`pnpm audit`. |
| 7 | **No error/loading states** (outage looked like empty) | ✅ Fixed | `app/(app)/error.tsx`, `loading.tsx`, `not-found.tsx`; **and** `lib/api.ts` no longer swallows failures into empty arrays (see §0b). |
| 8 | **Eval columns clipped off-screen** | ✅ Fixed | Table sits in `overflow-x-auto` and scrolls. |
| 9 | **No judge-vs-human calibration** | ✅ Fixed | `score_annotations` (migration 0013), pure `domain/evaluation/calibration.py`, `/calibration` page. |
| 10 | **Right half of the product empty in the demo** | ✅ Largely fixed | `make seed-regression` + `seed_demo.py` now promote a failing trace and run a red→green gate, so Cases/Gates are populated. (Runtime "is it seeded in *this* instance" is an ops step, not a code gap.) |
| 11 | **Eval token/cost not tracked at all** | ◑ Partial | Per-grade token usage now captured in score metadata (`score_writer.py:35-44`, `EvalResult.usage`). The `execution_trace_id` "evals are themselves traced" column is still never populated. |
| 12 | **`acks_late` missing on Celery** | ✅ Fixed | Set in `celery_app.py` (plus `visibility_timeout`/time-limits added this pass — §0b). |

## 0b. Fixed in this pass (2026-06-15)

Code-level remediation of the still-valid findings (tests green: 206 backend, 22 SDK, ruff clean, `tsc` clean):

- **OTLP ingest size cap** — `/v1/traces` rejects bodies over `max_ingest_bytes` (default 16 MiB) with 413, via a cheap Content-Length pre-check + a hard check on the read bytes (`otlp.py`, `config.py`).
- **CORS gated on env** — the permissive `http://localhost:*` regex is dropped when `TRACELY_ENV` is prod (`main.py`).
- **ClickHouse retention** — 90-day TTL on `events` (by `start_time`) and `scores` (by `created_at`), in the CREATE DDL **and** as idempotent `ALTER … MODIFY TTL` migrations for existing tables (`ddl/0001`,`0002`,`0003_events_ttl`,`0004_scores_ttl`).
- **Atomic promote** — `promote_trace` is now one transaction (helpers `flush`, single `commit`, ClickHouse score write moved after the commit); a crash mid-promote rolls back instead of leaving a half-promoted case (`regression_service.py`).
- **Atomic cluster replace** — `_replace_with_issues` no longer commits between the delete and the re-insert, closing the window where a project had zero clusters / a crash wiped all promote/ignore state (`failure_intel_service.py`).
- **Celery durability** — `visibility_timeout=3h` (stops long tasks double-running under `acks_late`) + `task_time_limit`/`task_soft_time_limit` (`celery_app.py`).
- **Honest step-judge coverage** — a capped step judge now appends `[coverage: graded N of M steps; …]` to each result instead of silently dropping the tail (`llm_judge.py`).
- **Fetch failures surface** — `lib/api.ts` throws `ApiError` on non-2xx (→ `error.tsx`); detail-by-id returns `null` only on 404 (→ `notFound()`). Genuinely-empty (200 + `[]`) still renders the empty state.
- **`window.alert` removed** — `PromoteButton`/`RunGateButton` show an inline `role="alert"` message and handle network errors (`finally`-reset busy state).
- **SDK PII redaction** *(the headline new feature)* — `tracely.init(redact=…)` scrubs sensitive content at the export chokepoint, so it covers **both** manual `set_io`/metadata **and** zero-touch auto-instrumentor prompts/completions/args. `redact=True` applies built-in PII patterns (email/SSN/credit-card/phone); a list of regexes or a `(key,value)->value` callable give full control. New `sdk/tests/test_redaction.py`.
- **Doc/dead-code** — fixed the `wrap_with_score` phantom in `backend/README.md`; removed the empty `tracely/ingestion/` package.

---

## 1. Interface — is what you see connected to the backend?

**The Observe → Detect → Triage path is genuinely connected, not faked** (unchanged from the original — still true and still your best demo surface):

- Real traces produce real conversation-level judge verdicts (`goal_success`, `trajectory`, `frustration`) with real rationales.
- Failure clusters are mechanism-focused and specific ("the agent asserts real-time facts without showing tool usage") — the most impressive product surface.
- Dashboard / trends / per-trace badges all reflect the same ClickHouse scores.

~~The eval columns are clipped off-screen~~ → fixed (`overflow-x-auto`). ~~A backend outage renders as "No traces yet"~~ → fixed (`error.tsx` + `lib/api.ts` throws). ~~Errors use `window.alert()`~~ → fixed (inline alerts).

**Still worth doing (information hierarchy):** the eval pills are the product — they should be visible *by default* and pinned to the left of the message dump, not relegated to a horizontal scroll. The `useWide` `734px/292px` negative-margin breakout is still a magic-number band-aid (`useWide.tsx`).

---

## 2. The Evaluator-column feature (the main business)

### 2a. Genuinely good (unchanged)
One LLM-provider seam (`provider.py`), registry dispatch, one judge class branching on level; idempotent UUID5 scores under `ReplacingMergeTree`; runtime enum→`Literal` enforcement; excellent library UX (Browse / Manual / Use-AI, 23 templates); fault isolation; the SSE on-demand run.

### 2b. Correctness — mostly resolved
- ~~Three contradictory FAIL computations~~ → ✅ unified (§0a #3).
- ~~Pill headlines the wrong field / needs `display_field`~~ → behavior is now the intentional "iterate the user's schema fields in order" (the user defines the output schema they want shown); **not a bug**.
- **Still true:** several catalog templates ship a `threshold` with **no score field** (`tracely.run.reask`, `tracely.run.correction`, step `analysis`/`self_correction`) → the threshold is dead config; those columns are informational. Either give them a score field or drop the threshold.
- ~~`backend/README.md` documents `wrap_with_score` (doesn't exist)~~ → ✅ fixed this pass.
- **Still true (by design, but the modal copy oversells it):** sequential/chained metrics inject `__previous_result__` only on the on-demand thread path, not on ingest — so a chained metric can score differently auto vs. on-Play.

### 2c. Business-critical gaps
- ~~Can't control eval spend (fake sampling/targeting)~~ → ✅ wired (§0a #4).
- ◑ **Eval cost/latency:** per-grade tokens are now captured (§0a #11); still missing a per-evaluator **$/1k-traces** surface, and `execution_trace_id` is still never written.
- **Still true:** no duplicate-call guard — an ingest auto-run + a manual re-run seconds apart make the same LLM calls twice (idempotent *writes*, not a request cache keyed on `(score_name, model, prompt_hash, content_hash)`).
- ~~Step-judge silently truncates at 30~~ → ✅ now surfaces an explicit coverage note (this pass). A "grade all / raise the cap" control is still future work.
- ~~`evaluator_suggestion.py` emits an unusable code shape~~ → it now returns a config dict the Add-Column editor consumes; **not dead**.

### 2d. What competitors still have that you don't (re-prioritized)
- ✅ **LLM-judge in the gate** — shipped (§0a #2).
- ✅ **Judge-vs-human calibration** — shipped (§0a #9).
- **Cheap/fast default judge + caching** — partly addressed (token capture, small default `llm_judge_model`); still no request-level cache, no sampling-cost surface.
- **Datasets / A-B experiments over a promoted-case set** — still absent (stay on-thesis: a "dataset" = promoted production cases with per-case deltas).
- **Monitors / alerting** on metrics already in ClickHouse — still absent.
- **Pairwise / preference judging** — still absent.
- **Eval versioning** (record producing-config on score rows) — still absent.

---

## 3. Competitive reality check (still accurate as context)

The 2025-26 market moves the original review flagged still stand and still matter:

- **Langfuse acquired by ClickHouse (Jan 2026)**, migrating to wide-table modeling — the substrate you fork is now a funded competitor's roadmap. ([ClickHouse blog](https://clickhouse.com/blog/langfuse-llm-analytics))
- **LangSmith (Oct 2025):** Insights Agent (auto failure-clustering) + online multi-turn trajectory evals — overlaps your Detect *and* Triage. ([LangChain blog](https://www.langchain.com/blog/insights-agent-multiturn-evals-langsmith))
- **Langfuse (May 2026):** a PR-blocking CI gate — but **dataset-first**, not production-trace-replay. ([changelog](https://langfuse.com/changelog/2026-05-25-experiment-ci-cd-gates))
- **Braintrust:** production-failure → clustered regression with per-case PR comments.

**Still-defensible wedge (lean in):** hermetic replay of the *exact failure trajectory* (including the tool that errored) as the gated artifact, bound to a content-addressed agent version, **with the LLM-judge in the gate** — and that last clause is now *true in code*, not just on the roadmap. A dataset row cannot express "this specific trajectory, with the tool that timed out, must not recur."

**Stop claiming:** "nobody does regression-from-production" (false now) and "trace as source of truth" as a category claim (mainstream). The durable sentence is the narrow one: *hermetic-trajectory replay vs. dataset-row replay, judge-gated, version-keyed.*

---

## 4. Architecture & code quality

### 4a. Backend
**Good (unchanged):** real DDD layering; the two hard rules hold; parameterized ClickHouse; blob-first ingest; disciplined migrations; one validated settings model.

Resolved: ~~leaked CH client~~, ~~no lifespan~~, ~~fake `/health`~~, ~~no logging/exception handler~~ (§0a #5); ~~always-on CORS~~ (gated on prod this pass); ~~multi-commit `promote_trace` / `_replace_with_issues`~~ (single-transaction this pass).

**Still true:**
- The **two-session-world** (async auth sessions vs. sync `SyncSessionLocal` + threadpool in data routers) is intentional but remains the highest-leverage refactor; the sync routers share the default anyio threadpool with SSE eval runs.
- **Eval-on-ingest is still a blind `countdown=4`** (`tasks.py`) with no "trace complete" signal — a slow agent whose spans arrive >4s apart is scored on a partial trace.

### 4b. Frontend
**Good:** SSR + secret-keeping proxy; high TS hygiene; SSE decoder; portal panels; specific empty states.

Resolved/in-flight: error/loading boundaries + non-swallowing fetch (this pass); the **`TraceTable.tsx` god component is being split** — a `trace-table/format.ts` module + a `__tests__/` vitest suite landed concurrently (the review's P2 split + "zero frontend tests" are being addressed). Confirm the split fully removes the in-file duplicates of `fmtMs`/`msgRole`/etc. and that the shared module is consumed by `IO.tsx`/`JsonView.tsx` too.

**Still true:** nothing in the row tree is `React.memo`'d → a single SSE eval run re-renders every cell; accessibility is thin (modals aren't focus-trapped dialogs, rows are mouse-only, dropdowns lack `role="menu"`); `agent="planner"`/`env="ci"` hardcoded as the gate target.

### 4c. SDK + replay
**Good (strongest engineering in the repo):** context-stamping `SpanProcessor`; broad auto-instrumentation with LangChain de-dup; multi-vendor I/O normalization; the record→`ToolError` replay seam.

Resolved: ~~all-SKIP passes the gate~~ (§0a #1); ~~no PII redaction~~ (added this pass — covers auto + manual at the export layer).

**Still true:**
- **Auto-instrument and hermetic replay are different styles.** A customer who used `instrument="auto"` gets faithful *recording* but cannot replay hermetically (their code makes real calls; OpenInference instrumentors aren't intercepted by `fixtures()`). Either ship a fixture-serving shim or document the manual-seam requirement + a migration recipe.
- **Fail-to-pass wedge is narrow.** Promotion validates missing/errored tools; `tool_args_mode="exact"` is stored but **never enforced** (`contract.py`, `regression_service.py:202`). A wrong-arg trace can't become a discriminating case.
- **Brittle CI timing** — `--cmd` replay still `time.sleep(8)`; `--entrypoint` proceeds after a 45s poll even on timeout.
- **Loose version pinning** — provider extras are unbounded. *(Nuance the original missed: the OpenInference instrumentors are now a mix of pre- and post-1.0 — anthropic 1.0.6, crewai 1.1.9, mistralai 2.0.4, etc. — so a blanket `<1.0` cap would break resolution; pins must be per-package against the current major.)*
- Minor: LLM fixture entries are written as `"input"` but read as `"args"` (`fixtures.py:73`) — currently harmless because LLM replay is order-matched, not arg-matched; latent if arg-keyed LLM replay is ever turned on.

### 4d. Infra
**Good:** best-in-class local docker-compose dev loop; real Railway deploy story; sound ClickHouse fundamentals.

Resolved: ~~no CI~~ (§0a #6); ~~fake healthcheck~~ (§0a #5); ~~no `acks_late`~~ / no visibility-timeout (this pass); ~~no ClickHouse TTL~~ (90-day TTL this pass).

**Still true (mostly ops, not code):**
- **No backups** — no `pg_dump`/`clickhouse-backup`/MinIO replication/volume snapshots. **P0 for any real customer.**
- **Zero self-observability** — no Sentry, no metrics, no Flower.
- **Solo Celery worker** (`--pool=solo`, single replica) — the load ceiling; split queues (ingest vs eval vs rebuild) + add replicas.
- **No dead-letter path**; Redis `noeviction` + no persistence → a restart drops in-flight work.
- **No `OPTIMIZE FINAL` schedule** (reads use `FINAL`; latency degrades between merges).
- **`tracely_dev_key` seeded into every deploy** and `AUTH_MODE=dev` is the default → a fumbled deploy runs wide open.

---

## 5. Prioritized remaining work

### P0 — data-loss / false-confidence (ops + code)
- [ ] **Back up Postgres + MinIO + ClickHouse** (volume snapshots + scheduled `pg_dump`/`clickhouse-backup`). Highest-leverage infra fix.
- [ ] **Don't ship `AUTH_MODE=dev` + the well-known `tracely_dev_key` to prod** — fail fast (or rotate) when env is prod.

### P1 — make it operable / true
- [ ] **Bridge auto-instrument → hermetic replay** (fixture-serving shim) *or* document the manual-seam requirement + migration recipe. *(Biggest honesty gap left in the thesis.)*
- [ ] **Scale the worker off `--pool=solo`** + split queues + add a dead-letter path; Redis persistence/eviction policy.
- [ ] **Self-observability:** Sentry (FastAPI + Celery), basic metrics, Flower.
- [ ] **Replace the blind `countdown=4`** eval-on-ingest with a trace-complete signal (debounce on last-span-seen).
- [ ] **`OPTIMIZE FINAL` schedule** to complement the new TTL.
- [ ] **Eval $/1k-traces surface** + a duplicate-call cache keyed on `(score_name, model, prompt_hash, content_hash)`; populate `execution_trace_id`.

### P2 — correctness polish / maintainability
- [ ] **Enforce `tool_args_mode="exact"`** (or stop storing it) to widen the fail-to-pass wedge to wrong-arg traces.
- [ ] **Finish the `TraceTable.tsx` split** (in flight) — ensure `IO.tsx`/`JsonView.tsx` consume the shared `trace-table/format` module; memoize the row tree.
- [ ] **Per-package SDK version caps** (against current majors — not a blanket `<1.0`).
- [ ] **Catalog templates:** give threshold-only templates a real score field or drop the dead threshold.
- [ ] **Migrate data routers off `SyncSessionLocal`+threadpool** onto the async engine (collapses the two-session-world + the threadpool ceiling).
- [ ] **Make eval pills visible by default**, pinned left of the message dump; replace the `useWide` magic-number breakout.
- [ ] **Accessibility:** dialog focus-trap, keyboard rows, `role="menu"` dropdowns.
- [ ] **Fix `OVERVIEW.md` drift** (still describes the old flat `evaluators.py`/`fi.py`/`cluster.py` layout and "no evaluator management UI yet").
- [ ] **Add backend tests** for `GateService` / `promote_trace` / the ClickHouse readers-writers (still the least-tested, scariest code).

---

## 6. What to build next (still on-thesis)

1. **"Re-break it" demo** — change a prompt → push → gate blocks the PR with a step-aligned trajectory diff. The one thing no dataset-first competitor can reproduce; make it the *first* thing anyone sees. (Seeding is now in place via `seed_demo.py`.)
2. **Zero-config GitHub App** — auto-detect the agent, post the check; removes the workflow-file + secrets + manual-seam friction.
3. **Monitors + Slack/webhook alerts** on the regression-loop metrics already in ClickHouse (failure-rate spike, gate pass-rate drop, MTTR).
4. **Promoted-case "compare versions" view** — run the suite across agent v12 vs v13, per-case deltas — the on-thesis answer to "is B better than A?" without building the dataset pillar.
5. **Eval cost dashboard** — per-evaluator $/1k traces with sampling enforcement (turns the cost work into a selling point).

---

> **Bottom line.** The three category-defining moves from the original review have shipped: the gate is honest (no more false-green, judge-in-the-gate), the moat is visible and seeded, and the eval feature is trustworthy (unified FAIL + calibration + real sampling). This pass closed the remaining correctness/durability quick-wins (atomic writes, retention, ingest cap, redaction, honest coverage). What's left is mostly **operability** (backups, worker scaling, observability) and the one honest thesis gap — **auto-instrument → hermetic replay** — plus finishing the frontend split that's already underway.

---

## 7. Sequencing — what's underway vs. queued (2026-06-15)

**In flight (this arc, branch `feat/monitors-and-cost-dashboard`):**
- **§6 #3 Monitors + alerts** — threshold rules over the regression-loop metrics already in ClickHouse (fail-rate spike / pass-rate drop over last N traces), Slack + generic-webhook sinks, evaluated periodically and dedup'd per alert.
- **§6 #5 Eval cost dashboard** — extends the `provider.on_usage` → `scores.metadata` capture into per-evaluator **$ math** (OpenRouter `/models` already returns per-model prompt/completion pricing; the cache just needs to keep it), **$/1k-traces** view in `/trends`, and a per-judge chip in the Columns menu.

**Next (after the arc above):**
- **§5 P1 — Auto-instrument → hermetic replay bridge.** A fixture-serving shim that intercepts OpenInference instrumentor exits inside an active `fixtures(...)` context and substitutes recorded outputs for the real network call. Closes the one remaining "README oversells" claim. Touches every provider — scoped, multi-day work.

**Queued (will land after the honesty gap):**
- **§6 #1 — "Re-break it" demo.** A 60–90s scripted flow (modify prompt → push → gate blocks with a step-aligned trajectory diff). Lands on the landing page and as the first step in `/onboarding`. Make it the *first* thing a visitor sees. The seeding (`seed_demo.py`) is already in place.
- **§6 #2 — Zero-config GitHub App.** Register the App; on Install, auto-detect the agent (look for `tracely.toml` or sniff for `tracely_sdk` usage), inject the workflow via the App's contents API, post the check via the App token. Removes the workflow-file + secrets + manual-seam friction from adoption.
