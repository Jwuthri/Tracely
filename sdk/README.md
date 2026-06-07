# `sdk/` — `tracely-sdk` (instrument agents + the CI gate CLI)

Two things in one small package:

1. an **instrumentation SDK** — `tracely.init()` activates the OpenAI/Anthropic/LangChain/LiteLLM auto-instrumentors so your existing code is traced with **zero span code** (the default path); a custom `SpanProcessor` stamps the active `tracely.trace()` run context onto every span — including the zero-touch provider spans. Manual context managers remain the escape hatch. Everything emits standard `gen_ai.*` / OpenInference attributes **plus** Tracely's first-class `tracely.*` hints, so the backend can populate its agent-semantic columns; and
2. the **`tracely` CLI** — `tracely gate` and `tracely replay`, which run an agent's promoted regression suite in CI and gate the PR (exit 0/1 + GitHub status/comment).

The core depends only on `opentelemetry-sdk` + the OTLP HTTP exporter (Python ≥ 3.10); a provider extra adds that provider's auto-instrumentor.

```bash
pip install "./sdk[openai]"        # provider extras: [openai] [anthropic] [langchain] [litellm] [all]
# or: uv pip install -e sdk        # core only (manual API + CLI)
# CLI becomes available as `tracely` (entry point tracely_sdk.cli:main)
```

> Already using OpenTelemetry / OpenInference / LangGraph instrumentation? You don't need the instrumentation half — point your existing OTLP exporter at `POST {endpoint}/v1/traces` with `Authorization: Bearer <ingest-key>` and set the `tracely.*` attributes below. This SDK is just the ergonomic path. The **CLI**, however, is how you wire Tracely into CI.

---

## 1. Instrument an agent

### Automatic (the default — zero span code)

`init()` activates the auto-instrumentors; `trace()` attaches the run context; `@observe` adds
function-level spans. No manual span code.

```python
import tracely_sdk as tracely
from openai import OpenAI

tracely.init(endpoint="http://localhost:8000", api_key="tracely_dev_key",
             service_name="support-agent", env="prod", instrument="auto")

with tracely.trace(agent="support-agent", conversation="conv-1", user="u_42"):
    OpenAI().chat.completions.create(model="gpt-4o", messages=[...])   # GENERATION span, captured

@tracely.observe(as_type="agent")            # args→input, return→output, auto-nested
def plan(goal): ...
```

`instrument` is `"auto"` (every importable provider SDK), an explicit list (`["openai",
"anthropic"]`), or `False`. The `tracely.trace()` hints flow onto **every** span inside it — including
the provider spans the instrumentor creates — via a custom `SpanProcessor`. Streaming token usage
needs `stream_options={"include_usage": True}`.

**Also covered:** LangChain/LangGraph (`[langchain]` — graphs nest, node names become steps), LiteLLM
(`instrument=["litellm"]` — 100+ providers via one callback), and a non-patching drop-in
(`from tracely_sdk.openai import OpenAI` / `wrap_openai`). Under `"auto"`, when the LangChain
instrumentor is present it owns LLM spans and the provider instrumentors are skipped to avoid
duplicate spans (override with an explicit list). Full guide: the docs [Automatic instrumentation](../docs/pages/automatic.mdx) page.

### Manual / custom spans (the escape hatch)

For anything the auto path doesn't cover. Each `with` block is a span; nesting builds the tree.

```python
import tracely_sdk as tracely

tracely.init(endpoint="http://localhost:8000", api_key="tracely_dev_key",
             service_name="support-agent", env="prod")

with tracely.agent("support-agent", version="v3", conversation="conv-1", turn=0) as a:  # AGENT span = run root
    tracely.set_io(a, input=user_msg, output=answer)                 # what the agent received / returned
    with tracely.thinking(agent="support-agent") as th:             # THINKING span (reasoning)
        tracely.set_io(th, output=reasoning); tracely.set_usage(th, thinking_tokens=120)
    with tracely.llm("gpt-4o", agent="support-agent") as g:          # GENERATION span
        tracely.set_io(g, input=messages, output=completion)
        tracely.set_usage(g, input_tokens=812, output_tokens=96)
    with tracely.tool("get_order", agent="support-agent") as t:      # TOOL span
        try:
            result = get_order(order_id)
            tracely.set_io(t, input={"order_id": order_id}, output=result)
        except Exception as e:
            tracely.error(t, str(e))                                 # level=ERROR → the failure signal

tracely.flush()   # force-flush the exporter (call before the process exits)
```

### Span context managers — one per observation type
| Call | Span type | Sets |
|---|---|---|
| `agent(slug, *, version, run_id, role, conversation, turn, user, trace_name, handoff_from, edge="delegate")` | `AGENT` (run root) | `tracely.agent.id`/`.version`/`.run_id`/`.role`, `tracely.conversation.id` + `session.id`, `tracely.turn.index`, `tracely.env`; `user`→`tracely.user.id`, `trace_name`→`tracely.trace.name`; `handoff_from`→ a handoff edge (`caller`→this agent, `edge.type`). |
| `llm(model, *, agent, temperature, top_p, max_tokens, frequency_penalty, presence_penalty, seed, tool_calls, metadata)` | `GENERATION` | `gen_ai.request.model` + the sampling params as `gen_ai.request.*`; `tool_calls`→`tracely.tool_calls` (tools the model **requested**); `metadata`→`tracely.metadata.*`. |
| `tool(name, *, agent)` | `TOOL` | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`. |
| `thinking(name="thinking", *, agent, model)` | `THINKING` | reasoning emitted as its own span; optional `model`. |
| `retriever(name="retrieve", *, agent)` | `RETRIEVER` | a retrieval step — query in `set_io(input=)`, hits in `set_io(output=)`. |
| `embedding(model, *, agent)` | `EMBEDDING` | `gen_ai.request.model`; record tokens with `set_usage(input_tokens=)`. |
| `guardrail(name="guardrail", *, agent)` | `GUARDRAIL` | a safety/policy check — verdict in `set_io(output={"action": "allow"\|"block"})`. |
| `chain(name, *, agent)` | `CHAIN` | a grouping span (e.g. a RAG pipeline) — nest other spans inside it. |
| `turn(turn_id, *, index)` / `step(name, *, step_id)` | marker / generic | `tracely.turn.*` / `tracely.step.*`. |

### Annotating spans
- `set_io(span, *, input=None, output=None)` → `tracely.input` / `tracely.output` (objects are JSON-encoded; message content is a `{role, content:[blocks]}` object or a content-block list).
- `set_usage(span, *, input_tokens=None, output_tokens=None, thinking_tokens=None)` → `gen_ai.usage.input_tokens` / `output_tokens` / `reasoning_tokens`.
- `set_metadata(span, **kv)` → `tracely.metadata.<key>` — arbitrary tags (e.g. prompt version, tenant), surfaced in the span's Metadata and searchable.
- `error(span, message="")` → marks the span `StatusCode.ERROR` (→ `level=ERROR` in Tracely) — this is *the* failure-detection signal.
- `flush()` → force-flush the OTLP exporter.

### What Tracely reads
Standard `gen_ai.*` / OpenInference attributes, plus first-class hints that become **indexed columns** on the span row: `tracely.agent.id`/`.version`/`.role`, `tracely.user.id`, `tracely.trace.name`, `tracely.conversation.id`, `tracely.turn.id`/`.index`, `tracely.step.id`/`.name`, `tracely.observation.type`, `tracely.tool_calls`, `tracely.handoff.*` + `tracely.edge.type`, the `gen_ai.request.*` sampling params, and `tracely.env` (`prod|staging|ci|dev` — the gating axis). Agent slug + version are auto-registered into the Postgres registry on ingest.

---

## 2. Hermetic replay (`call_tool` / `call_llm` / `fixtures`)

These let the **same agent code** run live in production and deterministically offline in CI. Wrap each external call:

```python
def run(user_input: str):
    with tracely.agent("support-agent"):
        # In prod: calls the real fn and records the output. In replay: serves the recorded output.
        order = tracely.call_tool("get_order", lambda: get_order(order_id), args={"order_id": order_id})
        answer = tracely.call_llm("gpt-4o", lambda: chat(messages), input=messages, usage=(812, 96))
        return answer
```

- **Production (`--live` or no fixtures active):** `call_tool`/`call_llm` invoke your `fn`, record the output (and any error) on the span, and return it.
- **CI replay:** `tracely replay` activates the case's recorded **fixture bundle** via `with tracely.fixtures(bundle): ...`; `call_tool`/`call_llm` then **serve the recorded outputs in order** (or by `args` match) and never call your `fn`. A call that errored in production is reproduced on the span **and raised as `tracely.ToolError`**, so the agent's own `try/except` runs exactly as it would live — and the gate sees the same failure condition.

This is what makes replay deterministic, offline, and free (no API keys, no cost). See [regression-testing design](../design/part2-tracely/05-regression-testing.md).

---

## 3. The CI gate CLI

```bash
tracely gate   <agent> [--env ci] [--api …] [--key …] [--pr N] [--sha …] [--github]
tracely replay <agent> (--entrypoint module:func | --cmd "…") [--live] [--github]
```

- **`tracely gate <agent>`** — gate a PR against **pre-emitted** `env=ci` traces (your CI already ran the agent and emitted traces); cases are matched to candidates by `input_digest`.
- **`tracely replay <agent>`** — re-run the agent **on each promoted case's recorded input** (fetched from `GET /api/gate/suite`), then gate. `--entrypoint module:func` calls a Python function per case; `--cmd "…"` runs a shell command per case (gets `TRACELY_INPUT`) that emits its own trace. Hermetic by default; `--live` makes real tool/LLM calls.

Both **exit 0 (PASS) / 1 (FAIL)** and, inside GitHub Actions (or with `--github`), post a **commit status + PR comment** with per-case results and soft warnings (latency/token deltas vs the last green gate). `--dry-run` prints the GitHub calls instead of sending; `--no-github` never touches GitHub. Config via flags or env (`TRACELY_API`, `TRACELY_KEY`, `TRACELY_AGENT`, `TRACELY_GATE_ENV`, `TRACELY_WEB_URL`, `GITHUB_TOKEN`). A reusable composite action lives at `.github/actions/tracely-gate/`.

---

## Examples (`sdk/examples/` + `sdk/example.py`)

[`examples/README.md`](examples/README.md) is the full index — **one runnable file per way of
tracing**, all the same fake-DB tool-calling support agent: each frontier provider (OpenAI, Anthropic,
Gemini, Mistral, Bedrock) + OpenRouter, each harness (LangChain `create_agent`, LangGraph, LiteLLM,
LlamaIndex, CrewAI), each first-party agent SDK (OpenAI Agents, Claude Agent SDK, Google ADK), and
each approach (`@observe`+`trace`, the `wrap_openai`/`wrap_anthropic` drop-ins, manual spans). Highlights:

| File | Shows |
|---|---|
| `../example.py` | the minimal demo trace (agent → llm → failing tool). `make sdk-example`. |
| `examples/auto_openai.py` · `auto_anthropic.py` · `auto_gemini.py` · … | **automatic** provider tracing — zero span code (one file per frontier provider + OpenRouter). |
| `examples/auto_langchain.py` (`create_agent`) · `auto_langgraph.py` · `auto_litellm.py` · … | **automatic** harness tracing (one file per framework, current APIs). |
| `examples/auto_openai_agents.py` · `auto_claude_agent.py` · `auto_google_adk.py` | **automatic** first-party agent-SDK tracing (OpenAI Agents / Claude Agent SDK / Google ADK). |
| `examples/auto_agent.py` | **automatic** `@observe` + `trace()` agent → thinking/gen/tool tree. `make auto-agent`. |
| `examples/dropin_openai.py` · `dropin_anthropic.py` | non-patching `wrap_openai` / `wrap_anthropic` drop-ins. |
| `examples/manual_spans.py` | the manual escape-hatch API as a full agent (no provider/key needed). |
| `examples/weather_agent.py` / `weather_agent_cli.py` | a real agent wired with `call_tool`/`call_llm` for `tracely replay --entrypoint` / `--cmd`. |
| `examples/seed_conversations.py` | rich demo data using **every** SDK helper — single/multi-turn, multi-agent + handoffs, RAG (guardrail→embed→retrieve→chain), thinking, multimodal, structured output, multi-model. `make seed-demo`. |
| `examples/seed_regression.py` | promote a failing trace → run red→green CI gates (fills Cases + Gates). `make seed-regression`. |
| `examples/seed_multicall.py` / `seed_handler.py` | repeated-call + handler examples for fixture replay. |

---

## Key decisions (and why)

1. **Thin wrapper, not a framework.** It only sets attributes on OTel spans — anyone already on OpenTelemetry/OpenInference can skip it and just emit the `tracely.*` hints. No lock-in.
2. **First-class `tracely.*` hints.** Agent/conversation/turn/step/env are emitted as semantic attributes so they become indexed columns server-side — the basis for agent-level evals and PR gating.
3. **`THINKING` is a span type, not a field.** Reasoning is its own observation, so it renders distinctly and carries its own token usage.
4. **Record-replay in the SDK.** `call_tool`/`call_llm` are the seam that makes "the recorded run is the test" real: the same code path records in prod and replays in CI, reproducing recorded errors via `ToolError` so error-handling behaviour is gated faithfully.
5. **The CLI is the CI contract.** `gate`/`replay` exit 0/1 and speak GitHub — so wiring Tracely into a pipeline is one step, with the hard gate being fail-to-pass and everything else advisory.
