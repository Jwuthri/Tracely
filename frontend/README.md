# `frontend/` — the Tracely web app

Next.js (App Router) UI for the whole product spine — **Observe → Triage → Test → Ship → Insights**. TypeScript, Tailwind CSS, and a deliberately tiny dependency set (only `clsx` on top of `next`/`react`).

- **Next.js 15** (App Router, RSC) · **React 19** · **Tailwind CSS 3.4** (config in [`tailwind.config.ts`](tailwind.config.ts)) · **clsx**.
- No component library, no data-fetching library, no chart library — charts are hand-rolled (`Bars.tsx`), tables are real `<table>`s, state is plain React hooks. This keeps the bundle small and the rendering legible.

```bash
# needs the backend running (see ../README.md). Then:
pnpm install        # or npm install
pnpm dev            # http://localhost:3001   (in Docker it's :3001 too)
```
Two env vars (server-side only): `TRACELY_API` (default `http://localhost:8000`) and `TRACELY_KEY` (default `tracely_dev_key`).

---

## How data flows (the one pattern to know)

There are **two** ways the UI talks to the backend, and which one you use depends on whether the component is a Server or Client Component:

- **Server Components (pages)** call [`app/lib/api.ts`](app/lib/api.ts) **directly** — these run on the server, attach `Authorization: Bearer ${TRACELY_KEY}`, and fetch the backend with `cache: "no-store"`. The key never reaches the browser.
- **Client Components** (the interactive table, the ⌘K palette, action buttons) fetch **Next route handlers under [`app/api/`](app/api/)** instead. Each handler is a thin proxy that re-issues the request to `TRACELY_API` with the Bearer key + `no-store`. This keeps the key + API base server-side and gives the browser clean typed JSON.

> Rule of thumb: a page renders with `lib/api.ts`; anything that fetches *after* a click (lazy expand, search, promote, run gate, SSE eval stream) goes through an `app/api/*` proxy.

---

## App shell

| File | Role |
|---|---|
| `app/layout.tsx` | Root layout: `_providers` (auth context) + `Sidebar` + content (`Topbar` + `<main>`) + `CommandPalette`. Loads display/sans/mono fonts. `<main>` is capped at `max-w-[1240px]` (the trace table can break out of this — see Enlarge). |
| `components/Sidebar.tsx` | Left nav (244px), grouped by the spine: **Observe** (Dashboard, Traces, Trends) · **Triage** (Failure clusters) · **Test** (Regression cases) · **Ship** (CI gates). Footer shows the project + `prod` env. |
| `components/Topbar.tsx` | Breadcrumbs + the ⌘K trigger. |
| `components/CommandPalette.tsx` | ⌘K/Ctrl-K global search → `/api/search`; result types trace / issue / case / gate with keyboard nav. |
| `components/AccountMenu.tsx` | User avatar menu (top-right) — profile, sign out, links to settings. Renders only in `local`/`clerk` auth modes. |
| `app/_providers/` | Auth context provider + Clerk dynamic-import wrapper (auth mode is resolved server-side and passed down as a prop). |
| `app/globals.css` + `tailwind.config.ts` | Theme tokens — `ink` (surfaces, near-black `#090b10`), `line` (borders), `fg`/`fg-muted`/`fg-faint` (text), `signal` (cyan accent), `ok/fail/warn/info`, and span-type colors `t_agent/t_llm/t_tool/t_retriever/t_step`. Utilities: `.card`, `.hairline`, `.reveal` (staggered fade-up), `.bg-grid`. |

## Route groups

```
app/
  (auth)/           # sign-in, sign-up, register, login, accept-invite + layout
  (app)/            # authenticated app shell
    settings/
      api-keys/     # API key management
      team/         # member list + InviteManager
```

## Pages (`app/**/page.tsx`)

All are **Server Components** unless noted; each lists the `lib/api.ts` calls it makes.

| Route | Fetches | Renders |
|---|---|---|
| `/` | `getStats`, `getTraces`, `getCases` | Dashboard — 4 stat cards + recent traces & cases. |
| `/traces` | `getSessions` | `TracesExplorer` (filter + search + date range) wrapping the hierarchical **TraceTable** in list mode. |
| `/traces/[traceId]` | `getTrace` | Single trace header (spans/latency/**usage totals**, `PromoteButton` if failing) + `SingleTraceView` (Table / Timeline / Evaluations tabs). |
| `/sessions/[threadId]` | `getSession` + `getTrace` per turn | A conversation, pre-expanded: builds a `ConvNode` with all turns + spans and renders **TraceTable** in detail mode. Header shows conversation usage totals. |
| `/clusters` | `getClusters` | Failure-cluster table + `RebuildButton` ("Analyze failures"). |
| `/clusters/[clusterId]` | `getCluster` | Issue detail — histogram, description, proposed fix, suggested evaluator (`CodeBlock`), member traces, `ClusterActions`. |
| `/cases` | `getCases` | Regression cases — title, status, fail→pass contract, last verdict, source trace. |
| `/cases/[caseId]` | `getCase` | Case detail — assertions, reference trajectory, `ReplayControls` + replay history. |
| `/gates` | `getGates` | Gate runs — result, agent/env/ref, passed/failed/skipped, `RunGateButton`. |
| `/gates/[gateId]` | `getGate` | Gate detail — status banner, soft warnings, per-case verdicts. |
| `/trends` | `getTrends` | Insights — stat cards + `Bars` charts (daily traces/failures, gate pass/fail). |
| `/settings/api-keys` | — | API key management (create/revoke ingest keys). |
| `/settings/team` | — | Team members list + `InviteManager` (send/revoke invitations). |

## Data layer

- **`app/lib/api.ts`** — server-side fetchers + all shared types. One function per backend endpoint (`getSessions`, `getSession`, `getTrace`, `getClusters`, `getCases`, `getGates`, `getTrends`, `getStats`, …) plus the type model the whole UI shares: `SpanOut`, `EvalScore`, `Thread`/`ThreadTurn`/`FullTurn`/`ConvNode` (the conversation→turn→span tree), `EvalCase`, `FailureCluster`, `GateRun`, `Stats`, `Trends`.
- **`app/lib/evaluators.ts`** — evaluator CRUD helpers + types (`EvaluatorRow`, `EvaluatorTemplate`). Wraps the `/api/evaluators/*` proxies for client-side fetches.
- **`app/lib/usage.ts`** — pure token/cost derivation, shared by the table **and** the detail-page headers so they compute identically. `spanUsage`/`turnUsage`/`convUsage` aggregate input/output/thinking tokens; `rateFor` prices them from a per-model rate table; `usageSummary`/`fmtUsd` format. `total_tokens` = input + output (matches the backend total); thinking tokens are surfaced separately.
- **`app/api/*/route.ts`** — the client→backend proxies: `session` (lazy-load a conversation's turns), `trace` (lazy-load a turn's spans), `search` (⌘K), `evaluators/` (CRUD + generate + SSE run stream), plus action proxies (`promote`, `cluster`/`cluster-rebuild`, `gate`, `replay`). Each forwards to `TRACELY_API` with the Bearer key + `no-store`.

## Components

**`TraceTable.tsx`** is the centerpiece — a real `<table>` rendering the **Conversation → Message → Step** tree (modeled on a TurnWise-style spreadsheet):
- **Column groups** with level badges and subtle group dividers: **C** (conversation: title, time, duration, summary, **metadata**, usage), **M** (message/turn: role, #, time, duration, content, usage), **S** (step/span: #, type, time, duration, agent, model, name, input, output, usage). Depth-coloured left borders (C=blue, M=green, S=purple).
- **Evaluator columns** — each enabled evaluator appears as a dynamically-loaded column. The header is a button that opens `AddColumnModal`; cells render a score pill (value + verdict badge) that opens a floating `FloatingPanel` (via `JsonView.tsx` Pill/FloatingPanel) with the full score detail. PASS/FAIL/numeric/boolean/text/JSON outputs each render appropriately. Clicking the pill does not propagate to row navigation (portal event isolation).
- **Rich cells:** any message object (`{role, content}`) — including assistant **completions** — renders as a compact role pill that opens a floating bubble panel; raw structured data with no `role` → a `{ }`/`[ ]` JSON pill with a syntax-highlighted panel; multimodal message content → text + clickable image/file chips; per-level **usage** → a Σ pill with a Tokens/Cost breakdown; `THINKING` is a first-class span type. Floating panels use `createPortal` to escape the table's overflow.
- **Two modes:** *list* (seeded with conversation summaries; turns + spans **lazy-load** on expand via the `/api/session` and `/api/trace` proxies) and *detail* (the whole tree pre-seeded, everything open).
- **Controls:** Expand/Collapse All (cascades to the step level), a Columns visibility menu, an Enlarge (full-width breakout) toggle, and the **+ Add Column** button to manage evaluator columns — all **persisted to `localStorage`**.

| Component | Role |
|---|---|
| `TracesExplorer.tsx` | `/traces` filter (All/Failing/Multi-turn) + search + `DateRangePicker`, wrapping `TraceTable` (list mode). |
| `SingleTraceView.tsx` | One trace as tabs: Table (`TraceTable` detail) / Timeline (`Waterfall`) / Evaluations. |
| `SessionView.tsx` | Conversation-level view wrapping `TraceTable` (detail mode). |
| `Waterfall.tsx` | Gantt-style span timeline (bars by type, depth-indented, I/O on expand). |
| `IO.tsx` | Smart input/output renderer (chat arrays → bubbles, objects → JSON, else text). |
| `JsonView.tsx` | Shared JSON rendering primitives: `HighlightedJson`, `prettyJson`, `Pill`, `FloatingPanel`, `IconBox`, `JsonPill`, `ExpandableText`, `Plain`. Used by the table, timeline, and attributes panel. |
| `AddColumnModal.tsx` | Multi-step modal for adding evaluator columns: pick type (browse catalog / manual / AI-generate) → pick granularity level → configure (prompt, output type, model, threshold, output schema). |
| `OutputSchemaBuilder.tsx` | Drag-and-drop JSON schema builder for LLM-judge `json` output type — fields with names, types, descriptions, and enum constraints. |
| `InviteManager.tsx` | Team invite flow (send invitation by email, list pending invitations, revoke). |
| `DateRangePicker.tsx` | Date range filter for the traces explorer. |
| `ui.tsx` | `Badge`, `verdictVariant`/`statusVariant`, `TypeChip` (span-type chip), `StatCard`. |
| `icons.tsx` | Inline stroke SVG icon set. |
| `Bars.tsx` | Hand-rolled stacked bar charts for `/trends`. |
| `CopyId.tsx` · `TimeAgo.tsx` · `CodeBlock.tsx` · `RowLink.tsx` | Copy-to-clipboard id chip · relative time (SSR-safe) · syntax-highlighted code w/ copy · clickable row wrapper. |
| `PromoteButton` · `RebuildButton` · `RunGateButton` · `ReplayControls` · `ClusterActions` | The write actions (promote a trace, rebuild clusters, run a gate, replay a case, ignore/promote a cluster) — each POSTs an `app/api/*` proxy. |

## Key decisions (and why)

1. **Tiny dependency surface.** Only `clsx` beyond Next/React — no UI kit, table lib, or chart lib. The UI stays fast, legible, and fully in our control (the trace table needed bespoke rendering anyway).
2. **Server fetch for pages, proxy for clicks.** Pages fetch the backend directly (key stays server-side, no client waterfall); interactive fetches go through `app/api/*` so the key/API base are never in the browser and caching is forced off.
3. **Usage math lives in one pure module.** `lib/usage.ts` is shared by the client table and the server-rendered headers, so a step, a message, a conversation, and a page header always agree on tokens + derived cost.
4. **The trace table is a real `<table>`, lazy and rich.** Hierarchical conv→message→step with per-level columns and inline pills; list mode lazy-loads so `/traces` stays cheap, detail mode pre-seeds so a single conversation renders fully.
5. **Evaluators as dynamic columns.** Each enabled evaluator is a column in the same table — no separate Evaluations tab to navigate to. Adding a column is a guided modal flow; the column's scores stream in live via SSE.
6. **Portal event isolation for floating panels.** `FloatingPanel` renders into `document.body` via `createPortal`. The backdrop click calls `e.stopPropagation()` to break React's synthetic event bubbling and prevent row-navigation events from firing.
7. **Cost is derived in-app.** The backend doesn't trace cost, so price comes from a per-model rate table in `usage.ts`; one open question (see the PRD) is whether to compute `cost_details` at ingest instead so it's authoritative everywhere.
8. **Theme as tokens.** Semantic color tokens (`ink/line/fg/signal/ok/fail/...` + span-type colors) keep the dark UI consistent and make per-type/per-verdict styling declarative.
