# TS/JS parity plan — automatic tracing for the JavaScript/TypeScript SDK

> The intended JS/TS surface that mirrors the Python automatic-tracing SDK (PRD
> [12-prd-automatic-tracing.md](12-prd-automatic-tracing.md), R16). **Not built** — this documents the
> design so the JS SDK lands consistent with Python. The backend ingestion path is unchanged: a JS
> SDK exports the same OTLP to `POST /v1/traces`, so most of this is client-side.
>
> _Status: plan · 2026-06-06_

---

## 1. Why parity is cheap here

The whole Python design rests on the OpenTelemetry ecosystem (decision D1), and **every vendor ships
the JS equivalent**:

- **OpenTelemetry-JS** — `@opentelemetry/sdk-trace-node`, `@opentelemetry/exporter-trace-otlp-http`,
  `registerInstrumentations(...)`. Same `SpanProcessor` extension point we used for the linchpin.
- **Auto-instrumentors** — OpenInference (`@arizeai/openinference-instrumentation-openai`,
  `-langchain`) and OpenLLMetry (`@traceloop/instrumentation-openai`, `-anthropic`, `-langchain`).
  Same two conventions (`gen_ai.*` / `llm.*`) the backend already maps.
- **Drop-in wrappers** — LangSmith `wrapOpenAI()`, Langfuse `observeOpenAI()` — the JS analog of our
  `wrap_openai` (R13).
- **Vercel AI SDK** — first-class OTel: `experimental_telemetry: { isEnabled: true }` emits spans for
  `generateText`/`streamText`/tool calls. This is the dominant JS-agent path and has no Python analog.

Because the backend already ingests `gen_ai.*` and OpenInference `llm.*` independently (D3) and is now
convention-version-aware (R14), a JS SDK needs **almost no new backend work** — except mapping the
Vercel AI SDK's `ai.*` attributes (see §5).

## 2. Intended public surface (`@tracely/sdk`)

Mirror the Python names so docs and mental model transfer 1:1.

```ts
import * as tracely from "@tracely/sdk";

// R1 — one-call setup: TracerProvider + OTLP exporter to /v1/traces + the context processor +
// activate importable instrumentors. instrument: "auto" | string[] | false.
tracely.init({
  endpoint: "http://localhost:8000",
  apiKey: "tracely_dev_key",
  serviceName: "weather-agent",
  env: "prod",
  instrument: "auto",
});

// R9 — run context. AsyncLocalStorage-based; stamps tracely.* onto every span inside.
await tracely.trace({ agent: "weather-agent", conversation: "conv-1", user: "u_7" }, async () => {
  await openai.chat.completions.create({ model: "gpt-4o", messages });   // captured, no span code
});

// R8 — function-level spans. Wraps sync/async fns: args→input, return→output, errors→ERROR.
const plan = tracely.observe(async (goal: string) => { ... }, { asType: "agent" });

// R13 — non-patching drop-in (instance-scoped, no global patch).
import { wrapOpenAI } from "@tracely/sdk/openai";
const client = wrapOpenAI(new OpenAI());
```

| Python | JS/TS | Notes |
|---|---|---|
| `tracely.init(instrument=…)` | `tracely.init({ instrument })` | `"auto"` detects installed instrumentor packages |
| `with tracely.trace(...)` | `tracely.trace(opts, fn)` | callback form (no `with`); also a decorator on methods |
| `@tracely.observe(...)` | `tracely.observe(fn, opts)` | higher-order fn (TS has no contextvar-free decorators for free fns) |
| `wrap_openai(client)` | `wrapOpenAI(client)` | instance-scoped, like LangSmith |
| `TracelyContextSpanProcessor` | same, AsyncLocalStorage-backed | the linchpin (§3) |
| `run_in_thread` | — | not needed; Node is single-event-loop (worker_threads caveat below) |

## 3. The linchpin in JS — `TracelyContextSpanProcessor`

Identical idea to Python (PRD §6, R4): a custom `SpanProcessor.onStart(span)` reads the active run
context and stamps `tracely.agent.id` / `conversation.id` / `turn.index` / `user.id` / `env` /
`metadata.*` onto every span — so zero-touch provider spans inherit Tracely's hints. The only
difference is the context store:

- **Python:** `contextvars.ContextVar`.
- **JS:** `AsyncLocalStorage` (the Node standard) — `tracely.trace(opts, fn)` runs `fn` inside
  `als.run(merge(parent, opts), fn)`. OpenTelemetry-JS already uses `AsyncLocalStorageContextManager`
  for span context, so async propagation is consistent.

## 4. Auto-instrumentation activation

`init({ instrument })` calls `registerInstrumentations({ tracerProvider, instrumentations: [...] })`
with whichever instrumentor packages resolve, mirroring the Python first-importable-wins logic and the
**LangChain de-dup guard** (R7): when the LangChain instrumentor is present under `"auto"`, skip the
provider instrumentors. Packages, by provider:

| Provider | OpenInference | OpenLLMetry |
|---|---|---|
| openai | `@arizeai/openinference-instrumentation-openai` | `@traceloop/instrumentation-openai` |
| anthropic | `@arizeai/openinference-instrumentation-anthropic` | `@traceloop/instrumentation-anthropic` |
| langchain | `@arizeai/openinference-instrumentation-langchain` | `@traceloop/instrumentation-langchain` |

Shipped as optional `peerDependencies` (the npm analog of Python extras, §9).

## 5. Vercel AI SDK — the JS-only path (needs a small backend addition)

The Vercel AI SDK is the most common JS agent framework and emits OTel spans natively:

```ts
import { generateText } from "ai";
await generateText({ model: openai("gpt-4o"), prompt, experimental_telemetry: { isEnabled: true } });
```

Its spans carry **`ai.*`** attributes (`ai.prompt`, `ai.response.text`, `ai.usage.promptTokens`,
`ai.usage.completionTokens`, `ai.toolCall.*`) **alongside** partial `gen_ai.*`. So:

- **Client:** `init()` just needs the run-context processor active; no instrumentor — the app sets
  `experimental_telemetry`. Tracely can offer a helper that flips it on by default.
- **Backend (the one new mapping):** add an `ai.*` family to `mapping.py` parallel to `gen_ai.*` /
  `llm.*` — `ai.usage.{promptTokens,completionTokens}` → usage, `ai.prompt`/`ai.response.text` → I/O,
  `ai.toolCall.*` → tool calls. The convention detector (R14) gains an `ai-sdk` shape. Small, additive.

## 6. Phasing (mirror Python P0–P3)

1. **P0** — `init` + OTLP export + the context processor; OpenAI + Anthropic instrumentors; `trace`.
   Acceptance: a plain OpenAI call → one GENERATION span with model/tokens/cost, zero span code.
2. **P1** — `observe`; the Vercel AI SDK path (client side + the `ai.*` backend mapping).
3. **P2** — LangChain/LangGraph.js + the `wrapOpenAI` drop-in.
4. **P3** — convention-version provenance already handled server-side (R14); JS hardening + the
   manual span API (`tracely.llm()/tool()/...`) as the escape hatch.

## 7. Risks / open questions

- **`ai.*` is Vercel-proprietary and evolves** — same drift discipline as `gen_ai.*` (R14): record
  `tracely.otel.gen_ai_convention = "ai-sdk"` + the package version for tracking.
- **Edge/serverless runtimes** — OTLP batch export + process exit: ensure `flush()` on
  `waitUntil`/before-exit (Vercel Edge, Lambda). Document, like Python's `flush()`.
- **worker_threads** — `AsyncLocalStorage` does not cross worker boundaries; document explicit
  context passing (the JS analog of Python's `run_in_thread`), though it's rarely needed.
- **ESM/CJS + instrumentation patching** — OTel-JS monkey-patching requires the instrumentations to
  register before the provider module is imported; document the `--import`/`-r` bootstrap, the JS
  analog of "call `init()` first."
