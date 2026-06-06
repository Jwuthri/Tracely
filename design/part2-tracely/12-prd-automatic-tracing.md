# PRD — Automatic tracing: make instrumentation the default

> Make the SDK capture traces **automatically** (like Langfuse / LangSmith / Phoenix), so the common
> path is zero manual code, while manual spans remain an escape hatch. Backed by the deep-research
> findings (24/25 claims verified 3-0 against primary sources — see [References](#references)).
>
> Sibling PRD: [11-prd-next-steps.md](11-prd-next-steps.md) (evaluators / Detect loop). Data model:
> [03-agent-and-trace-data-model.md](03-agent-and-trace-data-model.md). SDK: [../../sdk/README.md](../../sdk/README.md).
>
> _Status: draft · 2026-06-06_
>
> **Implementation status (2026-06-06):** P0–P3 built. SDK `init(instrument=…)` + the
> `TracelyContextSpanProcessor`, `tracely.trace()`, `@observe`, `run_in_thread`, instrumentor extras,
> and the `tracely_sdk.openai` drop-in (`wrap_openai`) are implemented in [../../sdk](../../sdk);
> backend ingestion of real OpenInference/OpenLLMetry/structured-`gen_ai.*` output + convention-version
> provenance is in [`backend/tracely/otel/mapping.py`](../../backend/tracely/otel/mapping.py).
> Validated end-to-end against OpenAI, LangChain/LangGraph, and LiteLLM. **R16 (TS/JS) is a plan only**
> — [13-ts-js-parity-plan.md](13-ts-js-parity-plan.md).

---

## 1. Where we are (the problem)

Today's `tracely-sdk` is **manual-only**. To trace a single LLM call you write:

```python
with tracely.agent("planner") as a:
    with tracely.llm("gpt-4o", agent="planner") as g:
        tracely.set_io(g, input=messages, output=completion)
        tracely.set_usage(g, input_tokens=812, output_tokens=96)
```

That's the *escape hatch* layer exposed as the *only* layer. Every competitor makes this automatic:
you call your normal OpenAI/Anthropic client and the span — model, tokens, latency, cost, messages,
tool calls, errors — appears with **no span code**. Manual instrumentation is the exception, not the rule.

**What we already have (keep):** the backend ingests OTLP at `POST /v1/traces` and maps `gen_ai.*`,
OpenInference, and first-class `tracely.*` attributes into indexed ClickHouse columns; cost is derived
server-/client-side from token counts + a model price table. The ingestion path stays — this PRD is
about **what produces the spans**.

## 2. What the market does (research-backed)

Three composable layers, all emitting standard OTLP and nesting into one trace via OTel context:

1. **Zero-touch provider capture**, two flavors:
   - **OTel monkey-patch instrumentors** — OpenLLMetry (Traceloop), OpenInference (Arize). Modular,
     per-provider, activated with `OpenAIInstrumentor().instrument()`; OpenLLMetry's conventions are
     **upstreamed into OpenTelemetry as `gen_ai.*`**.
   - **Drop-in client wrappers** — `from langfuse.openai import openai`, LangSmith `wrap_openai()`.
   - Both auto-capture model · messages · token usage · latency/TTFT · tool calls · errors · streaming · async.
2. **`@observe` / `@traceable` / `@traced` decorator** — wraps any function; args→input, return→output,
   latency, exceptions; sync+async; **auto-nests via contextvars/OTel context (no manual parent wiring)**;
   `as_type=` selects observation type.
3. **LiteLLM fan-out** — `litellm.callbacks=["otel"]` traces 100+ providers via the unified call path.

Plus a **trace-attribute propagation** context manager (Langfuse `propagate_attributes()`) that pushes
trace-level tags (user/session) onto every child span — the exact pattern for Tracely's `tracely.*` hints.

## 3. Goal

A developer adds **one line** — `tracely.init()` — and their existing OpenAI / Anthropic / LangChain /
LiteLLM code is fully traced into Tracely, with **model, tokens (incl. streaming), latency/TTFT, cost,
messages, tool calls, and errors** captured automatically. Multi-step agents nest correctly. The
`tracely.*` hints (agent, conversation, turn, env, user) attach with no per-call code. Manual spans
still work for anything custom.

## 4. Non-goals (this PRD)

- Rebuilding evaluators / clustering (that's [11-prd-next-steps.md](11-prd-next-steps.md)).
- A new backend store or changes to the OTLP ingestion transport.
- Removing the manual SDK API (it is **retained** as the escape hatch).
- A full TS/JS SDK now (parity is scoped in P3, not built).

## 5. Principles (canonical decisions for this work)

- **D1 — Reuse the OTel ecosystem.** Adopt OpenLLMetry / OpenInference instrumentors rather than
  reinventing per-provider monkey-patching. Build first-party wrappers only where reuse is insufficient.
- **D2 — Auto by default, manual as escape hatch, always composable.** All layers nest into one trace.
- **D3 — Speak standard conventions, keep `tracely.*` first-class.** Ingest `gen_ai.*` and OpenInference
  `llm.*` **independently** (they are separate, non-overlapping schemas); enrich with `tracely.*` hints.
- **D4 — Convention-version-aware ingestion.** `gen_ai.*` is experimental and drifting; handle both the
  legacy flat (`gen_ai.prompt`/`completion`) and new structured (`gen_ai.input.messages`/`output.messages`)
  shapes, and OpenInference's flattened `llm.input_messages.<i>.*`.

## 6. Architecture

```
 ┌─────────────────────────── your app ───────────────────────────┐
 │  tracely.init(env="prod")                                       │
 │                                                                 │
 │  L1  auto-instrumentors  ── OpenAI · Anthropic · LangChain ·    │  ← default, zero span code
 │      (OpenLLMetry / OpenInference)   LiteLLM(["otel"])          │
 │  L2  @observe(as_type=…)  ── arbitrary fns / agents / tools     │  ← one decorator
 │  L3  tracely.trace(agent=, conversation=, turn=, user=)         │  ← run context (tags flow down)
 │  L4  with tracely.span(...) / agent()/llm()/tool()  (manual)    │  ← escape hatch (today's API)
 └───────────────────────────────┬─────────────────────────────────┘
                                  │  every span passes through →
                  TracelyContextSpanProcessor   (stamps active L3 tracely.* hints on_start)
                                  │  OTLP exporter
                                  ▼
                   POST /v1/traces  →  S3 → worker → ClickHouse   (unchanged)
```

**The linchpin — `TracelyContextSpanProcessor`.** Auto-instrumentor spans are created by *their* code,
not ours, so they can't know about `agent.id` / `conversation`. A custom OTel `SpanProcessor.on_start`
reads the active `tracely.trace()` context (a contextvar) and stamps `tracely.agent.id`,
`tracely.conversation.id`, `tracely.turn.index`, `tracely.env`, `tracely.user.id` onto **every** span as
it starts. That's how zero-touch provider spans inherit Tracely's first-class hints without the
instrumentor knowing Tracely exists.

## 7. Requirements

### P0 — `init()` auto-captures OpenAI + Anthropic (the 80%)

- **R1 — One-call setup.** `tracely.init(env=..., instrument="auto" | [list] | False)` configures the
  OTel TracerProvider + OTLP exporter to `POST /v1/traces` (as today) **and** activates the matching
  instrumentors for whatever provider SDKs are importable (`"auto"` = detect installed). Idempotent;
  safe to call once at startup.
- **R2 — Capture set (per LLM call, automatic):** model name · input messages · output message(s) ·
  token usage (input/output/total, +reasoning when present) · latency · time-to-first-token (streaming) ·
  tool/function calls · errors (status + message) · for sync **and** async **and** streaming.
- **R3 — Streaming usage.** Ensure token usage is captured on streamed responses (OpenAI omits it unless
  `stream_options={"include_usage": True}`; usage arrives in the final chunk). The instrumentation must
  set/handle this so token + cost data isn't lost on streams.
- **R4 — `TracelyContextSpanProcessor`** (§6) stamps active `tracely.*` run context onto auto spans.
- **R5 — Backend ingest of real instrumentor output** (`mapping.py`, see §8): handle OpenInference
  flattened `llm.input_messages.<i>.message.*` / `llm.output_messages.<i>.*` and OTel structured
  `gen_ai.input.messages` / `gen_ai.output.messages`, in addition to today's flat keys; map model,
  usage, params, observation type. Map `gen_ai.*` and `llm.*` **independently**.
- **R6 — Cost** continues to derive from model + tokens server/client-side — verify the model name is
  always captured so the price lookup hits.
- **R7 — Double-instrumentation guard.** Never let a call be traced twice (e.g. provider instrumentor +
  LiteLLM `["otel"]`). `init()` activates one path per provider and documents
  `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS`.

**P0 acceptance:** `tracely.init()` then `OpenAI().chat.completions.create(model="gpt-4o", …)` (sync,
async, and streamed) produces **one** `GENERATION` span in the Traces UI with correct model, input/output
messages, token counts, latency, derived cost, tool calls, and (on error) `level=ERROR` — **with zero
span code**. Anthropic equivalent works the same.

### P1 — `@observe` decorator + `tracely.trace()` run context

- **R8 — `@observe(name=None, as_type="span", capture_input=True, capture_output=True)`** wraps any
  sync/async function; captures args→input, return→output, latency, exceptions; nests via OTel context
  with no manual parent wiring. `as_type` ∈ {span, generation, agent, tool, chain, retriever, embedding,
  guardrail, …} → `tracely.observation.type`.
- **R9 — `tracely.trace(agent=, conversation=, turn=, user=, trace_name=, env=, **metadata)`** context
  manager / decorator that sets the run-level `tracely.*` context consumed by R4's processor, so all
  child spans (auto or manual) inherit it. This replaces today's per-span `agent=`/`conversation=` plumbing.
- **R10 — Threads.** Provide a context-copying helper (or document the OTel threading instrumentor) since
  auto-nesting is in-process only.

**P1 acceptance:** an `@observe(as_type="agent")`-decorated function that internally calls OpenAI twice
and a `@observe`-decorated tool yields a 4-span tree (agent → 2 generations + tool) correctly nested,
all carrying the `agent`/`conversation`/`env` from an enclosing `tracely.trace(...)`.

### P2 — LangChain/LangGraph, LiteLLM, optional drop-in wrapper

- **R11 — LangChain/LangGraph** auto-traced (instrumentor or callback handler auto-registered by `init`).
- **R12 — LiteLLM** path: `init(instrument=["litellm"])` wires `litellm.callbacks=["otel"]` so 100+
  providers fan out through one integration; with the double-instrument guard (R7).
- **R13 — Optional `from tracely.openai import openai`** drop-in wrapper for environments where
  monkey-patching is undesirable (non-patching alternative to R1).

**P2 acceptance:** a LangGraph graph and a LiteLLM `completion()` each trace end-to-end with no manual
spans; no duplicate spans when both an instrumentor and LiteLLM are present.

### P3 — Hardening & parity

- **R14 — Convention versioning** in ingestion (track `gen_ai.*` spec version; tolerate flat + structured).
- **R15 — Observation-type derivation is defensive.** Derive from `tracely.observation.type` →
  `gen_ai.operation.name` → `openinference.span.kind`, but **do not hard-code** an exact OpenInference
  span-kind enum (the "ten fixed values" claim failed verification — treat unknowns as `SPAN`).
- **R16 — TS/JS parity plan** (not built): `wrapOpenAI`, Vercel AI SDK integration, OpenTelemetry-JS —
  every vendor ships it; document the intended JS surface. → [13-ts-js-parity-plan.md](13-ts-js-parity-plan.md).

## 8. Backend mapping spec (`backend/tracely/otel/mapping.py`)

Map each namespace independently into the existing columns. ✅ = already handled, ➕ = to add.

| Tracely column | OTel GenAI (`gen_ai.*`) | OpenInference (`llm.*` / `openinference.*`) |
|---|---|---|
| `model_id` | ✅ `gen_ai.response.model` / `request.model` | ✅ `llm.model_name` |
| `model_parameters` | ✅ `gen_ai.request.{temperature,top_p,max_tokens,frequency_penalty,presence_penalty,seed}` | ➕ `llm.invocation_parameters` (JSON) |
| `usage_details` | ✅ `gen_ai.usage.{input,output,total}_tokens` (+ ➕ reasoning/cache tokens) | ✅ `llm.token_count.{prompt,completion,total}` |
| `input` | ➕ `gen_ai.input.messages` (structured) · legacy `gen_ai.prompt` | ➕ `llm.input_messages.<i>.message.{role,content}` (flattened) · `input.value` ✅ |
| `output` | ➕ `gen_ai.output.messages` (structured) · legacy `gen_ai.completion` | ➕ `llm.output_messages.<i>.message.{role,content}` · `output.value` ✅ |
| `tool_call_names` | ➕ from `gen_ai.*`/output tool calls | ➕ `llm.output_messages.<i>.message.tool_calls.<j>.tool_call.function.name` |
| `type` (observation) | ✅ `gen_ai.operation.name` (chat→GENERATION, execute_tool→TOOL, embeddings→EMBEDDING) | ✅ `openinference.span.kind` (defensive, R15) |
| `completion_start_time` | ➕ TTFT if emitted | ➕ if emitted |
| agent/conv/turn/env/user | ✅ `tracely.*` (stamped by R4 processor) | ✅ `tracely.*` |

Helpers needed: a small normalizer that reassembles flattened `llm.*_messages.<i>.*` and structured
`gen_ai.*.messages` into Tracely's `{role, content:[blocks]}` shape used by the UI.

## 9. Build-vs-adopt decision

**Recommendation: adopt** (D1). Ship the instrumentors as **optional extras** —
`pip install "tracely-sdk[openai,anthropic,langchain]"` pulls the corresponding
`opentelemetry-instrumentation-*` (OpenLLMetry) / `openinference-instrumentation-*` packages, which
`init()` activates against Tracely's provider. Pin versions and track convention drift (D4). Build the
first-party `from tracely.openai import openai` wrapper only as the R13 non-patching fallback. Rationale:
minimal first-party code, maximal provider coverage, standards-based; the cost is inherited spec churn,
mitigated by R14.

## 10. Gotchas (verified caveats — must be designed for)

- `gen_ai.*` is **experimental & evolving** → R14 (version-aware; flat + structured messages).
- **Streaming usage** missing without `stream_options.include_usage` → R3.
- **Double-instrumentation** → R7.
- **In-process context only** (threads/processes/services need explicit propagation) → R10.
- **Two separate conventions** (`gen_ai.*` vs `llm.*`); dual-emission is partial/per-package → §8 maps each.
- **No fixed OpenInference span-kind enum** → R15.

## 11. Migration path

Fully incremental — **the current manual API is unchanged and keeps working** as L4:

1. Add `tracely.init()` → auto-capture turns on; existing manual spans still emit and compose.
2. Replace per-span `agent=`/`conversation=` with one enclosing `tracely.trace(...)` (R9) over time.
3. `@observe` adopted where teams want function-level spans.
4. Examples: keep `seed_conversations.py` as the manual-API showcase; add `examples/auto_openai.py`
   (zero-code path) and `examples/auto_agent.py` (`@observe` + `trace()`).
5. SDK docs site ([../../docs](../../docs)) gains an **"Automatic instrumentation"** section as the new
   front-and-center path; manual API demoted to "Advanced / custom spans."

## 12. Success metrics

- **Time-to-first-trace**: `pip install` → `init()` → one real LLM call visible in Tracely, **< 5 min, 1 LOC**.
- **Coverage**: OpenAI + Anthropic (P0), LangChain/LangGraph + LiteLLM (P2) trace with no manual spans.
- **Fidelity**: model, tokens (incl. streamed), cost, latency/TTFT, tool calls, errors all populated; **zero duplicate spans**.
- **No regression**: every existing manual-API trace + the seed still renders identically.

## 13. Open questions

- **Anthropic specifics** — validate the instrumentors capture native `tool_use`/`tool_result` blocks,
  prompt-cache tokens (`cache_creation`/`cache_read`), and streaming usage in `message_delta`.
- **Adopt vs vendor** the exact instrumentor packages (resolved as "adopt as extras" above, but the
  pin/version-tracking policy needs owning).
- **Exact message-normalization** reconciling OpenInference flat-indexed vs OTel structured vs legacy.
- **LangGraph node/edge** span shape + nesting (vs plain LangChain) — verify before P2.

## References

Deep-research report (this session): 24/25 claims verified 3-0, primary sources —
[OpenLLMetry](https://github.com/traceloop/openllmetry) ·
[OpenInference semconv](https://arize-ai.github.io/openinference/spec/semantic_conventions.html) ·
[Langfuse decorators](https://langfuse.com/docs/sdk/python/decorators) ·
[Langfuse OpenAI wrapper](https://langfuse.com/integrations/model-providers/openai-py) ·
[LangSmith wrap_openai](https://docs.langchain.com/langsmith/trace-openai) ·
[Braintrust @traced](https://www.braintrust.dev/docs/instrument/trace-application-logic) ·
[LiteLLM callbacks](https://docs.litellm.ai/docs/observability/callbacks) ·
[LiteLLM OTel](https://docs.litellm.ai/docs/observability/opentelemetry_integration).
