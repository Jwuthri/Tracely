# 🛰️ Tracely — The Complete Guide

> **Trace-native CI/CD for AI agents.** Your agent's production traces become regression tests that block bad pull requests — automatically.

`v0.1.0 · MVP` • A living overview of what's built, why it's built that way, and where it's going.

---

## 📑 Table of contents

1. [🧠 The big idea (ELI5)](#-the-big-idea-eli5)
2. [🎯 What Tracely is — and deliberately is NOT](#-what-tracely-is--and-deliberately-is-not)
3. [🦴 The spine: one loop to rule them all](#-the-spine-one-loop-to-rule-them-all)
4. [🏗️ Architecture at a glance](#️-architecture-at-a-glance)
5. [📚 Features, stage by stage](#-features-stage-by-stage)
   - [① Observe — catch every run](#-observe--catch-every-run)
   - [② Detect — grade it instantly](#-detect--grade-it-instantly)
   - [③ Triage — group the failures](#-triage--group-the-failures)
   - [④ Test — freeze a failure into a test](#-test--freeze-a-failure-into-a-test)
   - [⑤ Ship — gate the pull request](#-ship--gate-the-pull-request)
   - [🎨 The UI layer](#-the-ui-layer)
6. [🔑 Key decisions & why](#-key-decisions--why)
7. [🐛 War stories: the bugs we hunted](#-war-stories-the-bugs-we-hunted)
8. [⚠️ Sharp edges (honest limitations)](#️-sharp-edges-honest-limitations)
9. [🚀 What's next](#-whats-next)
10. [🏃 How to run it](#-how-to-run-it)
11. [🗂️ Codebase map](#️-codebase-map)

---

## 🧠 The big idea (ELI5)

> 🍼 **Explain it like I'm 5:**
> Imagine a robot helper that books your flights. One day it does something dumb — it approves a $900 refund without asking a human first. 😱
>
> Most tools would just draw you a chart that says "1 bad thing happened." Tracely does something better: it **records that exact bad moment** and turns it into a **test** with one click. From then on, every time someone changes the robot's brain, Tracely **re-plays that exact moment super fast and cheap** and checks: "Does the robot still do the dumb thing?" If a code change would bring the bug back, Tracely 🛑 **blocks it** — like a bouncer at the door of your pull request — *before* it ever reaches real users.

The one sentence that captures everything:

> 💡 **The recorded run *is* the test.** You don't sit down and hand-write a list of example questions and ideal answers. Production already gave you the perfect failing example. Tracely just freezes it.

Every other artifact in the system — a quality score, a failure cluster, a suggested fix, a CI verdict — is **derived from the trace**. The trace is the source of truth. 🌱

---

## 🎯 What Tracely is — and deliberately is NOT

Tracely is sharp about its anti-goals. This keeps it from drifting into "yet another observability tool."

| ✅ Tracely IS | ❌ Tracely is NOT |
|---|---|
| **Trace-native** — the production trace is the primary key | ❌ **Not another Langfuse** — it doesn't stop at "look at pretty traces" |
| **Agent-first** — agent / run / turn / step / tool are first-class | ❌ **Not prompt management** — the versioned thing is the *agent*, not a prompt |
| **Regression-first** — tests are born from real failures | ❌ **Not dataset-first eval** — you never author `{input, expected_output}` rows up front |
| **A CI gate** — produces a PASS/FAIL that blocks a PR | ❌ **Not Datadog-for-LLMs** — it's not a wall of metric dashboards |

> 🧭 **The wedge:** every incumbent (LangSmith, Braintrust, Phoenix, Galileo, DeepEval, OpenAI Evals…) bottoms out in `Dataset → Experiment → Scorer`. That throws away the trajectory, the tool outputs, and the agent version that failed. A dataset row *cannot* say "the exact failure path we saw last Tuesday must never recur." Making the **trace** the literal primary key is the defensible white space.

---

## 🦴 The spine: one loop to rule them all

Everything in Tracely is one closed loop. The UI's left sidebar literally teaches it as four stages:

```
   👀 OBSERVE          🔬 DETECT           🧹 TRIAGE          🧪 TEST            🚢 SHIP
 ┌────────────┐     ┌────────────┐     ┌────────────┐    ┌────────────┐    ┌────────────┐
 │ Production │────▶│  Failure   │────▶│  Failure   │───▶│ Regression │───▶│   CI/CD    │
 │   Trace    │     │ Detection  │     │ Clustering │    │    Test    │    │    Gate    │
 └────────────┘     └────────────┘     └────────────┘    └────────────┘    └─────┬──────┘
       ▲                                                                          │
       │                          🔁 a blocked-then-fixed PR ships a green check  │
       └──────────────────────────────────────────────────────────────────────────┘
```

| Stage | Sidebar | What happens | You click… |
|---|---|---|---|
| 👀 **Observe** | *Observe* | Agents emit OTLP traces → stored & shown as waterfalls | — |
| 🔬 **Detect** | *(automatic)* | Every run is auto-graded (incl. *silent* failures) | — |
| 🧹 **Triage** | *Triage* | Failures grouped into named **Issues** | **Analyze failures** |
| 🧪 **Test** | *Test* | One failure → a fail-to-pass **regression case** | **Promote** |
| 🚢 **Ship** | *Ship* | PR replays the suite → green/red check | **Run gate** / the GitHub Action |

---

## 🏗️ Architecture at a glance

> 🍼 **ELI5:** Tracely is a little team of helpers. A **doorman** (API) catches traces and immediately stuffs the raw envelope in a **safe** (S3) so nothing is ever lost. It drops a ticket in a **queue** (Redis). A **back-office worker** picks up tickets, files each step into a giant **fast filing cabinet** (ClickHouse), and grades the run. A **regular notebook** (Postgres) tracks which agents and tests exist. A **website** lets you look at it all.

```
        your agent (Tracely SDK / any OTLP exporter)
                        │  POST /v1/traces
                        ▼
   ┌─────────────────────────────────────────────┐
   │  FastAPI backend  (the `tracely` package)    │
   │  1) write raw OTLP to S3  ← source of truth   │──────▶ 🪣 MinIO / S3
   │  2) enqueue a job                             │──────▶ 🔴 Redis
   └─────────────────────────────────────────────┘
                        │
                        ▼   (Celery worker, same package)
   ┌─────────────────────────────────────────────┐
   │  parse OTLP → resolve agent → insert spans    │──────▶ 🐘 Postgres+pgvector (registry, cases, gates)
   │  then auto-evaluate the run (debounced 4s)    │──────▶ 🧱 ClickHouse  (events + scores)
   └─────────────────────────────────────────────┘
                        ▲
                        │  cache:'no-store' SSR fetches
   ┌─────────────────────────────────────────────┐
   │  Next.js 15 frontend (Observe/Triage/…)       │
   └─────────────────────────────────────────────┘
```

**The stack:**

| Layer | Tech | Why |
|---|---|---|
| API + worker | **Python · FastAPI · Celery** | One `tracely` package, shared by API (producer) and worker (consumer) so enqueue & execute never drift |
| Hot store | **ClickHouse** (`ReplacingMergeTree`) | Millions of spans; one immutable row per span; upserts late/duplicate spans |
| Registry | **Postgres 17 + pgvector** | Agents, cases, gates, clusters + cached failure embeddings |
| Blob | **MinIO / S3** | Raw OTLP = durable source of truth (blob-first ingestion) |
| Queue | **Redis** | Celery broker + result backend |
| UI | **Next.js 15 · React 19 · Tailwind** | Server-rendered dashboard |
| SDK + CLI | **`tracely_sdk`** (OpenTelemetry) | Instrument agents + the `tracely` CI command |

> 🧩 **Monorepo, one shared brain.** All real logic lives in `backend/tracely`. `workers/` is a 6-line runtime that just imports the tasks; `sdk/` is independent (OTel-only) so it installs anywhere CI runs. Everything boots with **one command**: `docker compose up`.
>
> ⚡ **Dev superpower:** the backend/worker containers bind-mount your local source over the image, and the packages are `uv`-editable-installed — so a Python edit is *live* after a `docker compose restart worker`, no image rebuild. (We leaned on this constantly while tuning the clustering.)

---

## 📚 Features, stage by stage

### 👀 Observe — catch every run

> 🍼 **ELI5:** A flight recorder for your AI. The SDK records each step (the agent, every LLM call, every tool call) as a "span," and ships them in the industry-standard OpenTelemetry format.

**What's built ✅**

- **`POST /v1/traces`** — the one public door. Accepts OTLP protobuf *or* JSON from any OTel SDK, authenticates a `Bearer` key → project, and returns instantly. It does **zero** parsing inline.
- **Blob-first ingestion** — the raw bytes hit S3/MinIO **before** anything is queued. A worker crash or parse bug can *never* lose data; the blob is re-processable. (Directly mirrors Langfuse's `processEventBatch`.)
- **One row per span in ClickHouse `events`** — a wide table with **first-class agent columns** (`agent_id`, `agent_run_id`, `conversation_id`, `turn_id`, `step_id`, typed `caller/callee` edges) + provenance (`evaluation_case_id`, `gate_run_id`, `failure_cluster_id`) + model/usage/IO. `ReplacingMergeTree(event_ts, is_deleted)` means re-sent or late spans **upsert** instead of duplicating; reads use `FINAL` to dedupe.
- **Multi-vendor attribute mapping** — `_map_span` lifts signals from **OpenInference, OTel GenAI semconv, Langfuse, LangGraph, and Tracely-native** attributes into the *same* typed columns via a `_first(keys…)` fallback chain. Span type (GENERATION / AGENT / TOOL / …) is classified by priority across all those conventions.
- **The SDK** — ergonomic `with` blocks (`agent`, `llm`, `tool`, `turn`, `step`) that auto-nest via OTel context and emit exactly the attributes the backend consumes. Plus `set_io`, `set_usage`, `error`, and `env` tagging.

> 🔑 **The differentiator:** in Langfuse, "which agent/turn/step does this score belong to?" means parsing `metadata[langgraph_node]` at read time. In Tracely it's a **column lookup**. That's what makes agent-level querying, clustering, and gating fast.

`backend/tracely/api/routers/otlp.py` · `ingestion/process_batch.py` · `otel/mapping.py` · `ch_migrations/0001_events.up.sql` · `sdk/tracely_sdk/__init__.py`

---

### 🔬 Detect — grade it instantly

> 🍼 **ELI5:** The moment a run lands, a teacher marks it. A few cheap checks (Did it crash? Did every tool it *said* it'd use actually run? Was it fast?) plus an optional smart AI grader that reads the final answer and checks it's actually correct.

**What's built ✅** — five evaluators run automatically on every trace (debounced 4s so late spans settle):

| Evaluator | Level | Catches |
|---|---|---|
| `run_outcome` | run | Any errored span 💥 |
| `tool_success` | **tool** | A specific tool span that errored (pinpointed to that span) |
| `tool_consistency` | run | 🥷 **The silent failure** — model *requested* a tool but no tool span ran |
| `latency` | run | Over the latency budget (default 60s) |
| `llm_judge` | run | 🧑‍⚖️ Wrong / unfaithful answers (only if a key is set) |

> 🥷 **Silent failures are the star.** A run with **zero error spans** can still be broken — the model says "I'll call `get_weather`" and then just… makes up the weather. `tool_consistency` compares *requested* tools (`tracely.tool_calls`) against *executed* TOOL spans and flags the gap. No other structural check would catch this.

> 🧑‍⚖️ **The judge grades faithfulness, not vibes.** The LLM judge reads the agent's **real final answer** (never a tool's raw payload) *and* the tool outputs it had in hand, then scores 0–1 and **fails answers that contradict their own tools**. PASS threshold is `0.6`. It's fully optional — no key, no judge, no cost.

Scores land in ClickHouse `scores` with a **first-class `verdict` column** (PASS/FAIL/SKIP) and **deterministic ids** (`uuid5(trace:name:span)`), so re-evaluating a trace *replaces* its scores instead of piling up duplicates. Online evals are tagged `evaluation_case_id=''` — that empty sentinel is how the read API tells them apart from gate/regression verdicts.

`backend/tracely/evaluators.py` · `eval_runner.py` · `tasks.py`

---

### 🧹 Triage — group the failures

> 🍼 **ELI5:** When 50 runs break, you want to know "is this actually the same 3 bugs?" Tracely groups them — first instantly by a fingerprint, then (on demand) with real AI that reads the failures and writes a plain-English **Issue** with a title and a suggested fix.

This is the part we invested the most in this session (inspired by LangSmith's "Engine"). It's **two clustering systems**:

**1. Signature clustering — always on, free ✅**
The instant a run fails, it's grouped by a structural fingerprint: the set of failed evaluator names + the error text with ids/numbers/quotes masked out (Drain3-style). So the Failures screen is never empty.

**2. Embedding + LLM clustering — on demand ("Analyze failures") ✅**
The richer pass that produces semantic **Issues**:

```
failing traces
   │  embed a MECHANISM-focused text (not the topic!)
   ▼
OpenAI embeddings (text-embedding-3-small, 1024-d) ──cached──▶ 🐘 pgvector
   │
   ▼  cluster:  cosine-distance HDBSCAN  (or UMAP+HDBSCAN at scale)
   │
   ▼  🤖 per-cluster agent  → title · description · severity · fix · per-trace summaries
   │
   ▼  🤖 meta-consolidation agent → merge/split into final Issues
   │
   ▼  inherit PROMOTED/IGNORED state from old clusters → write Issues
```

> 🧲 **The single most important lever: embed the *mechanism*, not the *topic*.** Each failing trace produces **two** texts: a terse `"tool execution error: get_weather: upstream timeout"` for the *clusterer*, and a full context block for the *analysis agent*. Without this, every "weather" failure clustered together regardless of *how* it broke. With it, two unrelated questions that hit the same bug cluster together, and one question failing two different ways does **not**.

> 🤖 **Two agents, built with LangChain `create_agent` + `gpt-4o-mini`.** The per-cluster agent is told to name the concrete *mechanism* (never "issues"/"problems") and state **only** what the evidence shows. The consolidation agent is told a tool that *errored*, a tool *never executed*, and a *hallucinated answer* are three **different** Issues — "when in doubt, keep separate." Both are grounded in the same evaluator verdicts (`Detected by: …`) and the actual tool results.

> ♻️ **Re-analyzing never loses your work.** A rebuild deletes and recreates an agent's clusters — so it first snapshots which were **PROMOTED** (→ a test) or **IGNORED**, and the new Issue with the biggest trace overlap *inherits* that status, the linked case, and the original first-seen time.

`backend/tracely/fi.py` · `agents.py` · `cluster.py` · `api/routers/clusters.py`

---

### 🧪 Test — freeze a failure into a test

> 🍼 **ELI5:** Click "Promote" on a bad run and Tracely freezes it into a rule: "given this same input, never fail this way again, and still use the right tools." The magic: the test starts **red** (it fails on the broken run it came from) and only goes **green** once the bug is truly fixed.

**What's built ✅**

- **`promote_trace`** — turns one trace into a durable `EvaluationCase`, **idempotently** (keyed by `input_digest`, so one flaky bug can't spawn 10,000 identical cases). It captures:
  - a **reference trajectory** (the golden step sequence),
  - **assertions** (`required_tools`, `match_mode`, `no_error`),
  - **fixtures** — the recorded tool & LLM outputs, saved to S3 for hermetic replay (more on this in Ship 👇).
- **The fail-to-pass contract** 🔴→🟢 — right after creating the case, Tracely re-evaluates the *source* trace against it. The case only becomes **PROMOTED** if that broken run genuinely **FAILS** its own assertions; otherwise it's parked as **DRAFT**. No vacuous always-green tests.
- **Trajectory match modes** (agentevals-style): `superset` (default — every required tool present, extras OK), `strict`, `unordered`, `subset`.
- **`evaluate_case`** returns PASS/FAIL + a rich `detail` (missing tools, erroring steps, …) that the CLI renders into a human reason.
- **`replay_case`** — evaluate the case against any *candidate* trace (e.g. a run from the fixed agent).
- **Nice touch:** a promoted cluster passes its **label** as the case title, so cases read `"get_weather requested but not executed"`, not `"planner"`.

`backend/tracely/regression.py` · `trajectory.py` · `api/routers/cases.py`

---

### 🚢 Ship — gate the pull request

> 🍼 **ELI5:** On every pull request, the `tracely` command re-runs your agent against all the saved failures and either passes ✅ or **blocks the merge** 🛑 — posting a green/red check and a comment right on the PR. And it does it **for free**, by replaying the *recorded* tool/AI answers so CI never calls a real (slow, costly, flaky) model.

This is the payoff — the thing no other tool does. **What's built ✅:**

**The `tracely` CLI** (ships in the SDK, stdlib-only so it runs anywhere):

- **`tracely gate`** — gate against ci traces your CI already emitted, matched to cases by input digest.
- **`tracely replay`** — the turnkey path: fetch the promoted suite, **re-run your agent** on each recorded input, pair each new trace to its case, gate, and post the check — *all in one step*.

> 🎯 **Explicit pairing beats guessing.** When `replay` re-runs the agent, it *knows* which trace ran which case, so it passes an explicit `{case_id: trace_id}` map to the gate — no fragile digest-matching. (The `--cmd` path for non-Python agents falls back to digest matching.)

**The gate result becomes a real PR check:**
- a **commit status** `tracely/regression-gate` (mark it required → it blocks merge),
- an **upserted PR comment** (a hidden marker means it updates in place, never spams) with a per-case table and a deep link to the gate run,
- proper exit codes: `0` PASS / `1` FAIL / `2` error.

**🔒 Hermetic replay — deterministic, offline, free (built ✅):**

> 🍼 **ELI5:** The agent re-runs against the *exact* tool and AI answers recorded in production. CI needs no API key, costs nothing, and never flakes.

The SDK's `call_tool(name, fn)` / `call_llm(model, fn)` serve the recorded fixture **instead of calling `fn`**. The fixtures were captured at promote time and flow through `GET /api/gate/suite`. Pass `--live` to make real calls instead.

> 🧪 **We made it self-proving.** The example agent's "live model" function **raises on purpose**. In hermetic mode it's never called → the test passes. With `--live` it fires and the run fails loudly. So you can *see* that CI isn't touching the real model.

**The GitHub glue:** a composite Action (`.github/actions/tracely-gate`) + a copy-paste workflow. Needs `statuses: write` + `pull-requests: write`.

`backend/tracely/gate.py` · `api/routers/gate.py` · `sdk/tracely_sdk/cli.py` · `sdk/examples/` · `.github/`

---

### 🎨 The UI layer

> 🍼 **ELI5:** A dark, glowing "control room" for your agents, organized as the same Observe → Triage → Test → Ship funnel.

**What's built ✅** — a hand-rolled Next.js 15 dashboard (zero UI libraries, just Tailwind + clsx + 17 inline SVG icons):

- **Dashboard** — four stat tiles + recent traces/cases.
- **Traces + waterfall** 🌊 — the flagship screen: a flamegraph-style span waterfall (color-coded by span type, staggered grow animation) with a sticky inspector showing the selected span's input/output/metadata.
- **Failure clusters** — Issues with counts, severity, the LLM analysis + proposed fix, member traces, and the **Analyze failures** button.
- **Regression cases** — the fail→pass contract, assertions, reference trajectory, and a **Replay** panel.
- **CI gates** — gate-run history with PASS/FAIL banners and per-case reasons.
- **`[ID]` copy chips** 📋 — the signature element. Long ids are never shown raw; a tiny `[ID]` chip copies the full value on click. (Whole rows are clickable via a `role=link` div so the chip's click can `stopPropagation` — invalid `<button>`-in-`<a>` avoided.)

The aesthetic: near-black `ink` palette, a **cyan "signal"** brand accent, faint background grid, glow shadows, custom fonts (Bricolage Grotesque / Hanken Grotesk / JetBrains Mono), staggered reveal animations. Every page is a **server component** fetching the backend with `cache:'no-store'` (always live); mutations go through thin Next.js proxy routes that keep the key server-side.

`frontend/app/` · `components/` · `lib/api.ts`

---

## 🔑 Key decisions & why

The choices that shaped the system, with their tradeoffs:

| 🧩 Decision | 💡 Why | ⚖️ Tradeoff |
|---|---|---|
| **Trace is the source of truth** (trace-first, not dataset-first) | A dataset row can't express "this exact failure trajectory must not recur"; the trace can | Thinner cold-start than a hand-authored dataset |
| **Agent semantics as indexed columns** (not metadata strings) | "Which level does this score target?" = a column lookup, not a read-time parse | Wider, opinionated schema; an ingest pass to resolve slugs→UUIDs |
| **Blob-first ingestion** (S3 before the queue) | Nothing is lost on a worker/queue outage — the blob is re-processable | An S3 PUT on the request path + a worker GET |
| **`ReplacingMergeTree` + read with `FINAL`** | Late/duplicate spans upsert to one row; re-eval is idempotent | `FINAL` reads are heavier; merges are async |
| **LLM features are key-gated & optional** | Default `docker compose up` is fully local & free | No quality/clustering smarts without a key |
| **Embed the *mechanism*, not the topic** | Cluster by *how* it broke, so unrelated inputs with the same bug group together | Two texts per trace; the cached vector is keyed to the mechanism text |
| **Skip UMAP for small/duplicate sets** (cosine HDBSCAN < 50 pts) | UMAP *invents* clusters on few/near-identical vectors (we saw it happen) | Two clustering regimes to reason about |
| **Two clustering agents (analyze → consolidate)** | Embeddings over-split; a 2nd agent merges dupes while keeping mechanisms apart | More LLM calls |
| **Fail-to-pass validated at promote time** | Rejects vacuous always-green tests — the case must fail on the run it came from | A failure not expressed as an ERROR/missing-tool can't validate |
| **Hermetic replay by default** | Per-PR gating is only viable if it's deterministic, free, and fast | Fixtures keyed by *name* (not args/order); missing fixture → silent live fallback |
| **Only fail-to-pass is a hard gate** | It's the reason to exist; cost/latency/score are noisy in replay → start as warnings | Quality/cost regressions can merge until you opt those gates in |
| **Two SQLAlchemy engines** (async API / sync workers) | FastAPI wants asyncpg; Celery tasks are sync processes | Two DB URLs to keep in sync |
| **Hand-rolled design system** (no UI libs) | Distinctive look, tiny bundle | No accessible primitives for free |

> 🏛️ **One source of truth for the design too.** `design/part2-tracely/00-canonical-decisions.md` is authoritative; ~16 cross-doc conflicts were adjudicated there so ambiguity never reached implementation.

---

## 🐛 War stories: the bugs we hunted

The journey wasn't a straight line. These are the real debugging moments from building this — and what each one taught us. 🔍

**1. 🌀 The clustering that lied ("Weather API Timeout Issues")**
The first embedding run merged *everything* into one wrong Issue and hallucinated "timeout." We traced it down a rabbit hole: HDBSCAN was producing 4 clusters, but they were a *random mix* of error + silent failures. The culprit was **UMAP** — on ~14 near-duplicate vectors it scatters the points and HDBSCAN finds phantom structure. **Fix:** cluster directly on cosine distance below `fi_umap_min_n=50`; reserve UMAP for large, diverse sets. Cosine HDBSCAN gave a *perfect* split instantly.

**2. 🧲 Domain drowned out mechanism**
Even with good clustering, the embedding text was ~80% shared content ("what's the weather in SF"), so the *failure mode* was noise. **Fix:** the mechanism-focused embedding text — the single highest-leverage change in the whole engine.

**3. 🧑‍⚖️ The judge was grading the wrong thing**
The hallucination case (tool succeeds, answer is absurd "9000°F") scored a fragile `0.5`. Why? The judge was grading the **tool's raw output** `{"tempF": 64}`, not the agent's actual answer — the same output-selection bug existed in two places. **Fix:** grade the agent's *real* answer **and** feed it the tool results as grounding → it now nails it at `0.0` with "contradicts the tool results, which indicate 64°F."

**4. 👯 The duplicate promoted cluster**
After a rebuild, the old PROMOTED signature cluster sat next to the new embedding Issue — a visible duplicate. **Fix:** promotion-inheritance — the new Issue with the biggest trace overlap inherits the promotion + linked case, and the duplicate vanishes.

**5. 🎯 Replay pairing**
The gate matched candidates to cases by input digest — fine for pre-emitted traces, fragile for replay. **Insight:** replay *knows* the pairing, so we added explicit `{case_id: trace_id}` candidates to `run_gate`. No more guessing.

**6. 🔒 Proving hermetic replay**
How do you *show* CI isn't calling the real model? **We made the live model `raise`.** Hermetic run → never called → green. `--live` → it fires → red. The proof is the behavior.

> 🧠 **The meta-lesson:** almost every bug was "the system grouped/graded by the wrong signal." The fixes were all about making the *mechanism* — not the topic, not the tool payload — the thing that drives clustering, judging, and pairing.

---

## ⚠️ Sharp edges (honest limitations)

Things that are true today and worth knowing:

- 🔓 **Auth is wide open.** Single hardcoded dev key `tracely_dev_key`; no multi-tenancy/RBAC. Single project.
- 🧪 **Fixtures are name-keyed, outputs-only.** Same tool called twice with different args gets the same recorded output; error *status* isn't captured, so faithful error-condition replay is a refinement.
- 🟰 **All-SKIP passes the gate.** If a replay harness emits no matching traces, every case SKIPs and the gate is a (false) green. Only `failed > 0` fails.
- 🔁 **Digest matching is heuristic** in the non-replay `tracely gate` path: latest-300 ci traces, latest-wins per digest; identical inputs collide by design.
- 🧱 **Worker is single-process** (`--pool=solo`) — fine for the demo, not for scale. The whole stack is single-node docker-compose.
- 🕳️ **Silent failure surfaces.** Read a down backend? The UI renders empty tables (no error toast). A novel single failure (`min_cluster_size=2`) is dropped as noise until it recurs. The embedding cache has no invalidation if the mechanism-text logic changes.
- 🖥️ **UI loose ends:** the `⌘K` palette is decorative; the gate's agent is hardcoded to `planner`; no `prefers-reduced-motion`.
- 📦 **SDK isn't on PyPI yet** — the Action installs it from the repo until published.

> ✅ These are all known and mostly *intentional* MVP scoping — captured in the design docs' "next steps."

---

## 🚀 What's next

### 🎯 Near-term (natural follow-ups to what's built)

1. **Faithful fixtures** — key by `tool_call_id` + args, capture error *status*, so hermetic replay reproduces error conditions exactly.
2. **Richer gates** — `decide_gate` beyond fail-to-pass: eval-score-delta, cost, and latency gates (start as warnings, opt into blocking).
3. **Multi-tenancy + real auth** — accounts, per-project keys, RBAC. The thing that lets anyone but you use it.
4. **Trends dashboard** — failure-rate over time, regression pass-rate, MTTR, "which agent version regressed."
5. **Tune & harden** — clustering params on real data, GitHub comment pagination, an agent picker in the gate UI.

### 🌅 The bigger vision (designed in the dossier, not yet built 📐)

The design dossier describes a much larger system than the MVP. Clearly marking **📐 designed / not built**:

- 📐 **Content-addressed `AgentVersion`** (`config_hash` over prompts+models+tools+graph) so the gate is *cache-skippable* like CI.
- 📐 **Full 7-signal failure detection** + two-stage clustering (Drain3 + MinHash-LSH → nightly BERTopic) + **RCA** (first-failing-step localization) + **auto-test-generation**.
- 📐 **The replay shim & framework adapters** (LangGraph, OpenAI Agents SDK, Agno) + a `tracely.yaml` live runner. *(The SDK's `call_tool`/`call_llm` are the first concrete step toward this.)*
- 📐 **Canary-as-GateRun** — canary failures reopen the originating cluster → new regression cases that gate the *next* PR (closing the loop fully).
- 📐 **Multi-agent** — typed sub-agent edges, impact analysis, the replay matrix (mocked vs live), cross-service linked traces.
- 📐 **A zero-config GitHub App** (vs today's thin Action).
- 📐 **Codebase-aware fixes** — map spans → source via stack frames, suggest concrete code diffs.
- ⛔ **Permanently out of scope** (off-thesis): prompt management, dataset/experiment pillar, annotation queues, billing, Datadog-style metric dashboards.

> 🧱 **The bet behind it all:** the *left* half (ingest → store) is ~70% borrowed from Langfuse's proven substrate; the *right* half (promote → replay → gate) is net-new and sits on top of it. Build only the trace-native CI layer nobody else has, on a foundation that already works.

---

## 🏃 How to run it

```bash
# 1) bring up the whole stack (ports 8088 backend / 3001 frontend on this machine)
TRACELY_BACKEND_PORT=8088 TRACELY_WEB_PORT=3001 docker compose up -d

# 2) seed a realistic mix of failing runs (errors + silent + hallucinations)
make demo-failures TRACELY_API=http://localhost:8088

# 3) open the UI → http://localhost:3001
#    → Failure clusters → "Analyze failures"   (needs OPENAI_API_KEY in .env)
#    → open an Issue → Promote → it becomes a regression case

# 4) run the CI/CD gate locally
make gate    TRACELY_API=http://localhost:8088    # gate pre-emitted ci traces
make replay  TRACELY_API=http://localhost:8088    # re-run the agent (hermetic) + gate
make replay  TRACELY_API=http://localhost:8088 ENTRYPOINT=weather_agent:run_broken   # → FAIL
```

> 🔑 **`OPENAI_API_KEY`** lives in `.env` (gitignored). It powers *both* the failure-intelligence agents/embeddings *and* the LLM-judge evaluator. Without it, the core trace pipeline still runs 100% local & free.

---

## 🗂️ Codebase map

```
Tracely/
├── backend/tracely/            # the shared brain (API + all domain logic)
│   ├── api/routers/            # otlp, reads, cases, clusters, gate, health
│   ├── otel/mapping.py         # OTLP → first-class columns (multi-vendor)
│   ├── ingestion/              # blob-first write path
│   ├── evaluators.py           # the 5 online evaluators 🔬
│   ├── eval_runner.py          # runs them, writes scores
│   ├── fi.py · agents.py       # failure intelligence 🧹 (embeddings + 2 agents)
│   ├── cluster.py              # cheap signature clustering
│   ├── regression.py           # promote / fail-to-pass / fixtures / replay 🧪
│   ├── gate.py                 # the CI/CD gate engine 🚢
│   ├── models.py               # Postgres registry (SQLAlchemy 2.0)
│   ├── ch_migrations/          # ClickHouse DDL (events, scores)
│   └── migrations/             # Alembic (Postgres + pgvector)
├── workers/tracely_workers/    # 6-line Celery runtime
├── sdk/tracely_sdk/            # SDK + the `tracely` CLI (gate/replay) + hermetic fixtures
│   └── examples/               # weather_agent.py (run / run_broken)
├── frontend/app/               # Next.js 15 dashboard 🎨
├── .github/actions/tracely-gate/   # composite Action + README
├── design/part2-tracely/       # the design dossier (00-canonical is authoritative)
├── scripts/send_test_trace.py  # the demo trace generator (FIXED/SILENT/HALLUCINATE/…)
└── docker-compose.yml · Makefile
```

---

> 🛰️ **In one line:** Tracely makes your AI agent's worst production moments into tests that guard every future pull request — automatically detected, intelligently grouped, frozen with one click, and replayed for free on every PR.
>
> *Built end-to-end as an MVP. The loop is closed. 🟢*
