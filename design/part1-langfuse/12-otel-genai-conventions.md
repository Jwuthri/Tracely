# OpenTelemetry GenAI & Agent Semantic Conventions (2025–2026): What Tracely Should Speak on the Wire

> Research note for the Tracely design series. Goal: ground Tracely's *native wire format* in the **actual** OpenTelemetry GenAI semantic conventions as they stand in 2025–2026, contrast the main vendor flavors (OpenLLMetry/Traceloop, OpenInference/Arize, Logfire/Pydantic, Langfuse extensions), and decide what a trace-native, agent-first CI/CD platform should adopt to be OTel-compatible and future-proof.

---

## TL;DR

- **There is now a real standard, and it is span-centric.** OpenTelemetry defines GenAI semantic conventions covering **client spans** (`chat`, `text_completion`, `embeddings`, `generate_content`), **agent/framework spans** (`create_agent`, `invoke_agent`, `invoke_workflow`, `execute_tool`), **events**, and **metrics**. The whole namespace is `gen_ai.*`. Source: [OTel GenAI overview](https://opentelemetry.io/docs/specs/semconv/gen-ai/), [client spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/), [agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/).
- **Status is still "Development" (experimental), and it is moving fast.** Versions v1.37 → v1.41 each touched GenAI conventions in rapid succession; there is no public stabilization timeline, but core concepts (span shapes, operation names, token usage) have largely settled. Source: [OTel GenAI overview](https://opentelemetry.io/docs/specs/semconv/gen-ai/), [Greptime, May 2026](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions).
- **The prompt/completion debate is resolved in favor of structured *span attributes*.** As of **v1.37** the per-message events (`gen_ai.user.message`, `gen_ai.assistant.message`, `gen_ai.choice`, …) are **deprecated** in favor of `gen_ai.input.messages`, `gen_ai.output.messages`, and `gen_ai.system_instructions`. As of **v1.38** the old flat `gen_ai.prompt` / `gen_ai.completion` attributes are **removed**. Source: [GenAI events spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/), [semconv v1.37.0 docs](https://github.com/open-telemetry/semantic-conventions/tree/v1.37.0/docs/gen-ai), [OpenLLMetry issue #3515](https://github.com/traceloop/openllmetry/issues/3515).
- **Content capture is opt-in.** By default instrumentations emit only metadata (model, token counts, durations); message bodies and tool args/results are recorded only when explicitly enabled, with a documented external-storage hook for sensitive data. Source: [client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/).
- **The vendor flavors split into two camps:** those that *converged onto* `gen_ai.*` (OpenLLMetry/Traceloop — now upstreamed; Logfire/Pydantic AI; the OpenAI/Anthropic/Bedrock instrumentations) versus **OpenInference (Arize)**, which uses its *own* non-`gen_ai` namespace (`openinference.span.kind`, `llm.*`, `input.value`/`output.value`). Langfuse is a *consumer* that ingests all of them via an OTLP endpoint and a multi-namespace attribute mapper. Sources: [Traceloop semconv](https://www.traceloop.com/docs/openllmetry/contributing/semantic-conventions), [OpenInference spec](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md), [Langfuse OTel](https://langfuse.com/integrations/native/opentelemetry).
- **Recommendation for Tracely:** adopt **OTel `gen_ai.*` (latest experimental) as the native wire format** — specifically the structured `gen_ai.input.messages`/`gen_ai.output.messages` model plus the agent span tree (`invoke_agent` → `chat` → `execute_tool`) — but **own your storage schema and treat the wire format as an adapter layer**, exactly as Langfuse does. Maintain an OpenInference ingestion adapter as a first-class second input. Add a thin `tracely.*` extension namespace for your CI/CD-derived concepts (failure cluster, regression case, gate decision) that OTel does not model.

---

## 1. The shape of the standard

### 1.1 Where it lives and who owns it

GenAI conventions were originally inside the monolithic `open-telemetry/semantic-conventions` repo. They have since been **split into a dedicated repository**, `open-telemetry/semantic-conventions-genai`, maintained by the **GenAI Special Interest Group (SIG)** that sits under the Semantic Conventions SIG (the SIG was formed in 2024). The human-readable docs are generated from YAML model files via Weaver. ([semantic-conventions-genai repo](https://github.com/open-telemetry/semantic-conventions-genai); [OTel GenAI overview](https://opentelemetry.io/docs/specs/semconv/gen-ai/))

The canonical published docs render at `opentelemetry.io/docs/specs/semconv/gen-ai/` and break into:
- **`gen-ai-spans`** — client/inference spans ([link](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/))
- **`gen-ai-agent-spans`** — agent & framework spans ([link](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/))
- **`gen-ai-events`** — events for inputs/outputs and evaluation ([link](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/))
- **`gen-ai-metrics`** — token usage & duration histograms ([link](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/))
- **per-vendor**: OpenAI, Anthropic, Azure AI Inference, AWS Bedrock, plus **Model Context Protocol (MCP)** ([overview](https://opentelemetry.io/docs/specs/semconv/gen-ai/))

### 1.2 Stability: experimental, opt-in, versioned baseline

The entire GenAI surface is **Development** (experimental) status — *not* stable — as of mid‑2026. The migration mechanism is the env var **`OTEL_SEMCONV_STABILITY_OPT_IN`**:

- **Default**: an instrumentation keeps emitting whatever version it shipped with (treated as the **v1.36.0** baseline or prior).
- **`gen_ai_latest_experimental`**: emit the newest experimental conventions the instrumentation supports (the v1.37+ structured-message world).

The spec explicitly notes the transition plan "will be updated to include a stable version before the GenAI conventions are marked as stable." So v1.36 is the *frozen old shape*, and `gen_ai_latest_experimental` is how you opt into the modern shape today. ([client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/); [GenAI overview](https://opentelemetry.io/docs/specs/semconv/gen-ai/))

The Greptime engineering writeup (May 2026) counts **six semconv versions, v1.37–v1.41**, that have touched GenAI, and frames adopting the conventions now as "a reasonable bet" because the core concepts have settled even though "attribute names and structures may still change." ([Greptime](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions))

---

## 2. The inference / chat span (the atom)

### 2.1 Span name and operation

Span name format is **`{gen_ai.operation.name} {gen_ai.request.model}`** (e.g. `chat gpt-4o`). ([client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/))

`gen_ai.operation.name` is the central discriminator. Defined values include:

| Operation | Meaning |
|---|---|
| `chat` | Chat-completion call |
| `text_completion` | Legacy text completion |
| `generate_content` | Multimodal generation |
| `embeddings` | Embedding generation |
| `retrieval` | Vector-store / data-source retrieval |
| `execute_tool` | Tool execution |
| `create_agent` / `invoke_agent` / `invoke_workflow` | Agent & framework operations |

Source: [client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/), [registry of gen_ai attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/).

### 2.2 Required / conditional attributes on an inference span

- **Required**: `gen_ai.operation.name`; `gen_ai.provider.name` (e.g. `openai`, `anthropic`, `aws.bedrock`, `gcp.vertex_ai`). `error.type` is required if the op failed. (`gen_ai.provider.name` replaced the older `gen_ai.system`.)
- **Conditionally required**: `gen_ai.request.model`, `gen_ai.output.type` (`text` | `json` | `image` | `speech`), `gen_ai.request.stream` (streaming only), `server.address` / `server.port`.

Source: [client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/).

### 2.3 Request parameters (recommended)

`gen_ai.request.temperature`, `gen_ai.request.max_tokens`, `gen_ai.request.top_p`, `gen_ai.request.top_k`, `gen_ai.request.frequency_penalty`, `gen_ai.request.presence_penalty`, `gen_ai.request.stop_sequences` (string[]), `gen_ai.request.seed`, `gen_ai.request.choice.count`. ([client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/))

### 2.4 Response attributes (recommended)

`gen_ai.response.model` (actual model if it differs from requested), `gen_ai.response.id`, `gen_ai.response.finish_reasons` (string[]), and for streaming `gen_ai.response.time_to_first_chunk`. ([client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/))

### 2.5 Token / usage attributes (recommended)

- `gen_ai.usage.input_tokens` (int)
- `gen_ai.usage.output_tokens` (int)
- `gen_ai.usage.reasoning.output_tokens` — reasoning/thinking models
- `gen_ai.usage.cache_creation.input_tokens` — tokens written to prompt cache
- `gen_ai.usage.cache_read.input_tokens` — tokens served from prompt cache

Source: [client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/). Note the provider-specific cache fields are surfaced through the `gen_ai.provider.name` discriminator — generic base + provider extensions. ([Greptime](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions))

---

## 3. How prompts & completions are carried — the decisive design point

This is the question that matters most for a wire format, and the SIG has changed its mind here twice. The current answer:

### 3.1 The structured-message attribute model (v1.37+)

Three structured attributes replace everything that came before:

- **`gen_ai.system_instructions`** — array of instruction parts, each `{ "type": "text", "content": "<instruction text>" }`.
- **`gen_ai.input.messages`** — ordered array of message objects: `{ "role": "<user|assistant|tool|...>", "parts": [ <part>, ... ] }`. *"Messages MUST be provided in the order they were sent to the model."*
- **`gen_ai.output.messages`** — same message shape, plus `finish_reason` per message (`"stop"`, `"length"`, …); role is typically `"assistant"`.

Each **part** has a `type`:

| part `type` | fields |
|---|---|
| `text` | `content` (string) |
| `tool_call` | `id`, `name`, `arguments` |
| `tool_call_response` | `id`, `result` |

The spec references formal JSON schemas `gen-ai-input-messages.json` and `gen-ai-output-messages.json`. This means **a tool call and its result live *inside* the message parts array of the chat span**, not only as separate spans — the chat span is self-describing. Source: [client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/).

### 3.2 What got deprecated/removed

- **v1.37**: the per-message **events** are deprecated —
  `gen_ai.system.message` → use `gen_ai.system_instructions` / `gen_ai.input.messages`;
  `gen_ai.user.message` / `gen_ai.assistant.message` / `gen_ai.tool.message` → use `gen_ai.input.messages`;
  `gen_ai.choice` → use `gen_ai.output.messages`.
  ([semconv v1.37.0 gen-ai docs](https://github.com/open-telemetry/semantic-conventions/tree/v1.37.0/docs/gen-ai))
- **v1.38**: the flat **`gen_ai.prompt`** and **`gen_ai.completion`** attributes are **deprecated and removed**. (This caused a concrete migration in downstream libraries — see [OpenLLMetry issue #3515](https://github.com/traceloop/openllmetry/issues/3515).)

### 3.3 Spans vs. events vs. logs — where the bodies go

The events spec is now narrow: it defines **`gen_ai.client.inference.operation.details`** (a single event that can carry the same `gen_ai.input.messages` / `gen_ai.output.messages` payload *off* the span) and **`gen_ai.evaluation.result`** (evaluation outcomes). The structured message attributes can therefore live **either on the span or in that event** — backends consume them either way. ([GenAI events spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/))

The practical reading (synthesis): the SIG re-litigated "events vs. attributes" and landed on **attributes as the primary carrier**, with the inference-details event as an optional sidecar for backends that want content separated from the span. The earlier "put every message in its own log event" approach is dead. ([GitHub discussion #2010](https://github.com/open-telemetry/semantic-conventions/issues/2010); synthesis from [events spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/) + [v1.37 docs](https://github.com/open-telemetry/semantic-conventions/tree/v1.37.0/docs/gen-ai))

### 3.4 Privacy posture

By default **no message content, tool arguments, or tool results are captured** — only metadata (model, token counts, durations). Content capture is opt-in, and the spec defines a **user-defined content-upload hook** that runs independently of the opt-in flag and regardless of sampling, so applications can route sensitive bodies to external storage. ([client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/))

---

## 4. The agent & tool spans (the part Tracely lives in)

This is the newer and most strategically relevant layer for an agent-first product.

### 4.1 Agent operations and span names

- **`create_agent`** — agent creation (mostly remote agent services). Span name: `create_agent {gen_ai.agent.name}`.
- **`invoke_agent`** — agent invocation. Span name: `invoke_agent {gen_ai.agent.name}` (or just `invoke_agent` if name unavailable). **As of v1.41 this splits by span kind**: **CLIENT** for remote agent services (e.g. OpenAI Assistants), **INTERNAL** for in-process frameworks (e.g. LangGraph).
- **`invoke_workflow`** — a *predetermined* path (deterministic workflow) vs. autonomous agent reasoning. Span name: `invoke_workflow {gen_ai.workflow.name}`.
- **`execute_tool`** — tool execution. Span name: `execute_tool {gen_ai.tool.name}` (INTERNAL).

Sources: [agent spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/); [Greptime](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions).

### 4.2 Agent attributes

`gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.agent.description`, `gen_ai.agent.version` (all conditionally required when applicable). ([agent spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/))

### 4.3 Conversation & data-source correlation

- **`gen_ai.conversation.id`** — "the unique identifier for a conversation (session, thread), used to store and correlate messages within this conversation." This is the OTel-native hook for **multi-turn** conversation grouping.
- **`gen_ai.data_source.id`** — data-source id for retrieval/RAG agents.

Source: [agent spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/).

### 4.4 Tool-call attributes (on `execute_tool` spans)

`gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.type`, `gen_ai.tool.description`, and (opt-in, content) **`gen_ai.tool.call.arguments`** and **`gen_ai.tool.call.result`** — the latter two were added so a tool span carries both its input parameters and its output. Tool *definitions* available to the agent can be captured via the opt-in `gen_ai.tool.definitions`. Sources: [agent spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/); [client spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/).

### 4.5 The full agent span tree

A canonical agent trace nests as:

```
invoke_agent {name}            (INTERNAL for local frameworks; CLIENT for remote services)
├── chat {model}               (CLIENT — the LLM reasoning step; messages/tool_calls in gen_ai.input/output.messages)
├── execute_tool {tool}        (INTERNAL — gen_ai.tool.call.arguments / .result)
├── chat {model}
├── execute_tool {tool}
└── chat {model}
```

All sharing one `trace_id`. Greptime frames this as "cracking open the black box": each model call, tool selection, execution, and reasoning continuation becomes a distinct, observable span. **Sub-agents and handoffs** are represented as nested `invoke_agent` spans inside a parent `invoke_agent` (planner/executor and multi-agent systems fall out of the same parent/child + `gen_ai.agent.*` model), though the spec does not yet prescribe a dedicated "handoff" semantic. Sources: [Greptime](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions); [agent spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/).

### 4.6 Framework/vendor adoption status

- **Mature**: `opentelemetry-instrumentation-openai-v2` (OpenAI Python SDK) — the recommended starting point.
- **Active/community**: Anthropic, Cohere, AWS Bedrock instrumentations.
- **In progress**: LangGraph and CrewAI framework instrumentations.
- **Backends**: Datadog natively supports v1.37+; Honeycomb, Grafana, New Relic, OpenObserve recognize the standard metrics.

Sources: [Greptime](https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions); [OTel GenAI blog, 2026](https://opentelemetry.io/blog/2026/genai-observability/).

---

## 5. Metrics (for completeness)

Two standard histograms anchor GenAI metrics:

- **`gen_ai.client.token.usage`** — histogram, unit `{token}`, with explicit bucket boundaries `[1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]`.
- **`gen_ai.client.operation.duration`** — histogram, unit `s` (seconds).

These let backends aggregate token totals across a multi-call operation *without* the double-counting risk you get from summing `gen_ai.usage.*` span attributes up a tree (parent agent spans report the sum of children). Sources: [GenAI metrics spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/); [Logfire metrics-in-spans](https://pydantic.dev/docs/logfire/observe/llm-panels/).

---

## 6. Vendor flavors: who speaks `gen_ai.*` and who doesn't

| Flavor | Namespace | Message bodies | Span kind discriminator | Relationship to OTel |
|---|---|---|---|---|
| **OTel GenAI (canonical)** | `gen_ai.*` | `gen_ai.input.messages` / `gen_ai.output.messages` (structured parts) | `gen_ai.operation.name` | The standard |
| **OpenLLMetry / Traceloop** | `gen_ai.*` + `traceloop.*` extras | historically `gen_ai.prompt`/`gen_ai.completion` (now migrating off, per #3515) | `gen_ai.operation.name` | **Upstreamed into OTel**; adds `traceloop.entity.name`, `traceloop.association.properties` |
| **Logfire / Pydantic AI / Vercel AI SDK** | `gen_ai.*` + `ai.*` extras | follows OTel GenAI | `gen_ai.operation.name` | **Conforms to OTel**; richer `ai.*` add-ons |
| **OpenInference (Arize/Phoenix)** | **own namespace** (`openinference.*`, `llm.*`, `input.value`/`output.value`) | `llm.input_messages.{i}.message.*` (flattened) | `openinference.span.kind` | **Parallel standard, NOT `gen_ai.*`** |
| **Langfuse** | consumer; `langfuse.*` overrides | ingests all of the above | derives type from `model` attr / `langfuse.observation.type` | **Ingestion adapter**, not an emitter standard |

### 6.1 OpenLLMetry / Traceloop

OpenLLMetry was an early extension of OTel conventions for LLM apps, adding prompt/completion/token attributes plus framework context (`traceloop.entity.name` = e.g. the LangChain chain class name; `traceloop.association.properties` = user id, chat id). Crucially, **OpenLLMetry's conventions have been upstreamed into OpenTelemetry**, and Traceloop is now migrating off the deprecated `gen_ai.prompt`/`gen_ai.completion` attributes that v1.38 removed. They also have an active RFC for agent observability. Sources: [Traceloop semconv](https://www.traceloop.com/docs/openllmetry/contributing/semantic-conventions); [OpenLLMetry #3515](https://github.com/traceloop/openllmetry/issues/3515); [agent RFC #3460](https://github.com/traceloop/openllmetry/issues/3460).

### 6.2 Logfire / Pydantic AI

Logfire is squarely in the `gen_ai.*` camp: Pydantic AI, the Vercel AI SDK, and OpenAI instrumentation emit `gen_ai.*` attributes (plus `ai.*` extras), and Logfire's "LLM Panels" render any standard `gen_ai.*` span as a readable conversation with token/cost/latency. They explicitly call out using `gen_ai.usage.input_tokens` / `output_tokens` and the `gen_ai.client.token.usage` metric, and they had to migrate OpenAI/Anthropic instrumentation to the new conventions. Sources: [Pydantic Vercel AI + Logfire](https://pydantic.dev/articles/vercel-ai-sdk-logfire-otel); [Logfire LLM panels](https://pydantic.dev/docs/logfire/observe/llm-panels/); [Logfire migration issue #1586](https://github.com/pydantic/logfire/issues/1586).

### 6.3 OpenInference (Arize / Phoenix) — the important divergence

OpenInference is OTel-*based* (it rides OTLP) but uses a **completely different attribute namespace** from `gen_ai.*`. Key differences a Tracely ingestion layer must handle:

- **`openinference.span.kind`** is required on every span. Values: `LLM`, `CHAIN`, `TOOL`, `RETRIEVER`, `RERANKER`, `EMBEDDING`, `AGENT`, `GUARDRAIL`, `EVALUATOR`, `PROMPT`. (This is richer than OTel's `gen_ai.operation.name` set — note **`AGENT`, `GUARDRAIL`, `EVALUATOR`, `RERANKER`** as first-class kinds.)
- Generic I/O: **`input.value` / `output.value`** with `input.mime_type` / `output.mime_type`.
- Messages: flattened, indexed — `llm.input_messages.{i}.message.role`, `llm.input_messages.{i}.message.content`, `llm.output_messages.{i}.…`, multimodal via `message.contents.{j}.message_content.type`.
- Tokens: **`llm.token_count.prompt` / `.completion` / `.total`** (+ `prompt_details.cache_read`, `completion_details.reasoning`).
- Tools: `tool.name`, `tool.parameters`, `tool.json_schema`, `tool_call.function.name`, `tool_call.function.arguments`, `tool_call.id`.
- Identity: `llm.model_name`, `llm.system`, `llm.provider`; session via `session.id`; arbitrary `metadata`; `user.id`.

Source: [OpenInference semantic conventions](https://github.com/Arize-ai/openinference/blob/main/spec/semantic_conventions.md); [Arize docs](https://arize.com/docs/ax/observe/tracing-concepts/openinference-semantic-conventions). **Takeaway: OpenInference is a real, widely deployed second standard. Any agent-tracing product needs an OpenInference adapter, because LlamaIndex/LangChain users via Phoenix emit it.**

### 6.4 Langfuse — the model to copy for *ingestion*

Langfuse does **not** invent an emitter convention; it ingests OTLP and maps many namespaces to its own data model. This is the architectural pattern Tracely should mirror:

- **Endpoint**: `/api/public/otel/v1/traces` (OTLP HTTP, both protobuf and JSON; **no gRPC**).
- **Namespaces mapped** (precedence: `langfuse.*` wins): `gen_ai.*`, OpenInference `input.value`/`output.value` and `llm.*`, MLflow `mlflow.spanInputs`/`spanOutputs`, generic OTel resource/span attrs as metadata catch-all.
- **Observation typing**: default `span`; **any span with a `model` attribute becomes a `generation`**; `langfuse.observation.type` can force `span` | `generation` | `event`.
- **Custom override namespace** `langfuse.*`: `langfuse.observation.input/output`, `…type`, `…level`, `…model.name`, `…usage_details`, `…cost_details`, `…metadata.*`, plus trace-level `langfuse.trace.name`, `langfuse.session.id`, `langfuse.user.id`, `langfuse.trace.tags`, `langfuse.release`.
- **Model/token resolution order**: model = `langfuse.observation.model.name` → `gen_ai.request.model` → `gen_ai.response.model` → `llm.model_name` → `model`; tokens = `langfuse.observation.usage_details` → `gen_ai.usage.*` → `llm.token_count.*`; input = `langfuse.observation.input` → `gen_ai.prompt` → `input.value`; output symmetrically.

Source: [Langfuse OTel integration](https://langfuse.com/integrations/native/opentelemetry).

---

## 7. So what for Tracely

Tracely is **trace-native and agent-first**: the trace is the source of truth, and evals, regression tests, failure clusters, and gates are *derived*. That makes the wire format a foundational decision. Recommendations, in priority order:

1. **Adopt OTel `gen_ai.*` (latest experimental) as the canonical native wire format.** Specifically:
   - Ingest OTLP/HTTP (protobuf + JSON). Don't reinvent transport. (Match Langfuse's `/otel/v1/traces` posture.)
   - Treat the **structured message model** (`gen_ai.input.messages` / `gen_ai.output.messages` / `gen_ai.system_instructions` with typed `parts`: `text`, `tool_call`, `tool_call_response`) as your internal representation of a Turn/LLM Call. It already encodes tool calls *inside* the assistant message and tool results as `tool_call_response` parts — which is exactly the trajectory data you need for trajectory-level evals. *This is the single most reusable piece.*
   - Model your span tree on `invoke_agent` (CLIENT vs INTERNAL) → `chat` → `execute_tool`, with nested `invoke_agent` for sub-agents/handoffs and `invoke_workflow` for deterministic graph segments. Your entity map (Agent / Agent Run / Turn / Step / Tool Call / LLM Call / Sub-Agent Call) lines up almost 1:1.

2. **Decouple wire format from storage schema.** OTel GenAI is **experimental and churning** (v1.37→v1.41 in months; `gen_ai.prompt`/`completion` removed under downstream pain). Do **not** let `gen_ai.*` attribute names leak into your DB columns or public API. Build an **attribute-mapper / adapter layer** (Langfuse's `AttributeMapper` is the proof this works) so a convention bump is a mapper change, not a migration. Set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` for any SDK you ship/recommend.

3. **Ship an OpenInference ingestion adapter as a first-class second input — not an afterthought.** OpenInference is a genuinely parallel standard (its own namespace, `openinference.span.kind`, `llm.*`, `input.value`). A large slice of real agent traffic (LlamaIndex, LangChain via Phoenix) is OpenInference, not `gen_ai.*`. Map `openinference.span.kind` → your operation types, `llm.input_messages.*`/`output_messages.*` → your message model, `llm.token_count.*` → usage. Also map MLflow I/O attrs cheaply (Langfuse already does). Borrow OpenInference's **richer span-kind taxonomy** — `EVALUATOR`, `GUARDRAIL`, `RERANKER`, `AGENT` — because those map directly onto Tracely concepts that bare `gen_ai.operation.name` lacks.

4. **Use OTel's native correlation keys instead of inventing your own.** `gen_ai.conversation.id` = your Conversation/session grouping for multi-turn; `gen_ai.agent.id` + `gen_ai.agent.version` = your Agent / Agent Version linkage straight off the wire; `trace_id` = your Agent Run. This means a stock OTel SDK can populate Tracely's core entities with **zero custom instrumentation**.

5. **Add a thin `tracely.*` extension namespace — and only there — for what OTel does not model.** OTel covers observation; it does *not* model your CI/CD-derived concepts. Reserve `tracely.*` (mirroring `langfuse.*` overrides) for: `tracely.failure.cluster.id`, `tracely.regression.case.id`, `tracely.eval.suite.id` / `tracely.eval.case.id`, `tracely.gate.decision`, `tracely.agent.version` overrides, and content overrides (`tracely.observation.input/output`) for custom business spans. Keep these *additive* so a Tracely-emitted trace is still a valid OTel GenAI trace any other backend can read.

6. **Lean on the events spec for evaluation, not for messages.** Messages belong on spans (the SIG settled this). But `gen_ai.evaluation.result` is a ready-made carrier for *derived* eval outcomes — useful when Tracely writes evaluation results back as telemetry. And the optional `gen_ai.client.inference.operation.details` event is your escape hatch if you ever want to store large message bodies separated from the span (privacy/sampling), which the spec's external content-upload hook also supports.

7. **Default to metadata-only capture; gate content behind explicit opt-in + an external blob store.** The spec's privacy model (no bodies by default; opt-in content; sampling-independent upload hook) is exactly right for a platform that turns *production* traces into regression tests — those traces contain PII. Adopt it verbatim rather than designing your own.

**Net:** the OTel GenAI conventions' *evaluation/dataset* story is thin (only `gen_ai.evaluation.result`), which validates Tracely's thesis that eval should be trace-first and built *on top*, not adopted from a dataset-first vendor. But the *tracing* layer — structured messages, the agent span tree, conversation/agent/version correlation, token usage, privacy posture — is strong, converging, and the right native wire format. Speak `gen_ai.*` on the wire, ingest OpenInference too, own your schema behind a mapper, and extend with a minimal `tracely.*` namespace for CI/CD-derived concepts.
