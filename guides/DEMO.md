# Tracely in 2 minutes — see the moat

Most agent-observability tools stop at *Observe → Detect → Triage* (a trace explorer + failure
clusters). That half is commoditized. Tracely's wedge is the other half: **promote a real
production failure into a hermetic regression test, then replay that exact trajectory in CI and
block the PR that brings it back** — with an LLM judge in the gate so it catches *bad answers*, not
just crashes.

This walkthrough populates the whole product and then **re-breaks an agent on purpose** so you can
watch the gate turn red. No dataset-first tool (Langfuse, LangSmith, Braintrust) can reproduce the
last step: their CI artifact is a curated dataset row, not *this specific trajectory with the tool
that errored*.

---

## 0. Populate the whole product (one command)

```bash
# Docker (recommended): brings up the stack AND runs the one-shot `demo` seeder
docker compose --profile demo up -d --build --wait

# …or, if the stack is already running:
docker compose exec backend python scripts/seed_demo.py
# …or local dev (backend + worker already up):  make demo
```

Open **http://localhost:3001**. Unlike a fresh instance, every sidebar stage is now populated —
including the two that are usually empty:

| Stage | Page | What you'll see |
|---|---|---|
| Observe | **Traces** | rich multi-turn conversations, every span shape, graded by online evaluators |
| Triage | **Failure clusters** | failures grouped into readable issues ("asserts a fact with no tool evidence") |
| **Test** | **Regression cases** | failing traces **promoted** into hermetic cases (the differentiated half) |
| **Ship** | **CI gates** | **red→green** gate-run history + a `NO_COVERAGE` safety run |

> If **Regression cases** or **CI gates** are empty, the seeder didn't finish — check the worker is
> running and re-run `scripts/seed_demo.py --force`.

---

## 1. The re-break (the part that matters)

The seeded suite was built from a real **silent failure**: the model asked for `get_weather` but
the agent never executed it, so it answered without the tool. That trace is promoted as a case whose
contract is *"the fix must actually call `get_weather`."*

Now play the agent author. Here are the two versions of the agent — the diff *is* the regression
([`sdk/examples/weather_agent.py`](sdk/examples/weather_agent.py)):

```python
def run(prompt):                       # the FIX
    answer = tracely.call_llm("gpt-4o", ..., input=prompt)
    tracely.call_tool("get_weather", lambda: '{"tempF": 64}')   # ← actually calls the tool
    return answer

def run_broken(prompt):                # the REGRESSION (someone deletes the tool call)
    return tracely.call_llm("gpt-4o", ..., input=prompt)        # ← answers without the tool
```

Replay the promoted suite against each version:

```bash
# ✅ the fix — gate PASSES
make replay ENTRYPOINT=weather_agent:run

# ❌ re-break it — gate FAILS (required tool `get_weather` never called)
make replay ENTRYPOINT=weather_agent:run_broken
```

<details><summary>Docker equivalents</summary>

```bash
docker compose exec backend sh -c 'cd /app && PYTHONPATH=sdk/examples tracely replay planner --entrypoint weather_agent:run'         # PASS
docker compose exec backend sh -c 'cd /app && PYTHONPATH=sdk/examples tracely replay planner --entrypoint weather_agent:run_broken'  # FAIL
```
</details>

The broken run exits non-zero and prints the **step-aligned trajectory diff** — the recorded
trajectory had a `get_weather` tool step; the candidate trajectory doesn't. That is the merge
blocker. In CI it's the same call, so the PR that reintroduced the bug is blocked. Open the new run
under **CI gates** in the UI to see the per-case verdict and the diff.

Replay is **hermetic**: `call_llm` / `call_tool` serve the *recorded* fixture, so the live model is
never called (the example's live model raises on purpose to prove it). The test costs nothing and is
deterministic — no API keys, no flakiness.

---

## 2. The judge in the gate (catches bad answers, not just crashes)

The seeder also promotes a **hallucination**: `get_weather` *succeeds*, but the agent's answer is
fabricated. A structural check passes this (the tool ran!) — only the **LLM judge inside the gate**
catches it. In **CI gates**, find the `feat/answer-fix` runs:

- while the answer is still hallucinated → structural PASS, **quality FAIL → gate FAIL**
- after the answer is faithful to the tool → **gate PASS**

This is what makes the README's claim — *"the recorded run is the test"* — literally true: the gate
re-grades answer quality on the replayed trace, not just tool structure.

---

## 3. The safety net (a gate that tested nothing must not be green)

Scroll to the `test-coverage` run: it matched **no** candidate traces, so every case SKIPped. Instead
of a false green, it reports **`NO_COVERAGE`** — a blocking status. A merge-blocker that passes when
it tested nothing is worse than no gate; this is the bug that fix closed.

---

## Why this is the moat, in one sentence

> A hermetic replay of your **exact production failure trajectory** — including the tool that errored —
> gating the PR, with an **LLM judge in the gate**. Incumbents gate a *dataset row*; Tracely gates the
> *trajectory*. A dataset row can't express "this specific path, with the tool that timed out, must
> not recur."

See [OVERVIEW.md](OVERVIEW.md) for the guided tour and [design/README.md](design/README.md) for the
full rationale.
