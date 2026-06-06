# 🛰️ Tracely — The Complete Guide

> **Trace-native CI/CD for AI agents.** Your agents' production traces become regression tests that block bad pull requests — automatically detected, intelligently grouped, frozen with one click, and replayed for free on every PR.

`v0.1.0 · MVP` • A living overview of what Tracely is, every interesting feature, why it's built this way, and what's next.

---

## 📑 Contents

1. [🧠 The big idea (ELI5)](#-the-big-idea-eli5)
2. [🎯 What Tracely is — and isn't](#-what-tracely-is--and-isnt)
3. [🦴 The spine + the product map](#-the-spine--the-product-map)
4. [🏗️ Architecture](#️-architecture)
5. [📚 The features](#-the-features)
   - [👀 Observe](#-observe--see-everything-your-agents-do) · [🔬 Detect](#-detect--grade-every-run) · [🧹 Triage](#-triage--group-failures-into-issues) · [🧪 Test](#-test--freeze-a-failure-into-a-regression) · [🚢 Ship](#-ship--gate-the-pull-request) · [📈 Insights](#-insights--trends) · [🎨 The UI](#-the-ui)
6. [🔑 Key decisions](#-key-decisions--why)
7. [🐛 War stories](#-war-stories-bugs-we-hunted)
8. [⚠️ Honest limitations](#️-honest-limitations)
9. [🚀 What's next](#-whats-next)
10. [🏃 Run it](#-run-it) · [🗂️ Codebase map](#️-codebase-map)

---

## 🧠 The big idea (ELI5)

> 🍼 Imagine a robot that answers customer questions and uses tools (look up an order, check the weather). One day it quietly breaks — it *says* it checked your order but never actually called the tool, and makes up an answer. 😱
>
> Most tools draw a chart that says "1 bad thing happened." Tracely does better: it **records that exact broken moment**, turns it into a **test** with one click, and from then on **re-plays that moment on every code change** — cheaply, offline, deterministically. If a change would bring the bug back, Tracely 🛑 **blocks the pull request** before it ships.

> 💡 **The recorded run *is* the test.** You never hand-author a dataset of example questions and ideal answers. Production already handed you the perfect failing example — Tracely just freezes it and guards against it forever.

Everything else — quality scores, failure clusters, suggested fixes, CI verdicts, trends — is **derived from the trace**. The trace is the source of truth. 🌱

---

## 🎯 What Tracely is — and isn't

| ✅ Tracely IS | ❌ Tracely is NOT |
|---|---|
| **Trace-native** — the production trace is the primary key | ❌ another Langfuse (it doesn't stop at "pretty traces") |
| **Agent-first** — agent / run / conversation / turn / tool are first-class | ❌ prompt management (the versioned thing is the *agent*) |
| **Regression-first** — tests are born from real failures | ❌ dataset-first eval (you never author `{input, expected}` up front) |
| **A CI gate** — produces a PASS/FAIL that blocks a PR | ❌ Datadog-for-LLMs (it's CI, not metric dashboards) |

> 🧭 **The wedge:** every incumbent (LangSmith, Braintrust, Phoenix, Galileo…) bottoms out in `Dataset → Experiment → Scorer`, which throws away the trajectory, the tool outputs, and the agent version that failed. Making the **trace** the literal primary key is the defensible white space.

---

## 🦴 The spine + the product map

One closed loop. The sidebar teaches it as four stages (+ Insights):

```
   👀 OBSERVE        🔬 DETECT         🧹 TRIAGE        🧪 TEST           🚢 SHIP
 ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
 │Production│───▶│ Failure  │───▶│ Failure  │───▶│Regression│───▶│  CI/CD   │
 │  Trace   │    │Detection │    │Clustering│    │   Test   │    │   Gate   │
 └──────────┘    └──────────┘    └──────────┘    └──────────┘    └────┬─────┘
       ▲                                                              │
       └──────────────── 🔁 a blocked-then-fixed PR ships green ──────┘
```

| Stage | Sidebar nav | What it does |
|---|---|---|
| 👀 **Observe** | *Traces · Trends · Dashboard* | OTLP traces, grouped into **conversation threads**, with a tabbed detail view |
| 🔬 **Detect** | *(automatic)* | Every run auto-graded — incl. **silent** failures |
| 🧹 **Triage** | *Failure clusters* | Failures grouped into named **Issues** (Engine-style) |
| 🧪 **Test** | *Regression cases* | One failure → a fail-to-pass test with hermetic fixtures |
| 🚢 **Ship** | *CI gates* | A PR replays the suite → a blocking green/red check |
| 📈 **Insights** | *Trends* | Failure-rate, gate pass-rate, MTTR over time |

Plus a **⌘K command palette** to jump anywhere.

---

## 🏗️ Architecture

> 🍼 A little team of helpers: a **doorman** (API) catches traces and stuffs the raw envelope in a **safe** (S3) so nothing is ever lost, then drops a ticket in a **queue** (Redis). A **back-office worker** files each step into a **fast filing cabinet** (ClickHouse) and grades it. A **notebook** (Postgres) tracks agents, tests, gates, evaluators. A **website** shows it all.

```
  your agent (Tracely SDK / any OTLP exporter)
                │  POST /v1/traces
                ▼
  FastAPI backend ── write raw OTLP to S3 (source of truth) ──▶ 🪣 MinIO/S3
        │          ── enqueue ───────────────────────────────▶ 🔴 Redis
        ▼  Celery worker (same package)
  parse → resolve agent → insert spans ─▶ 🧱 ClickHouse (events + scores)
        │  then auto-evaluate (debounced) ─▶ 🐘 Postgres+pgvector (registry, cases, gates, clusters, evaluators)
        ▼
  Next.js 15 frontend (SSR, no-store)
```

| Layer | Tech | Why |
|---|---|---|
| API + worker | **Python · FastAPI · Celery** | one shared `tracely` package — API (producer) & worker (consumer) never drift |
| Hot store | **ClickHouse** (`ReplacingMergeTree`, read `FINAL`) | millions of spans; one row per span; upserts late/duplicate spans |
| Registry | **Postgres 17 + pgvector** | agents, cases, gates, clusters, evaluators + cached failure embeddings |
| Blob | **MinIO / S3** | raw OTLP + replay fixtures = durable source of truth |
| Queue | **Redis** | Celery broker + result backend |
| UI | **Next.js 15 · React 19 · Tailwind** (zero UI libs) | a distinctive, hand-rolled dark dashboard |
| SDK + CLI | **`tracely_sdk`** (OpenTelemetry) | instrument agents + the `tracely` CI command |

> ⚡ **Dev loop:** backend/worker/migrate/frontend bind-mount the source and the Python packages are `uv`-editable — edit a file, restart the one service, no image rebuild. Whole stack: `docker compose up`.

---

## 📚 The features

### 👀 Observe — see everything your agents do

**Ingestion & data model ✅**
- **`POST /v1/traces`** accepts OTLP protobuf *or* JSON from any OTel SDK. **Blob-first**: raw bytes hit S3 *before* the queue, so nothing is ever lost.
- One row per span in ClickHouse `events`, with **first-class agent columns** (`agent_id`, `agent_run_id`, `conversation_id`, `turn_id`, typed caller/callee edges) + provenance (`evaluation_case_id`, `gate_run_id`, `failure_cluster_id`) + model/usage/cost.
- **Multi-vendor mapping** — lifts OpenInference, OTel GenAI, Langfuse, LangGraph, and Tracely-native attributes into the *same* typed columns. "Which level does a score target?" is a **column lookup**, not a read-time parse — the core edge over generic span storage.

**🧵 Conversation threads ✅** *(new)*
- The Traces page is no longer a flat list — traces **group into threads by conversation/session**, showing 👤 **first user message → 🤖 last assistant answer**, a turns badge, tokens, status, and time (LangSmith-style). Proper two-level grouping (resolve each trace's conversation from its root span, then group).
- **Filters + search** on the thread list (all / failing / multi-turn + free text), and a **⌘K command palette** to jump to any trace/case/cluster/gate.
- A **thread detail** page = a conversation replay: each turn shows the messages **and its full waterfall** (tool calling), with metrics and an "open trace →" link.
- The SDK takes `conversation=` on `agent()` to thread runs together.

**🌊 Tabbed trace detail ✅** *(new)*
- Opens on the **Trace** tab — a flamegraph **waterfall** (color-coded by span type, staggered animation) + a **tabbed span inspector**: **Input · Output · Attributes**. The Attributes tab is a full metadata table (gen_ai.*, tracely.*, model, env…).
- **Evaluations** live in their *own tab* (not cluttering the trace), with a verdict badge on the tab so you know if anything failed.
- Input/Output render as a **conversation/markdown view** (chat bubbles, collapsible JSON) instead of a raw `<pre>` dump. Tokens & cost roll up to the trace header.

`api/routers/reads.py` · `otel/mapping.py` · `components/{ThreadList,TraceBody,Waterfall,IO}.tsx` · `sdk/tracely_sdk`

---

### 🔬 Detect — grade every run

> 🍼 The moment a run lands, it's auto-graded (debounced ~4s so late spans settle). The grades become pass/fail **scores**.

**The checks ✅** (run automatically today):

| Check | Catches |
|---|---|
| **Run outcome** | any errored span 💥 |
| **Tool success** | a specific tool span that errored (pinpointed) |
| **Tool consistency** | 🥷 **silent failure** — a tool *requested* but never executed |
| **Latency** | over the latency budget |
| **Answer quality (LLM judge)** | wrong/unfaithful answers — grades the agent's *real* answer against its tool results (needs a key) |

> 🥷 **Silent failures are the star** — a run with zero error spans can still be broken (the model claims it called a tool but didn't, then hallucinates). No structural-only tool catches this.

**✅ User-defined** — per your steer that *the user must own evaluators*, the engine runs **configurable `Evaluator` records** (`models.Evaluator`, migration `0007`): each has a kind (`structural` | `llm_judge`), target agent/env, sampling, and config. The runner (`eval_runner`) loads the project's **enabled** records and dispatches each via `evaluators.run_evaluator` (the LLM judge takes a **custom rubric + threshold**); `seed.py` installs the recommended **template catalog** (`evaluators.TEMPLATES`) as editable rows so eval works out of the box. Evaluation is opt-in — a project with no enabled evaluators produces no scores (no hidden fallback). Still to add: a CRUD **API** + a management **UI**.

`evaluators.py` · `eval_runner.py` · scores → ClickHouse `scores` (deterministic ids → idempotent re-eval)

---

### 🧹 Triage — group failures into Issues

> 🍼 When 50 runs break, are they really the same 3 bugs? Tracely groups them — instantly by a fingerprint, then (on demand) with real AI that writes a plain-English **Issue**.

**Two clustering systems ✅**
1. **Signature clustering** — instant, free, structural fingerprint of each failure (so the Failures screen is never empty).
2. **Embedding + LLM clustering** ("Analyze failures") — embeds a **mechanism-focused** signature → cosine/HDBSCAN clusters (UMAP only at scale) → a per-cluster **LangChain `create_agent`** writes a semantic title/description/severity/fix → a **meta-consolidation agent** merges/splits into clean Issues. Grounded in the actual evaluator verdicts + tool results.

**🔬 Engine-style cluster detail ✅** *(new — LangSmith Engine parity)*
- An **occurrence histogram** (when this failure happened, over time).
- **Linked traces** — each member shows its 👤 input snippet + latency.
- A **suggested evaluator with copyable code** — a real detector keyed to the failure mechanism (e.g. for "tool not executed" it generates the `def evaluate(ctx)` that checks requested-vs-executed tools), matching the actual evaluator interface.
- One-click **Promote** → a regression test; **Ignore** to dismiss. Re-analysis **inherits** your promotions so they're never lost.

`fi.py` · `agents.py` · `cluster.py` · `api/routers/clusters.py` · `clusters/[clusterId]/page.tsx`

---

### 🧪 Test — freeze a failure into a regression

> 🍼 Click **Promote** on a bad run → it becomes a rule: "given this input, never fail this way again, and still use the right tools." The test starts **red** (it fails on the run it came from) and only goes **green** once truly fixed.

**What's built ✅**
- **`promote_trace`** — one trace → a durable `EvaluationCase`, idempotent (keyed by `input_digest`, so one flaky bug can't spawn 10,000 cases). Captures a reference trajectory, assertions, and **fixtures**.
- **Fail-to-pass contract** 🔴→🟢, validated at promote time — a case becomes PROMOTED only if the broken run genuinely fails it.
- **Trajectory match modes** (agentevals-style: superset/strict/unordered/subset).
- **🔒 Faithful hermetic fixtures** *(new)* — fixtures are now an **ordered list of calls**, each with its **args, output, AND error status**. The SDK's `call_tool(name, fn, args=…)` / `call_llm` serve them in order (or by args), and **raise `ToolError`** when the recorded call errored — so a tool that timed out in production replays as a timeout, and the gate reproduces the *exact* failure. (Before, both calls got one output and the error was silently dropped → a spurious PASS.)
- **🛡️ Run-outcome assertion** *(new)* — `allow_tool_errors`: a tool *may* fail (it's the replayed environment) as long as the agent's own run is clean — so a graceful **error-handling fix can pass** while a crashing agent still fails. Auto-set when the source failed because a tool errored *and* the agent crashed.

`regression.py` · `trajectory.py` · `api/routers/cases.py` · `sdk/tracely_sdk` (`call_tool`/`call_llm`/`fixtures`)

---

### 🚢 Ship — gate the pull request

> 🍼 On every PR, the `tracely` CLI re-runs your agent against all the saved failures and **blocks the merge** if any regress — posting a green/red check + comment right on the PR. For free, by replaying recorded tool/LLM outputs so CI never calls a real model.

**What's built ✅**
- **`tracely` CLI** (ships in the SDK, stdlib-only): `tracely gate` (match pre-emitted ci traces by digest) and `tracely replay` (the turnkey path — re-run your agent on each promoted case, then gate).
- **Explicit pairing** — replay knows which trace ran which case, so it gates with an exact `{case_id: trace_id}` map (no digest guessing).
- **Hermetic by default** — fixtures served via `call_tool`/`call_llm`; `--live` opts into real calls.
- **GitHub PR check** — a commit status `tracely/regression-gate` (the blocking check) + an upserted PR comment, exit codes `0/1/2`. A composite **GitHub Action** + example workflow ship in `.github/`.
- **💸 Soft delta gates** *(new)* — the gate rolls up candidate **latency** and **token usage**, compares to the agent's last **green** gate, and posts non-blocking **⚠️ warnings** when a metric regresses (default 25% thresholds). **Fail-to-pass stays the only hard gate** unless `gate_block_on_warnings`. Metrics + warnings persist on `GateRun` (migration `0006`) and render in the CLI, the PR comment, and the gate UI.

`gate.py` · `api/routers/gate.py` · `sdk/tracely_sdk/cli.py` · `.github/actions/tracely-gate/`

---

### 📈 Insights — Trends

**What's built ✅** — `GET /api/trends` + a `/trends` page: **failure-rate over time, gate pass-rate, open-vs-resolved issues, regression-test count, and an MTTR (failure → test) proxy**, with hand-rolled bar charts. Scoped to **regression-loop health** (on-thesis), not generic Datadog-style metrics.

`api/routers/analytics.py` · `trends/page.tsx` · `components/Bars.tsx`

---

### 🎨 The UI

Hand-rolled Next.js 15 dashboard, **zero UI libraries** (Tailwind + clsx + inline SVG icons). Near-black `ink` palette, **cyan "signal"** accent, faint grid, glow, staggered reveals; custom fonts (Bricolage Grotesque / Hanken Grotesk / JetBrains Mono). Every page is a **server component** fetching the backend with `cache:"no-store"`; mutations go through thin Next route proxies that keep the key server-side.

Signature touches: **`[ID]` copy chips** (long ids never shown raw), the **⌘K command palette**, list **filters**, the **conversation/markdown** IO renderer, and **tabbed** trace + span panels.

---

## 🔑 Key decisions — why

| 🧩 Decision | 💡 Why | ⚖️ Tradeoff |
|---|---|---|
| Trace is the source of truth (not dataset-first) | a dataset row can't express "this exact failure trajectory must not recur" | thinner cold-start |
| Agent semantics as **indexed columns** | level lookups are O(1), not read-time parses | wider, opinionated schema |
| **Blob-first** ingestion | nothing lost on a worker/queue outage | an S3 PUT on the request path |
| Embed the **mechanism**, not the topic | cluster by *how* it broke, so unrelated inputs with the same bug group | two texts per trace |
| Skip UMAP on small/duplicate sets | UMAP *invents* clusters on few near-identical vectors | two clustering regimes |
| Fixtures key by **args + order + error** | replay reproduces the real failure, including errors | a richer bundle |
| **Run-outcome** vs strict `no_error` | error-*handling* fixes can pass while crashes fail | a per-case opt-in |
| Only fail-to-pass is a **hard** gate | cost/latency are noisy in replay → warnings | quality regressions can merge until opted in |
| Threads list status = **structural** failures | the strict LLM judge nitpicks good answers → keep the list honest | list vs detail show slightly different status |
| **Evaluators as data** (in progress) | the user owns what counts as a failure | runtime/UI rewiring |
| Hand-rolled design system | distinctive look, tiny bundle | no a11y primitives for free |

---

## 🐛 War stories (bugs we hunted)

- 🌀 **UMAP invented clusters.** The first embedding run merged distinct failure modes and hallucinated "timeout." Root cause: UMAP scatters near-duplicate vectors and HDBSCAN finds phantom structure. Fix: cosine-distance clustering below a size threshold.
- 🧲 **Domain drowned out mechanism.** Embeddings were ~80% shared "weather" text, so the failure mode was noise. Fix: a terse mechanism-focused embedding signature.
- 🧑‍⚖️ **The judge graded the wrong thing.** A hallucination scored a fragile 0.5 — because the judge was grading the *tool's* raw payload, not the agent's answer. Fix: grade the real answer + feed tool results as grounding → it nails it at 0.0.
- 🔒 **Hermetic replay was unsound for errors.** Name-keyed, outputs-only fixtures replayed an errored tool *clean* → a spurious PASS. Fix: ordered, args-keyed, error-bearing fixtures that raise `ToolError`.
- 🩺 **The strict judge made everything look broken.** It failed perfectly fine support answers — which is exactly why the thread list shows *structural* status and why **user-defined evaluators** matter.
- 🩹 **Empty trends charts.** Bars had % heights with no definite-height parent → they collapsed to zero. Fixed the bar component.

---

## ⚠️ Honest limitations

- 🛠️ **No evaluator management API/UI yet** — evaluators are fully DB-backed and the runner loads them (seeded with the recommended catalog), but editing/adding one means touching the `evaluators` table directly; the CRUD API + Evaluators page are still to build.
- 🔓 **Auth is wide open** — single dev key `tracely_dev_key`, no multi-tenancy/RBAC, single project.
- 🟰 **All-SKIP passes the gate** — a replay harness that emits no matching traces yields a false green.
- 🧱 **Single-node, single-process worker** (`--pool=solo`) — fine for the demo, not for scale.
- 🤖 **Structural gating only** — a *bad answer* with no error span isn't caught by the gate yet (needs the LLM-judge wired into replay).
- ⏱️ **Latency/cost ≈ 0 in hermetic replay** — the soft gates are most meaningful for live cases / instrumented token usage.

---

## 🚀 What's next

**Near-term**
1. **Evaluator management API + UI** — the runner already loads DB `Evaluator` records and `seed.py` installs the recommended (editable) catalog; what's left is a CRUD API + an Evaluators page with a "set up evaluator" flow (so the "Create evaluator" button on a cluster lands somewhere).
2. **Eval-score-delta gate** + an LLM-judge assertion inside replay.
3. **Multi-tenancy + real auth.**

**The bigger vision** *(designed in the dossier, not built 📐)* — content-addressed `AgentVersion` gating (`config_hash`), full 7-signal detection + RCA + auto-test-gen, the canary-as-GateRun loop, multi-agent edges + impact analysis, a zero-config GitHub App, and codebase-aware fixes.

> 🧱 **The bet:** the *left* half (ingest → store) is ~70% borrowed from Langfuse's proven substrate; the *right* half (promote → replay → gate) is net-new on top. Build only the trace-native CI layer nobody else has.

---

## 🏃 Run it

```bash
# whole stack (ports 8088 backend / 3001 frontend on this machine)
TRACELY_BACKEND_PORT=8088 TRACELY_WEB_PORT=3001 docker compose up -d

make demo-failures      TRACELY_API=http://localhost:8088   # seed errors/silent/hallucination runs
# (multi-turn convos: uv run python sdk/examples/seed_conversations.py)

# UI → localhost:3001  →  Failure clusters → "Analyze failures" (needs OPENAI_API_KEY in .env)
#                     →  open an Issue → Promote → a regression case

make gate    TRACELY_API=http://localhost:8088              # gate pre-emitted ci traces
make replay  TRACELY_API=http://localhost:8088              # re-run the agent (hermetic) + gate
```

> 🔑 `OPENAI_API_KEY` lives in `.env` (gitignored) — it powers the FI agents/embeddings *and* the LLM judge. Without it, the core pipeline runs 100% local & free.

---

## 🗂️ Codebase map

```
Tracely/
├── backend/tracely/            # the shared brain (API + all domain logic)
│   ├── api/routers/            # otlp, reads (traces+sessions), cases, clusters, gate, analytics, health
│   ├── otel/mapping.py         # OTLP → first-class columns (multi-vendor)
│   ├── evaluators.py           # check implementations + run_evaluator dispatch + TEMPLATES 🔬
│   ├── eval_runner.py · fi.py · agents.py · cluster.py   # detect + failure intelligence 🧹
│   ├── regression.py · trajectory.py                     # promote / fail-to-pass / fixtures / replay 🧪
│   ├── gate.py                 # CI/CD gate + soft delta gates 🚢
│   ├── models.py               # Postgres registry (incl. Evaluator, GateRun metrics)
│   ├── ch_migrations/ · migrations/ (0001–0007)
├── workers/tracely_workers/    # thin Celery runtime
├── sdk/tracely_sdk/            # SDK (agent/conversation/call_tool/call_llm/fixtures) + the `tracely` CLI
│   └── examples/               # weather agents, seed_conversations, seed_handler, seed_multicall
├── frontend/app/               # Next.js 15 — traces(threads)/sessions, clusters, cases, gates, trends, dashboard 🎨
│   └── components/             # ThreadList, TraceBody(tabs), Waterfall, IO, CommandPalette, Bars, CodeBlock, …
├── .github/actions/tracely-gate/   # composite Action + README
├── design/part2-tracely/       # the design dossier (00-canonical is authoritative)
└── docker-compose.yml · Makefile
```

---

> 🛰️ **In one line:** Tracely turns your AI agents' worst production moments into tests that guard every future pull request — observed as conversation threads, auto-detected, grouped into Issues, frozen with one click, and replayed for free (and faithfully) on every PR.
>
> *The core loop is closed end-to-end; the UI is now LangSmith-grade; user-defined evaluators are the live build. 🟢*
