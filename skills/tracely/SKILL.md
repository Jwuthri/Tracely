---
name: tracely
description: Instrument AI agents with Tracely and turn their production traces into CI gates. Use when the user mentions Tracely, tracely-ai, tracely_sdk, the `tracely` CLI, or asks to trace/observe an AI agent, add LLM evaluators or LLM-as-a-judge columns, debug why a trace or conversation isn't showing up, wire agent regression tests into a PR check, run scenario or red-team suites against an agent endpoint, or replay recorded agent failures in CI. Covers both zero-span-code automatic instrumentation and the manual span API.
license: MIT
---

# Tracely

Trace-native CI/CD for AI agents. One loop:

```
production trace → failure detection → regression test → CI gate
```

The trace is the source of truth. Evaluators, failure clusters, regression cases, gates and trends
are all **derived from it** — there are no hand-authored datasets. Docs: <https://doc.tracely-studio.xyz>.

## Pick the path first

Do not start writing spans. Ask what the code already looks like, then pick:

| The user's code | Path | Effort |
|---|---|---|
| Calls OpenAI / Anthropic / Gemini / Mistral / Bedrock / Groq SDKs | **Automatic** — `init(instrument="auto")` | 1 line |
| Uses LangChain / LangGraph / LlamaIndex / CrewAI / LiteLLM | **Automatic** + that extra | 1 line |
| Uses OpenAI Agents SDK / Claude Agent SDK / Google ADK | **Automatic**, named explicitly | 1 line |
| Has business logic worth seeing (routers, tools, retrievers) | Automatic **+ `@observe`** | 1 decorator each |
| Needs spans the auto path can't produce (custom retrievers, guardrails, handoffs, multimodal I/O, hand-rolled providers) | **Manual context managers** | `references/manual.md` |
| Is TypeScript / Go / Ruby / anything not Python | **Emit OTLP directly** — no SDK | `references/automatic.md` § other languages |
| Already emits OpenTelemetry / OpenInference / OpenLLMetry | Point the existing exporter at Tracely, add 2 attributes | `references/automatic.md` § other languages |

**Default to automatic.** Manual spans are the escape hatch, not the starting point, and the two
compose — manual spans nest inside auto-instrumented traces in the same tree.

## Connect

```python
import tracely_sdk as tracely   # pip install "tracely-ai[openai]"  ([anthropic] [langchain] [all])

tracely.init(
    endpoint="http://localhost:8000",   # hosted: https://api.tracely-studio.xyz
    api_key="tracely_dev_key",          # an ingest key — Settings → API keys. The key IS the workspace.
    service_name="support-agent",
    env="prod",                         # prod | staging | ci | dev — the gating axis
    instrument="auto",
)
```

Python ≥ 3.10. Import name is `tracely_sdk`; the CLI is `tracely`. `init()` is idempotent — call it
once at startup. Prefer `os.environ` for `endpoint`/`api_key` in real code; never inline a key.

## The 90% path

```python
with tracely.trace(agent="support-agent", conversation="conv-1", user="u_42"):
    client.chat.completions.create(model="gpt-4o", messages=[...])   # traced, no span code
```

`trace()` opens no span — it stamps run context (`agent`, `conversation`, `turn`, `user`, `env`,
arbitrary metadata) onto **every** span inside it, including the ones the instrumentor created.
It also works as a decorator on sync or async functions.

## Five rules that decide whether Tracely actually works

Getting these wrong doesn't error — it silently produces a useless workspace. Check them in every
review of someone's instrumentation.

1. **`conversation=` is what makes a conversation.** Each turn is its own trace; passing the same
   conversation id to every turn is the only thing that threads them. Without it, a 12-turn support
   thread is 12 unrelated rows, and every conversation-level evaluator has nothing to grade.
2. **`env` is the gating axis.** `prod` failures become regression cases; `ci` traces are what the
   gate grades. Tagging CI runs as `prod` poisons the case pool with test data.
3. **Errors are the failure signal.** A failed tool must be marked — `tracely.error(span, msg)`, an
   exception inside `@observe`, or an OTel `ERROR` status. Detection, clustering and the gate all key
   off it. A tool that returns `{"error": "..."}` as a *successful* span is invisible.
4. **`flush()` before the process exits.** Scripts, Lambdas, CLI runs and tests lose their last
   spans otherwise. Long-lived servers don't need it.
5. **If Tracely calls your agent, honour the `traceparent` header.** Scenarios and `simulate` mint
   the trace id and send it. Ignore it and the gate sees only text in / text out — blind to your
   tool calls, so tool expectations report `SKIP` instead of grading. See `references/ci-gate.md`.

Two more that bite on specific stacks:

- Streaming OpenAI calls need `stream_options={"include_usage": True}` or token counts (and
  therefore cost) are lost.
- LangChain + a provider instrumentor double-traces. Under `"auto"` LangChain wins and the provider
  instrumentors are skipped; pass an explicit list only if you also make direct provider calls.

## Your own spans — `@observe`

The cheapest way to see business logic. Args → input, return → output, exceptions → `level=ERROR`,
auto-nested via OTel context with no parent wiring.

```python
@tracely.observe(as_type="tool")
def get_weather(city: str) -> dict:
    return {"city": city, "tempF": 64}
```

`as_type` ∈ `agent` · `delegate` · `generation` · `tool` · `skill` · `chain` · `retriever` ·
`thinking` · `embedding` · `guardrail` · `span`. Decorating tools also makes them **hermetically
replayable** in CI for free.

## Manual spans

When the auto path can't express it. Every helper is a context manager; nesting builds the tree.

```python
with tracely.agent("support-agent", version="v4", conversation="conv-1", turn=0) as a:
    tracely.set_io(a, input=user_msg, output=answer)
    with tracely.tool("get_order", agent="support-agent") as t:
        try:
            tracely.set_io(t, input={"order_id": oid}, output=get_order(oid))
        except Exception as e:
            tracely.error(t, str(e))
```

Two types are worth naming even on an otherwise-automatic agent, because they're the shape a
multi-agent system fails in:

- `skill(name, version=…)` → **SKILL**, a named capability the agent chose to run (a refund flow, an
  escalation playbook, a loaded agent-skill file). Makes "which skill did this?" a filter and a
  failure cluster instead of a tree shape you have to infer.
- `delegate(to, agent=…, task=…)` → **DELEGATE**, the handover itself. Open the callee's `agent(...)`
  inside it and a judge can grade *the routing decision* separately from *the work*.

Full cookbook — every span type, `set_io` / `set_usage` / `set_metadata` / `set_state` /
`set_agents`, RAG pipelines, multi-agent handoffs, multimodal content, structured I/O rendering:
**`references/manual.md`**.

## Evaluators are columns

An evaluator is a column on the trace table, graded automatically as traces land. Two kinds:
`structural` (deterministic, no model, no cost) and `llm_judge` (a rubric prompt).

**A trace fails iff a non-advisory evaluator scored it FAIL.** Mark subjective quality judges
`advisory: true` so they show their verdict without flipping the roll-up.

Reach for structural checks before a judge — `run_outcome`, `tool_success`, `tool_consistency`,
`latency`, `required_tools` cost nothing and never flake. Levels, sequential grading, `@VARIABLE`
advanced templates, targeting and sampling: **`references/evaluators.md`**.

## Gate the PR

Three ways, by what CI can reach:

| Situation | Command | Needs |
|---|---|---|
| Agent is a deployed HTTP endpoint (any language) | `tracely simulate --all` | Endpoint registered + a scenario |
| CI already runs the agent and emits `env=ci` traces | `tracely gate <agent>` | Nothing extra |
| Want deterministic, offline, $0 replay of real failures | `tracely replay <agent> --entrypoint mod:fn` | Python agent + `@observe` tools or the `call_tool`/`call_llm` seam |

All exit `0` PASS / `1` FAIL / `2` never-got-an-answer, and post a GitHub commit status + PR comment.
A composite action ships at `.github/actions/tracely-gate/`. Details, scenario authoring, red-team
runs and hermetic replay: **`references/ci-gate.md`**.

## Drive it from the editor (MCP)

Every backend serves MCP at `/mcp` — read traces, inspect clusters, create evaluators, no glue code.

```bash
claude mcp add --transport http tracely https://api.tracely-studio.xyz/mcp \
  --header "Authorization: Bearer $TRACELY_KEY"
```

Then ask: *"look at the last 20 traces, find what's failing, and add an evaluation column that
catches it."* The key scopes every call to its workspace. Nothing deletes; there is no tool for
**sending** traces — that's the SDK's job.

## Verify before claiming it works

1. Run the agent, then `tracely.flush()`.
2. Open the UI → **Traces**. The run appears within a few seconds (evaluation is debounced ~4s).
3. Check the tree is a tree, not a flat list — if every span is a root, `trace()` isn't wrapping the
   call or the framework escaped the context.
4. Check the conversation groups its turns.
5. Check a deliberately-broken run shows red.

No trace at all, spans not nesting, conversations not grouping, evaluators not running, gate
suspiciously green: **`references/troubleshooting.md`** — symptom → cause → fix.

## References

| File | Read it when |
|---|---|
| `references/automatic.md` | Zero-span-code setup: extras, `instrument=`, `trace()`, `@observe`, drop-ins, LangChain/LangGraph/LiteLLM/CrewAI, agent SDKs, redaction, threads, **and non-Python / raw-OTLP integration**. |
| `references/manual.md` | The full manual span API and how to model a real agent with it. |
| `references/evaluators.md` | Designing evaluation columns, judge prompts, `@VARIABLE` templates, verdict policy, cost control. |
| `references/ci-gate.md` | Scenarios, adversarial suites, hermetic replay, the CLI, GitHub Actions. |
| `references/troubleshooting.md` | Something isn't showing up or the gate is lying. |

Self-hosting (`docker compose up -d --build --wait` → UI :3001, API :8000, dev key
`tracely_dev_key`) and Railway one-click: <https://doc.tracely-studio.xyz/self-hosting>.
