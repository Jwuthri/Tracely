# Tracely agents demo

Three end-to-end agent apps — **LangChain/LangGraph**, the **OpenAI Agents SDK** and
**Anthropic (raw Claude API)** — each built idiomatically for its framework, each traced by
[Tracely](https://github.com/Jwuthri/Tracely) with a couple of lines.

All three play the **same 4-turn customer conversation** against the same tiny fake store
([`shared.py`](shared.py)), so you can open Tracely and compare, side by side, how the same
session looks across frameworks: the agent graph, the handoffs, every tool call, the tokens,
the cost — and the two moments where things get interesting:

- **turn 2** asks for a $189 refund while the payments system only auto-approves up to $100 —
  the `issue_refund` tool fails, each framework recovers its own way, and Tracely flags it;
- **turn 4** is a prompt injection ("ignore all previous instructions…") — caught by a
  guardrail (OpenAI / Anthropic demos) or the supervisor's policy (LangGraph demo).

## What's inside

| Demo | Framework | Patterns shown |
|---|---|---|
| [`demo_langgraph.py`](demo_langgraph.py) | LangChain 1.x / LangGraph 1.x | Supervisor with workers as **subagents-as-tools** (`create_agent`), custom typed graph **state** read from tools via `ToolRuntime`, multi-turn **memory** (`InMemorySaver` + `thread_id`) |
| [`demo_openai_agents.py`](demo_openai_agents.py) | OpenAI Agents SDK | Triage agent with **handoffs**, a sub-agent used **as a tool** (`agent.as_tool`), an **input guardrail** tripwire, local **context** (`RunContextWrapper`), **sessions** (`SQLiteSession`) |
| [`demo_anthropic.py`](demo_anthropic.py) | Anthropic Claude API | **Orchestrator → worker delegation** on the raw Messages API tool loop, a versioned **skill** (refund playbook), a deterministic **guardrail**, a tool failure surfaced as an ERROR span |

Each file is self-contained and heavily commented — read it top to bottom as the tutorial.

## Run it

**Prereqs:** [uv](https://docs.astral.sh/uv/), a running Tracely (from the repo root:
`docker compose up -d --build --wait` → UI on `:3001`, API on `:8000` — or point
`TRACELY_API`/`TRACELY_KEY` at a hosted instance), and `OPENAI_API_KEY` and/or
`ANTHROPIC_API_KEY` in the repo-root `.env` (the demos read it; `TRACELY_API`/`TRACELY_KEY`
default to the local dev stack).

```bash
cd demo
uv sync                        # its own venv — separate from the repo's uv workspace

uv run demo_langgraph.py       # needs OPENAI_API_KEY
uv run demo_openai_agents.py   # needs OPENAI_API_KEY
uv run demo_anthropic.py       # needs ANTHROPIC_API_KEY
```

(or `make langgraph` / `make openai-agents` / `make anthropic` / `make all`.)

Each script prints the agent's answers, then flushes its traces to Tracely. The demos use
the published [`tracely-ai`](https://pypi.org/project/tracely-ai/) package (≥ 0.3.3) —
exactly what your own app would install. git tag sdk-v0.3.4 && git push origin sdk-v0.3.4

## The integration, in full

```python
import tracely_sdk as tracely

tracely.init(endpoint=TRACELY_API, api_key=TRACELY_KEY,
             service_name="support-desk", env="prod",
             instrument=["langchain"])          # or ["openai-agents"], ["anthropic"], "auto"

for i, question in enumerate(TURNS):
    with tracely.trace(agent="supervisor", conversation="conv-1", turn=i,
                       user="mara@example.com", agents=CATALOG if i == 0 else None):
        answer = run_agent(question)            # your code, unchanged

tracely.flush()
```

That's the whole thing for the framework demos: `init()` activates the auto-instrumentor
(every generation, tool call, agent run and handoff becomes a span with zero span code), and
`trace()` stamps agent / conversation / turn / user onto all of them so Tracely can group
turns into conversations, grade them, and gate PRs on them.

The Anthropic demo has no framework, so it also shows the **manual API**: `@tracely.observe`
turns plain functions into TOOL/AGENT spans, and `tracely.delegate` / `agent` / `skill` /
`guardrail` context managers record the handoff edge, the sub-agent run, the playbook version
and the safety check as first-class observation types.

## What to look at in Tracely

Open the UI (local: <http://localhost:3001>) after a run:

- **Traces** — each turn is one trace: a named agent root, GENERATION spans with model +
  token usage, TOOL spans with args → result. In the LangGraph trace the supervisor's tool
  call wraps the whole worker subgraph; in the OpenAI trace you see the handoff chain; in the
  Anthropic trace the DELEGATE → AGENT → SKILL nesting.
- **The failed refund (turn 2)** — in the Anthropic demo the `issue_refund` span is marked
  **ERROR** (level-based failure detection); in all three, the conversation shows the agent
  recovering and escalating. This is the trace you'd promote into a regression case.
- **Conversations** — the four turns grouped into one thread per run
  (`langgraph-support-demo-…`, `openai-agents-support-demo-…`, `anthropic-support-demo-…` —
  each run mints a fresh thread), with the rolling summary and per-turn verdicts.
- **Conversation → Agents panel** — the *declared* catalog (`tracely.trace(agents=…)`):
  system prompts, models, tool schemas, guardrails and skills, each tool annotated with how
  often it actually fired. Guardrails that pass emit no span — declaring them is how they
  stay visible.
- **Conversation → State drawer** (LangGraph demo) — node return values are captured as
  state deltas, so you can replay how the graph state evolved step by step.
- **Evaluators** — add an LLM-judge evaluator (e.g. "did the agent resolve the request or
  escalate correctly?") and it grades these traces on ingest; turn 4 makes a nice
  adversarial test case.

From there the rest of Tracely's loop applies to these demos as-is: failures cluster, a
cluster becomes a regression case, and `tracely gate` / `tracely simulate` turn it into a PR
check — see the [Tracely docs](https://github.com/Jwuthri/Tracely).

## Notes

- Models: the OpenAI demos use the Agents SDK's default cost-efficient model (LangGraph pins
  the same one explicitly); the Anthropic demo uses `claude-opus-5`. A full run of all three
  demos is ~30 LLM calls on small prompts.
- Everything else (orders, inventory, refunds) is deterministic in-memory fake data — no
  external services, safe to run repeatedly.
