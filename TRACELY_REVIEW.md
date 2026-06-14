# Tracely — Brutally Honest Product & Engineering Review

> Review date: **2026-06-13** · Reviewer: deep audit across frontend / backend / workers / SDK / infra / docs, plus a live walkthrough of the running app at `localhost:3001` (local `AUTH_MODE=local`, the seeded **Default** project: 16 traces, 119 spans, 19 clusters).
>
> Method: six parallel subsystem audits (eval pipeline, backend architecture, frontend, SDK+ingest, infra/devops, competitive landscape) + 12 full-page screenshots of the live UI + first-hand verification of the load-bearing claims against source. Every sharp claim below is cited to `file:line` or a screenshot.
>
> You asked for no sugar-coating. This document is written that way on purpose. The bones are genuinely good — that's *why* it's worth being harsh about the gaps.

---

## 0. TL;DR — the ten things that actually matter

1. **The moat is invisible in your own product.** The live app shows the *commoditized* half — trace explorer + failure clusters ("another Langfuse") — fully populated and polished. The *differentiated* half — promote → hermetic replay → CI gate — is **empty: 0 regression cases, 0 gate runs, 0% gate pass-rate** (screenshots `06-cases`, `07-gates`, `08-trends`). A visitor sees exactly the thing you say you're *not*.
2. **The gate has a false-green bug that defeats its entire purpose.** If CI emits no matching traces, every case SKIPs and the gate returns **PASS** (`gate_service.py:200` — `_final_status` never receives `skipped`). A merge-blocker that passes when it tested nothing is worse than no gate.
3. **The gate only catches crashes, not bad answers.** Fail-to-pass validation only fires for missing/errored tools (`regression_service.py:126-141`); a hallucination with a clean trace **cannot be promoted**. Your headline ("the recorded run *is* the test") is half-true until the LLM-judge is wired into replay.
4. **The flagship feature — "evaluators as columns" — is literally pushed off the right edge of the screen** in every view (screenshots `02`, `03`, `04`: the metric column reads "METR…" cut off). The main business is the least visible thing in the UI.
5. **The eval feature has correctness bugs that make the UI contradict itself.** The same trace shows a **green dot in the list but "EVALS FAIL" on the detail page** (three different FAIL computations: `async_reader.py:26` vs `traces.py:60` vs `sessions.py:52`). JSON-judge results can show a pill value that differs from what the judge actually computed.
6. **You can't control eval cost or scope — the knobs are fake.** `sampling`, `target_agent`, `target_env` are stored, shown in the UI, and **never read by the runner** (`repositories.py:114-149`). There is **zero** cost/token/latency tracking on judge calls. For a product whose business is "judges on every ingest," this is the gap.
7. **The competitive moat narrowed materially in the last 9 months.** Langfuse was **acquired by ClickHouse** (Jan 2026) and is moving to the exact wide-table substrate you fork; **LangSmith shipped auto failure-clustering + online multi-turn trajectory evals** (Oct 2025); **Langfuse shipped a PR-blocking CI gate** (May 2026). Your "nobody does production→regression" framing is now refutable.
8. **Architecture is real, not theater — but the operational seams are dangerous.** Clean DDD layering, the two hard rules hold. But: a ClickHouse async client **leaked on every request** (`client.py:30`), **no app lifespan/shutdown**, a **fake healthcheck** (`health.py` returns static `ok`), unconfigured logging, always-on permissive CORS, and multi-commit operations that leave half-written state.
9. **It demos; it will not survive production.** Single replica of everything, **zero backups**, **zero self-observability** (no Sentry/metrics), **no ClickHouse TTL** (unbounded growth), **solo Celery worker** with no replicas, no payload-size limit on ingest, no PII redaction in the SDK.
10. **The SDK and ingest/normalization layer are the strongest part of the codebase** — context-stamping span processor, blob-first durability, genuinely impressive multi-vendor message normalization. Lead from this strength.

### Scorecard

| Area | Grade | One-line |
|---|---|---|
| Product thesis & positioning | **B−** | Real wedge, but narrowing fast and half-invisible in the app |
| Eval feature (main business) | **C+** | Good bones; correctness bugs + no cost control + no calibration |
| Interface / UX | **C+** | Right concept, buries the payload, no error states |
| Backend architecture | **B** | Clean layering; dangerous infra seams |
| Frontend code quality | **C+** | 1942-line god component, 0 tests, 0 error states; great TS hygiene |
| SDK + ingest / mapping | **B+** | The best-engineered part of the stack |
| Replay + gate (the moat) | **C** | False-green bug, narrow wedge, auto/replay mismatch |
| Infra / deployability | **C−** | Single-everything, no backups, no observability |
| Testing | **C** | Domain + auth well-tested; infra/services untested |
| Docs | **B−** | Excellent OVERVIEW, drifted from the code |

---

## 1. Is this the optimal interface? Is what you see actually connected to the backend?

**Short answer: the data is genuinely connected, the *information hierarchy* is wrong, and the half of the product that matters isn't shown at all.**

### 1a. What's connected (and it's real)

The Observe → Detect → Triage path is coherent and live, not faked:

- Real traces produce **real scores**. The seeded `manual_spans.py` thread carries live conversation-level judge verdicts — `tracely.conv.goal_success` = **FAIL 0.5** with a real reason ("did not confirm the coat's back-in-stock status"), `trajectory` = 0.55, `frustration` = PASS. That's the judge actually grading the agent's answer against its tool results.
- Real clusters are **mechanism-focused and specific** (screenshot `05-clusters`): "*The agent claims specific real-time facts… without showing any tool usage*", "*The answer simply repeats the user's question*", "*FAIL: the agent asserted the coat's back-in-stock status without tool evidence*". This is the single most impressive *product* surface — it's the kind of output that makes someone go "oh, it actually understood the failure." 19 distinct, readable issues from 16 traces.
- The dashboard, trends, and per-trace verdict badges all reflect the same underlying ClickHouse scores. The wiring is honest.

> ✅ **Verdict on "connected":** Observe/Detect/Triage are well-connected and trustworthy. The clusters page is your best demo asset.

### 1b. The buried-payload problem

The interface concept is right: a hierarchical **conversation → turn → step** table with **evaluators as columns** on the right. That's the correct mental model and nobody else nails it.

But the execution buries the thing you're selling:

- **The eval columns are off-screen.** In the traces list (`02`), the visible columns are Conversation / Datetime / Duration / Summary — and the metric columns are pushed past the right edge. On the trace detail (`03`) and session (`04`) the metric column is literally rendered as "METR…", cut off. Your **main business feature is the least visible element on every screen.** A new user does not see the evals unless they go hunting (Columns toggle / "Enlarge" breakout).
- **The summary column eats the width** with the full assistant message, so the high-value, at-a-glance signal (the pass/fail metric pills) loses the layout fight to a low-value text dump.
- The **"Enlarge"** affordance (a `calc(734px - 50vw)` negative-margin breakout, `useWide.tsx:7`) exists *because* the table is too wide for the content column — that's a band-aid over an information-hierarchy problem, and it's built on hardcoded magic numbers that silently break if the sidebar width changes.

> 🔧 **Fix the hierarchy, not just the CSS:** the eval pills are the product. They should be visible by default, pinned, and to the left of the message dump — not the last thing to render and the first to clip.

### 1c. The empty-moat problem (the big one)

Walk the sidebar in the live app top-to-bottom and watch the product evaporate:

| Stage | Sidebar | Live state |
|---|---|---|
| Observe | Traces, Trends | ✅ 16 traces, full |
| Detect | (automatic) | ✅ scores on every run |
| Triage | Failure clusters | ✅ 19 issues, excellent |
| **Test** | **Regression cases** | ❌ **"No cases yet"** (screenshot `06`) |
| **Ship** | **CI gates** | ❌ **"No gate runs yet"** (screenshot `07`) |

The Trends page makes it official: **Gate pass-rate 0% · 0 gate runs · 0 regression tests** (screenshot `08`).

This is the crux of your own question — *"does what we see and what happens in the backend really connect?"* Observe/Detect/Triage: yes. **Test/Ship: there's nothing to see.** The differentiated half of the product — the only half competitors don't have — is invisible in your own running instance. Combined with the gate bugs in §4c, the moat is simultaneously (a) not demonstrated, (b) narrower than pitched, and (c) partially broken.

> 🚨 **If a customer or investor opened this app right now, they would conclude you built a (very nice) Langfuse clone.** The wedge only exists in the README and the design dossier. Seed `seed_regression.py` into the default project so the right half is always populated, and make the promote→gate loop the *first* thing the demo shows, not the last.

### 1d. Failure modes look like empty states

There is **no `error.tsx` or `loading.tsx` anywhere**, and every server fetch swallows failure into an empty array (`lib/api.ts:53,91,135,166`). So a backend outage renders as "No traces yet" — **indistinguishable from genuinely empty**. For an *observability* product, "the tool silently shows nothing when it's broken" is the worst possible failure mode. Errors that *do* surface use `window.alert()` (`PromoteButton.tsx:21`, `RunGateButton.tsx:21`), which is jarring and untestable.

---

## 2. The Evaluator Column feature (your main business) — deep dive

You asked me to spend the most time here. The good news: the bones are right and the library UX is your most polished surface. The bad news: it has correctness bugs that make the UI lie, it can't control its own cost, and it's missing the table-stakes credibility features every serious eval product ships.

### 2a. What's genuinely good

- **The architecture is the right shape.** One LLM provider seam (`provider.py` — LangChain v1 `create_agent` on OpenRouter, structured-output via pydantic), a registry dispatch (`evaluators/base.py:56-100`), one judge class that branches on `level` (CONVERSATION builds a thread transcript, AGENT_RUN grades request/answer/tool-grounding, SPAN grades each step). Clean, extensible, the hard rules hold.
- **Idempotent, deterministic scores.** UUID5 ids (`score_writer.py:78,81`) under ClickHouse `ReplacingMergeTree(event_ts)` mean re-runs replace in place — the linchpin that makes "re-evaluate live into the grid" work. This is correct and verified end-to-end.
- **Runtime enum enforcement** (`output_schema.py:30-32`): a JSON-schema enum compiles to a pydantic `Literal`, so a judge returning an out-of-vocabulary label is a validation error, not garbage. The notes say TurnWise dropped this — keeping it is a real quality edge.
- **The library UX is excellent** (screenshot `11`): templates grouped by level (Conversation / Message / Step), each with a description, a level badge, an LLM/SCHEMA type chip, and an `INSTALLED` flag. The 3-way entry — **Browse Library / Manual / Use AI** (screenshot `10`) — is exactly the right on-ramp. 23 templates including TurnWise ports (Sycophancy, Intent drift, Trajectory, Self-correction).
- **Fault isolation**: one bad evaluator can't sink the batch (`evaluation_service.py:242-245`); a judge transport error → skipped, not crashed.
- **The SSE on-demand run** (`/api/evaluations/run`) is the most sophisticated code in the backend — bounded concurrency, thread-offloaded sync engine, results marshaled back to the event loop, cancels cleanly on client disconnect. It streams scores into the grid live.

### 2b. The correctness bugs that make the UI lie (fix these first)

These are not style nits — they make what the user sees diverge from what was computed.

1. **Three contradictory FAIL computations.** The failing-dot in the list excludes exactly one hardcoded metric — `name != 'tracely.run.quality'` (`async_reader.py:26`) — but the trace-detail badge (`traces.py:60`) and the session verdict (`sessions.py:52`) count **all** FAILs. **Result: the same trace shows a green dot in the threads list and a red "EVALS FAIL" badge when you open it.** Worse, the "structural-only status" intent is fiction — it special-cases *one* seeded judge, so every *other* quality judge (helpfulness, tone, all 20+ library judges, any custom one) flips the list dot red anyway. → Unify into one policy. Make "counts toward the failing dot" a per-evaluator property (`config.gates: bool`), not a magic string.

2. **JSON-judge verdict can diverge from the displayed value.** The freeform JSON path name-plucks `parsed.get("score", parsed.get("overall_score"))` and clamps it to [0,1] (`llm_judge.py` `_json_result`). So a schema with a `score` field meaning a 1–5 rating gets silently clamped and drives a wrong PASS/FAIL — and the clamped pill value differs from the raw `score` shown in the JSON panel. Several catalog templates ship a `threshold` with **no score field at all** (`tracely.step.analysis`, `step.self_correction`, `is_reask`, `is_correction`) → the threshold is dead config; the column is silently informational despite advertising a pass/fail.

3. **The at-a-glance pill can headline the wrong field.** `jsonResultLabel` (`TraceTable.tsx:934-947`) shows "the first short string that isn't prose," so a result of `{sycophancy_detected: true, severity: "severe", type: "none"}` can render as `none` (whichever sorts first) — the cell contradicts the judge. → Let the schema declare a `display_field`.

4. **Doc/notes drift.** `backend/README.md:103` documents a `wrap_with_score` symbol that **doesn't exist**; internal notes describe a `score__`/`reason__` "envelope" that isn't in the tree. The JSON path still relies on name-plucking. Either ship the envelope or fix the docs — right now they describe code that isn't there.

5. **Ingest vs. on-demand give different answers.** Sequential ("chained") metrics only inject `__previous_result__` on the thread-run path (`evaluation_service.py:190-196`), not on ingest. So the same evaluator produces different scores depending on whether it auto-ran or you hit Play. The modal copy implies chaining always happens.

### 2c. The business-critical gaps

6. **You cannot control eval spend.** `sampling` / `target_agent` / `target_env` are columns (`models.py:283-285`), editable in the API, surfaced in the UI and the live JSON (`sampling:1.0` on every evaluator) — and **never read** by `evaluator_enabled_specs` (`repositories.py:114-149`). The model docstring literally claims "filtered by agent/env, sampled" — that is false. So every enabled judge runs on every trace, with no way to sample to 10% or scope to prod. This is a feature the UI *implies works*, which is worse than missing.

7. **Zero eval cost / latency / token tracking.** Grep the entire eval domain: no cost capture anywhere. The `scores` DDL even has an `execution_trace_id` column ("evals are themselves traced") that `write_eval_scores` never populates. You cannot answer "what does this column cost me per 1k traces" or "why is my OpenRouter bill huge." Every serious eval product (Langfuse, Braintrust) shows per-eval cost.

8. **No duplicate-call guard.** Idempotent *writes* save correctness, but an ingest auto-run + a manual re-run seconds apart make the **same LLM calls twice** and you pay twice. No cache keyed on `(score_name, model, prompt_hash, content_hash)`.

9. **Step-judge silently truncates.** `_run_steps` grades the first 30 spans (`max_spans`) and drops the rest with only a log line — a 200-step agent run is silently under-evaluated with no "30 of 200 graded" indicator.

10. **Dead/mismatched code.** `evaluator_suggestion.py` emits a `{name, language:"python", code}` shape that **no current executor consumes** and that can't be pasted into the Add-Column flow — leftover from a previous design.

### 2d. What competitors have here that you don't (prioritized)

This is where the eval feature is behind the market, ordered by leverage:

| # | Capability | Who | Why it matters for *your* business | Effort |
|---|---|---|---|---|
| 1 | **LLM-judge inside the gate** | LangSmith, Braintrust, Langfuse, Galileo | Converts the gate from "catches crashes" to "catches bad answers" — makes "the trace is the test" actually true. **Highest leverage.** | Med (judge engine exists; wire into replay + score-delta-vs-baseline) |
| 2 | **Judge-vs-human calibration** | LangSmith (single + pairwise) | Table-stakes *credibility*. Your own war-stories admit the judge is flaky; a buyer's first question is "how do I know the judge is right?" A focused "review N scored traces, override, see agreement %" view answers it. | Med (reuse the cluster-review UI pattern) |
| 3 | **Cheap/fast default judge + cost controls** | Galileo Luna-2 (−97% cost, sub-200ms), Opik | "Judges on every ingest" only pencils out with cheap judges + sampling + caching. Without this, the main business is uneconomic at volume. | Low (recommend a small default model, add caching + sampling caps) |
| 4 | **Datasets / experiments — A/B two prompts/versions over a set** | Everyone | Buyers always ask "is the new prompt better on these 50 cases?" You have no offline experiment surface. Stay on-thesis: a "dataset" = a materialized set of *promoted production cases*, with per-case deltas. | Med-High (resist building the full pillar) |
| 5 | **Monitors / alerting on the metrics you already compute** | Arize AX, Galileo, Opik | "Alert when agent X's `goal_success` drops below 0.7 over the last N traces." The data is in ClickHouse; there's no monitor layer. On-thesis (regression-loop health, not Datadog). | Low-Med |
| 6 | **Pairwise / preference judging** | LangSmith | The standard way to compare two agent versions' answer quality (with position-swap). Already specced in your dossier. | Low-Med |
| 7 | **Eval versioning** | Braintrust, LangSmith | Editing a column mutates `config` in place with no history, so you can't tell "scores moved because the prompt changed." | Low (add `version` + record producing-config on score rows) |

> 🎯 **The eval roadmap in one line:** make it **trustworthy** (calibration + unified FAIL + honest verdicts), **affordable** (cheap judge + real sampling + cost surfacing), then **comparative** (pairwise + promoted-case experiments). Trust first — nobody pays for a judge they don't believe.

---

## 3. Competitive reality check (Langfuse / LangSmith / Braintrust, 2025–2026)

You explicitly asked what Langfuse and others do differently. The honest summary: **the category moved under you in the last 9 months**, and your design dossier's competitive section (dated 2026-06-02) predates the two moves that matter most.

### 3a. What changed

- **Langfuse was acquired by ClickHouse (Jan 2026)** and is migrating to "immutable, wide-table modeling" — *the exact `events_full` substrate your plan forks*. Your dossier's own risk R2 (fork-drift maintenance tax) just got much heavier: the substrate you depend on is now a well-funded competitor's core roadmap. ([ClickHouse blog](https://clickhouse.com/blog/langfuse-llm-analytics))
- **LangSmith shipped (Oct 2025): "Insights Agent"** — automatic clustering of production traces by failure mode — **and online multi-turn trajectory evals** that score semantic intent, outcome, *and* tool-call trajectory when a conversation completes. That directly overlaps your **Triage** *and* **Detect**. ([LangChain blog](https://www.langchain.com/blog/insights-agent-multiturn-evals-langsmith))
- **Langfuse shipped a CI/CD gate (May 2026)** — `langfuse/experiment-action` fails the workflow when an experiment score misses a threshold. But it is **dataset-first**, not production-trace-replay. ([changelog](https://langfuse.com/changelog/2026-05-25-experiment-ci-cd-gates))
- **Braintrust** already does production-failure → regression with **automatic, clustered promotion** and a per-case "what improved/regressed" PR comment. ([Braintrust](https://www.braintrust.dev/articles/turn-llm-production-failures-into-regression-tests))
- **Hermetic record-replay is no longer novel as a technique** — `EvalView` and `agent-vcr` are off-the-shelf cassette replay for agents.

### 3b. Where your differentiation is genuinely strong vs. illusory

**Still defensible (lean in):**
- **Hermetic replay of the *exact failure trajectory* — including the tool that errored — as the gated artifact.** Every incumbent's CI artifact is a *dataset experiment* (a curated set scored by a scorer). Even Langfuse's new gate runs a *versioned dataset*. A dataset row *cannot* express "this specific trajectory, with the tool that timed out, must not recur." This survives all the 2025-26 moves.
- **`config_hash` content-addressed `AgentVersion` as the gated unit.** Nobody else versions the agent's *behavioral surface* (prompts + model + tools + graph) as a diffable entity the gate keys on. This is genuinely novel and the right primitive for multi-turn/multi-agent. (Note: it's **designed, not built** — today the gate keys on `(agent_id, root.name, root.input)` digest, `spans.py:28-37`.)
- **The FAIL-TO-PASS contract** validated at promote time (must fail on the version that broke) is a quality bar incumbents' "add trace to dataset" flows don't enforce.

**Illusory / eroded (stop claiming):**
- **"Nobody does regression-from-production" is now false** (Braintrust + LangSmith + Langfuse all do a version of it). Re-cut the pitch to the *narrow true* claim: *hermetic-trajectory replay vs. dataset-row replay.*
- **"Trace is the source of truth" as a category claim is soft** — OpenAI, EvalView, agent-vcr all operate trace-first. The philosophy is mainstream; only the *integrated platform* is unowned.
- **Failure clustering as a differentiator is converging to table-stakes** (LangSmith Insights GA). Yours is good, but it's no longer a wedge by itself — the wedge is the cluster→promote→gate *linkage*.

### 3c. The strategic recommendation

> 🧭 **The durable, unowned sentence is narrower but real:** *"A hermetic replay of your exact production failure trajectory — including the tool that errored — gating the PR, bound to a content-addressed agent version, with an LLM-judge in the gate."*
>
> Ship the **judge-in-gate** (it's the single highest-leverage thing on the whole roadmap — it makes the core claim true). Prove the **replay-vs-dataset distinction** in the demo (re-break the agent → gate blocks with a step-aligned trajectory diff — the moment no dataset-first competitor can reproduce). Add **judge calibration** and **cheap judges**. And **refuse the dataset/prompt-management feature race** — you cannot out-feature a ClickHouse-funded Langfuse, LangSmith, and Braintrust on their turf.

---

## 4. Architecture & code quality — what's good, what's bad, where the design is wrong

### 4a. Backend — clean layering, dangerous operational seams

**Good:** The DDD layout is real, not decoration. `domain/` is genuinely pure (no I/O except the deliberate LLM-provider import). The two hard rules hold — no SQL in routers, all LLM calls through `provider.py`. ClickHouse queries are fully parameterized (no injection surface). Blob-first ingestion is the right durability story. Migration discipline is excellent (8 linear Alembic migrations, real downgrades, `server_default` backfills, a sophisticated partial-unique-index on local email). Config is one validated pydantic-settings model that fails fast.

**Bad — and these are the ones that bite in production:**

- **ClickHouse async client leaked on every request.** `get_async_client()` (`client.py:30`) is created fresh per query, **never closed**, and `async_reader` calls it ~12 times across the read surface. Every API read opens a new connection pool and abandons it → socket/FD leak + connection-setup latency on every request. **Highest-priority infra bug.**
- **No app lifespan / shutdown / readiness.** `api/main.py` has no `lifespan`. The leaked clients are never disposed, the async engine never `dispose()`s, and **`/health` is a static `{"status":"ok"}`** that never checks Postgres/ClickHouse/Redis/S3 — a backend with a dead DB pool reports healthy and keeps taking traffic.
- **No global exception handler, no logging config.** `structlog.get_logger()` is used in 8+ modules but **`structlog.configure()` is never called** — the observability product has unconfigured observability of itself. Any unhandled router exception → a raw 500 with no structured log, no request id.
- **Always-on permissive CORS.** `allow_origin_regex=r"http://localhost:\d+"` is on in *all* environments (`main.py:33`) with `allow_methods/headers=["*"]`. Gate it on `env != prod`.
- **The two-session-world is the structural debt.** `auth.py` uses **async** sessions; every other router uses **sync** `SyncSessionLocal()` wrapped in `run_in_threadpool`. So Postgres access is split across two stacks with duplicated query patterns, and the sync routers fan everything onto the default 40-token anyio threadpool — a concurrency ceiling shared with the SSE eval runs. This is the root of several smaller problems and the highest-leverage refactor.
- **Multi-commit operations leave half-written state.** `promote_trace` commits **4 times** for one logical promote (`regression_service.py:184,203,205,218`); a crash between them leaves a half-promoted case. `FailureIntelService._replace_with_issues` **deletes all clusters and commits, then inserts** (`failure_intel_service.py:237-291`) — between commits the project has *zero* clusters, and a crash wipes all promotion/ignore state. Make each one transaction.
- **Eval-on-ingest is a blind `countdown=4`** (`tasks.py:24`) with no "trace complete" signal — a slow agent whose spans arrive >4s apart gets scored on a partial trace.
- **Dead code:** `tracely/ingestion/` is an empty package (only `__pycache__`); `repositories.evaluator_get` is unused.

### 4b. Frontend — a god component and no safety net

**Good:** The SSR + secret-keeping-proxy pattern is sound (JWT in an httpOnly cookie, never reaches client JS). TypeScript hygiene is genuinely high — **zero `any` in the whole tree**, one justified `@ts-expect-error`. The SSE decoder, the usage math, and the portal-based floating panels are well done. Empty states are specific and helpful.

**Bad:**

- **`TraceTable.tsx` is a 1942-line god component doing 8 jobs** — a private icon library, a ~700-line content-shape inference engine, token popovers, the entire eval-column subsystem, the column model, the row tree, two dropdown menus, and a root with **15 `useState` hooks**. This is the dominant maintainability liability.
- **It re-renders the whole grid on every SSE frame.** `EvalViewContext` value depends on `liveScores`/`busyCols`/`busyRows`, and nothing in the row tree is `React.memo`'d — so a single eval run re-renders every cell on each streamed score. It will visibly lag on large traces.
- **The hardest logic is triplicated and untested.** Message/JSON shape inference exists in three places (`TraceTable.tsx`, `IO.tsx`, `JsonView.tsx`) with divergent copies of `msgRole`, `MSG_TYPES`, `MessageCard`, `ToolCalls`; `fmtMs` is defined 3×. There are **zero frontend tests**. A fix to tool-call parsing in one renderer won't reach the other → the timeline and the table can render the same span differently.
- **No error/loading boundaries** (§1d). **Accessibility is thin** — modals aren't dialogs (no focus trap/restore), table rows are mouse-only (`<tr onClick>` with no `tabIndex`/key handler), dropdowns have no `role="menu"`/arrow-nav, the sidebar vanishes below `md` with no mobile replacement.
- **Magic values:** the `useWide` `734px`/`292px` breakout, `agent="planner"`/`env="ci"` hardcoded as the gate target in 4 places, span-type vocab + color maps hand-mirrored across 4 files.

### 4c. SDK + replay — the moat, and where it's quietly broken

**Good (the strongest engineering in the repo):** The context-stamping `SpanProcessor` (`__init__.py:101-124`) that stamps `tracely.*` onto every span — including zero-touch instrumentor spans — is the load-bearing idea and it's correct and tested. Broad auto-instrumentation with thoughtful LangChain de-dup. The multi-vendor I/O normalization (`messages.py`, `io_field.py`, `tool_enrichment.py`) reassembles gen_ai structured/legacy + OpenInference + OpenLLMetry + LangChain ×2 + LiteLLM repr into one shape — unglamorous, hard-won, real-world-shaped code. The record→error→`ToolError` replay seam is genuinely clever.

**Bad — and these undermine the thesis:**

1. **All-SKIP passes the gate** (`gate_service.py:200`; CLI exits 0). A misconfigured CI step, a renamed agent, a digest mismatch, or a crashed entrypoint → every case SKIPs → `failed=0` → **GREEN merge**. For a merge-blocker this is the worst possible bug. Add `--require-coverage` (skipped must be 0) and return FAIL/INCONCLUSIVE when `passed==0 and total>0`.
2. **Auto-instrumentation and the replay seam are mutually exclusive instrumentation styles.** Replay is hermetic only if the dev hand-wrote the agent against `call_tool`/`call_llm`. A customer who used the advertised `instrument="auto"` path gets faithful *recording* but **cannot replay hermetically** — their code makes real calls, and the OpenInference instrumentors aren't intercepted by `fixtures()`. The README's "the same agent code runs live and offline" is only true if you adopted the manual seam from day one.
3. **The fail-to-pass wedge is narrow.** Promotion only validates missing/errored tools (`regression_service.py:126-141`); a hallucination/wrong-answer/wrong-arg trace has all tools run and nothing errored → can't be promoted. `tool_args_mode="exact"` is stored and never enforced. The seeded hallucination case literally can't become a regression test.
4. **LLM fixture args are dropped at serialization** (`fixtures.py:73` writes `"input"`, the SDK reads `"args"`) → arg-keyed LLM replay is silently impossible; latent wrong-completion bug.
5. **No PII redaction anywhere in the SDK**, and **no payload-size cap** — production prompts/args/user data shipped verbatim. Adoption blocker for any regulated buyer.
6. **Brittle CI timing** — `--cmd` replay does `time.sleep(8)` (`cli.py:384`); `--entrypoint` "gates anyway" after a 45s poll → flakes or false greens.
7. **Loose version pinning** — every provider extra is `>=0.1.0` with no upper bound; OpenInference instrumentors are pre-1.0 and break between minors. The `all` extra is a transitive-conflict minefield.

### 4d. Infra — it demos, it won't survive production

**Good:** The local docker-compose dev loop is genuinely best-in-class for a project this size — healthcheck-gated ordering, a one-shot idempotent migrate job, live source mounts + editable installs. The Railway deploy story is real and well-documented (migrations-on-deploy before cutover, all idempotent). ClickHouse schema fundamentals are sound (ReplacingMergeTree, monthly partitions, project-first ORDER BY, bloom-filter skip indexes, ZSTD on I/O columns).

**Bad:**

- **Single replica of everything. Zero backups** — no `pg_dump`, no `clickhouse-backup`, no MinIO replication, no volume snapshots. Lose the Postgres volume (registry, users, password hashes, all eval/gate history) and the product is gone. **P0.**
- **Zero self-observability** — no Sentry, no metrics, no Flower, fake healthcheck. The observability company is blind to its own outages.
- **No ClickHouse TTL** on `events`/`scores` → unbounded growth → the single-volume CH fills and dies on its own clock. Reads use `FINAL` (merge-on-read) with no `OPTIMIZE` schedule → latency degrades over time.
- **Solo Celery worker, no replicas** (`worker.json:8`, `--pool=solo`). Ingestion, evals, and cluster rebuilds all serialize through one thread on one shared queue → head-of-line blocking; the documented `numReplicas` fix isn't even in the config. **This is the load ceiling.**
- **Celery on Redis with no `visibility_timeout` + `acks_late`** → long tasks redeliver and double-run; no dead-letter → a task past `max_retries` is silently lost; Redis is `noeviction` + no persistence → a restart drops in-flight work.
- **`/v1/traces` reads the full body into memory with no size or rate limit** (`otlp.py:15`) → large/concurrent posts exhaust backend memory.
- **The well-known `tracely_dev_key` is seeded into every deploy** including prod; `AUTH_MODE=dev` is the default → a fumbled deploy runs wide open.
- **No CI tests/lint/build/security.** The `backend/tests` suite and `ruff` exist; **nothing in `.github/workflows/` runs them.** The *production* frontend Dockerfile (`Dockerfile.railway`, different from dev) is never built until deploy. The only CI is your own gate dogfood. (Irony noted.)

---

## 5. The prioritized fix list

> Treat P0 as "before any real customer wires this to a required check or sends real traffic."

### P0 — correctness, data-loss, false-confidence
- [ ] **Kill the all-SKIP false-green gate** (`gate_service.py:200`): pass `skipped` into `_final_status`; return non-PASS when `passed==0 and total>0`; add `--require-coverage`. *(The gate is a liability until this lands.)*
- [ ] **Unify the three FAIL computations** (`async_reader.py:26`, `traces.py:60`, `sessions.py:52`) into one policy; make "counts as failing" a per-evaluator flag, not a magic string.
- [ ] **Back up Postgres + MinIO** (Railway volume snapshots + scheduled `pg_dump`/`clickhouse-backup`). Single highest-leverage infra fix.
- [ ] **Cache + close the ClickHouse async client** in a FastAPI `lifespan` (`client.py`, `main.py`); make `/health` actually probe dependencies.
- [ ] **Wire `sampling`/`target_agent`/`target_env` into the runner — or delete them.** Shipping fake knobs is worse than missing ones.
- [ ] **Make `promote_trace` and `_replace_with_issues` single-transaction** (`regression_service.py`, `failure_intel_service.py`).
- [ ] **Add per-span error isolation + a size cap on ingest** (`parser.py`, `span_mapper.py`, `otlp.py`); quarantine poison blobs instead of retry-storming.

### P1 — make the product *true* and *operable*
- [ ] **Wire the LLM-judge into the gate** + score-delta-vs-baseline. *Makes "the trace is the test" actually true; #1 strategic lever.*
- [ ] **Bridge auto-instrument → replay** (a fixture-serving shim) *or* document honestly that hermetic replay needs the manual seam, with a migration recipe.
- [ ] **Add a redaction hook to the SDK** (`init(redact=...)` / field allow-deny in `set_io`).
- [ ] **Eval cost/latency tracking + a duplicate-call cache + a cheap default judge.**
- [ ] **Scale the worker off solo** + split queues (ingest vs eval vs rebuild); add `task_time_limit` + `visibility_timeout` + a dead-letter path.
- [ ] **ClickHouse TTL/retention** + an `OPTIMIZE FINAL` schedule.
- [ ] **Configure `structlog` + a global exception handler + request-id middleware** (`main.py`); wire Sentry into FastAPI + Celery.
- [ ] **Add real CI:** `ruff check`, `pytest backend/tests`, build both Dockerfiles, `pip-audit`/`npm audit`, Dependabot.
- [ ] **Frontend `error.tsx`/`loading.tsx`** + stop swallowing fetch failures into empty arrays.

### P2 — maintainability & polish
- [ ] **Split `TraceTable.tsx`** (columns / eval-columns / rows / root) and **extract one shared `lib/content.ts`** consumed by table + timeline + JSON view; memoize the row tree.
- [ ] **Make the eval columns visible by default** and to the left of the message dump; fix the `useWide` magic-number breakout.
- [ ] **Migrate data routers off `SyncSessionLocal`+threadpool onto the async engine** (collapses the two-session-world + the threadpool ceiling).
- [ ] **Delete dead code** (`tracely/ingestion/`, `evaluator_suggestion.py`, `repositories.evaluator_get`); fix `backend/README.md:103`.
- [ ] **Add the missing high-value tests** (`async_reader`/`score_writer`/`GateService`/`promote_trace`; the frontend parsers + SSE decoder).
- [ ] **Pin SDK instrumentor extras** with upper bounds.

---

## 6. What to build next — ideas that matter to customers

Ordered by "moves the business," staying on-thesis:

1. **"Re-break it" demo + always-seeded right half.** Seed `seed_regression.py` into the default project so cases/gates are never empty, and script the killer demo: change a prompt → push → gate blocks the PR with a **step-aligned trajectory diff**. This is the one thing no dataset-first competitor can reproduce — make it the *first* thing anyone sees.
2. **Judge-in-the-gate** (also P1). The feature that turns "catches crashes" into "catches the regressions customers actually fear."
3. **A judge-trust surface.** A "calibration" view: review N judge-scored traces, agree/override, see live judge-vs-human agreement %. This is the prerequisite for *charging* for "evaluators as columns" — it answers the buyer's first question.
4. **Zero-config GitHub App.** Today wiring the gate needs a workflow file + secrets + the manual `call_tool` seam. A GitHub App that auto-detects the agent and posts the check is the difference between "a project" and "a product."
5. **Monitors + Slack/webhook alerts** on the regression-loop metrics you already compute (failure-rate spike, gate pass-rate drop, MTTR). On-thesis, low effort, immediately useful.
6. **A thin, promoted-case "compare versions" view** — run the suite across agent v12 vs v13, show per-case deltas. The on-thesis answer to "is B better than A?" without building the dataset pillar.
7. **Cost dashboard for evals** — per-evaluator $/1k traces, with sampling enforcement. Turns the cost gap into a selling point.

---

## 7. Appendix — drift, dead code, and the honest doc problem

- **`OVERVIEW.md` describes the old flat layout** (`evaluators.py`, `fi.py`, `cluster.py` at top level) — the code has since been refactored into a clean `domain/services/infrastructure/api` structure. The honest-limitations section also still says "no evaluator management API/UI yet," which is no longer true (it's built and is your best UX). Great document; it's lying by omission about its own progress now.
- **`backend/README.md:103`** references `wrap_with_score` (doesn't exist).
- **Dead code:** `tracely/ingestion/` (empty pkg), `evaluator_suggestion.py` (mismatched shape), `repositories.evaluator_get`, `CopyId` `chars`/`full` props (call sites still pass them), the non-functional "Bot/view agents" row button.
- **Test reality:** domain logic + auth are well-tested (~1900 lines, including JWT alg-confusion). The **stateful infra and service orchestration — where every scary bug above lives — is the least tested.** Zero tests touch the ClickHouse readers/writers, `GateService`, `promote_trace`, or the ingest pipeline; zero frontend tests at all.

---

> **Bottom line.** Tracely is a genuinely well-engineered system with a real, narrowing wedge — and right now it shows the world its commoditized half while the differentiated half sits empty and partly broken. The fastest path to "this is obviously a category-defining product, not a Langfuse clone" is three moves: **make the gate honest** (kill the false-green, put the judge in it), **make the moat visible** (seed it, demo the re-break), and **make the eval feature trustworthy and cheap** (calibration + real sampling + cost). Everything else on the list is in service of those three.
