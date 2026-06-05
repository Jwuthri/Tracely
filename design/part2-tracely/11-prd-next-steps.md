# PRD — Next milestone: close the Observe → Detect loop

> Near-term execution PRD. Long-term roadmap lives in [10-mvp-and-roadmap.md](10-mvp-and-roadmap.md); the core loop that's already built is in the MVP-state memory + [OVERVIEW.md](../../OVERVIEW.md). This doc is what to build **next**.

_Status: draft · 2026-06-05_

---

## Where we are

The **trace explorer** (Observe) was just rebuilt: a TurnWise-style hierarchical table (Conversation → Message → Step) with rich inline rendering — chat-transcript pills, JSON pills, multimodal content (text + image/file chips), `THINKING` as a first-class span type, per-level **Usage** (tokens + derived cost) at step / message / conversation, group separators, full-width toggle, persisted column visibility, and row → trace navigation. Detail-page headers show conversation totals.

The **evaluators** layer (Detect) is **mid-refactor** and the seam where the next work lives:
- Evaluators were moved from hardcoded → DB-backed records (`Evaluator` model + migration `0007_evaluators.py`), but **`0007` is unapplied**, nothing seeds the table, and `eval_runner` runs a **built-in `TEMPLATES` fallback** (logs `evaluator_load_failed` per trace).
- There's **no UI** to view/edit/add evaluators.
- The table's per-column / per-row **"▶ Run" buttons are decorative**, and the eval columns (Response Quality, etc.) were removed pending this work.

## Goal

Make evaluators **first-class, editable, and visible** — and connect them back into the trace explorer — so the Observe → Detect loop is complete and self-serve. Then take the explorer from "demo-scale" to "GA".

## Non-goals (this milestone)

- New failure-intelligence / clustering work (already built; untouched).
- Gate depth (score-delta, LLM-judge assertion) — tracked as P3 below, not committed.
- A full design-system pass.

---

## P0 — Evaluators become first-class

**Problem.** Evaluators only run via a fallback; users can't see, add, edit, enable/disable, or target them; the table's eval affordances are dead; the `evaluators` table doesn't exist in deployed DBs.

**Scope.**
1. **Schema + seeding.** Apply `0007`; seed the recommended `evaluators.TEMPLATES` into the `evaluators` table per project (on project creation + a one-time backfill for existing projects).
2. **Evaluators API (CRUD).** `backend/tracely/api/routers/evaluators.py`: list / create / update / enable-disable. Fields: `name, kind (structural|llm_judge), score_name, level (CONVERSATION|AGENT_RUN|TOOL), enabled, target_agent, target_env, sampling, config`.
3. **`eval_runner` honors config.** Filter the loaded evaluators by `target_agent` / `target_env`, apply `sampling`; drop the fallback once seeding is guaranteed (keep it as a safety net only). Remove the noisy `evaluator_load_failed` path.
4. **Evaluators management page** (`/evaluators`, sidebar under Detect): list with enable toggles, edit config (llm-judge prompt + threshold; structural check + params), and a **"Run on recent traces"** action.
5. **Wire the trace table.** Bring back **eval columns driven by the project's enabled evaluators** — one column per evaluator, placed in its level's group (C/M/S), cell = the score verdict for that row. Make the column-header **▶ Run** re-evaluate that evaluator over the visible rows, and the row **▶ Run** re-evaluate that row; cells update in place.

**Acceptance.**
- A fresh project shows the recommended evaluators at `/evaluators`; toggling/adding one changes which scores get written on ingest.
- The trace table renders live eval columns from enabled evaluators; header/row ▶ Run triggers a re-eval and the verdict cell updates.
- No `evaluator_load_failed` in worker logs under normal operation.

**Effort:** L. **Touches:** `backend/tracely/eval_runner.py`, `evaluators.py`, `models.py`, `migrations/0007`, new `routers/evaluators.py` + `schemas`, `frontend/app/evaluators/`, `components/TraceTable.tsx`.

---

## P1 — Trace Explorer → GA (scale + ergonomics)

**Problem.** The explorer works at demo scale (50-thread cap, client-side filter, no virtualization). It needs to hold up at real volume and feel finished.

**Scope.**
- **Server-side pagination / infinite scroll** for `/traces` + **server-side filters** (status, agent, env, date range). Extend the existing ⌘K `/api/search`.
- **Row virtualization** for large expanded trees.
- **Sticky table header** on vertical scroll (needs the horizontal-scroll-wrapper restructure flagged earlier).
- **Saved views** — named column-visibility + filter presets (today only a single persisted state in `localStorage`).
- Polish empty / loading / error states; keyboard nav (`j`/`k`, `enter` to open a row).

**Acceptance.** `/traces` stays smooth at 1k+ threads; filters/search run on the backend; the header stays pinned while scrolling a long tree.

**Effort:** M. **Touches:** `routers/reads.py`, `TracesExplorer.tsx`, `TraceTable.tsx`.

---

## P2 — Make it real: projects, auth, multi-tenancy

**Problem.** Single shared dev key (`tracely_dev_key`), effectively one project.

**Scope.** Real project model + API-key management + minimal auth (session or bearer), a project switcher, and scoping all reads/writes by project (data is already keyed by `project_id`). Key-management UI.

**Acceptance.** Two projects are fully isolated; keys can be created/revoked in the UI; the default-project dev flow is unchanged.

**Effort:** L. (From the MVP "not yet built" list.)

---

## P3 — Gate depth (deferred / not committed)

From the MVP backlog, pick up when P0–P2 land: **eval-score-delta gate**, **LLM-judge assertion in the gate**, **agent-version regression attribution**, **canary-as-GateRun**.

---

## Open questions (need a decision)

1. **Column density** — auto-show a column per enabled evaluator (could be many), or only "pinned" evaluators? Lean: pinned, with the rest reachable via the Columns menu.
2. **Manual-run cost** — the LLM judge costs money; gate "▶ Run" behind a confirm + sampling cap?
3. **Multimodal rendering** — always inline image thumbnails, or behind a setting (PII / payload size)?
4. **Cost source of truth** — keep deriving price in the app from a model-rate table, or compute `cost_details` at ingest (backend) so it's authoritative everywhere?
