# How Tracely Evaluations Work

> A practical, implementation-accurate guide to what Tracely evaluates, when it runs, where each result appears, and how batch and sequential modes differ. ✨

## The short version

Tracely evaluates **captured traces**, rather than hand-authored dataset rows. An evaluator is a configurable column: it has a stable score name, a level (conversation, message, or step), a type (structural or LLM judge), and optional targeting/sampling rules.

Each evaluator produces one or more **scores**. Scores are persisted alongside traces and shown in the table at the row matching their level:

| Table row | Internal evaluation level | What it grades |
|---|---|---|
| **C — Conversation** | `CONVERSATION` | The complete thread, across all turns |
| **M — Message** | `AGENT_RUN` | One trace, which normally represents one user turn and its agent response |
| **S — Step** | `SPAN`, `TOOL`, `GENERATION`, or `CHAIN` | A specific recorded span inside one trace |

The important distinction is scope:

- A **conversation** score answers “did the whole interaction succeed?”
- A **message** score answers “was this particular response/run good?”
- A **step** score answers “did this tool call, model call, chain node, or selected span do the right thing?”

---

## 1. What is being evaluated?

### Conversation level — `CONVERSATION`

A conversation evaluator receives all spans in a thread, ordered from oldest to newest. The LLM judge builds a compact turn-by-turn transcript from each trace’s user input and final agent answer.

Use this level for properties that require the whole interaction:

- Goal achievement / resolution
- User frustration
- Conversation efficiency
- Whether the user had to repeat themselves

There is one persisted score per evaluator per thread. It is addressed by `session_id` (the conversation id), not an individual trace id.

### Message level — `AGENT_RUN`

In the product UI this is called “message level.” Internally it is `AGENT_RUN` because a trace captures one agent execution. In ordinary conversational instrumentation, that is one user message → one agent response, plus all the work needed to produce it.

The judge sees:

1. the user request;
2. the final answer; and
3. the outputs of executed tool spans, when available.

Use this level for per-response qualities:

- Correctness and helpfulness
- Hallucination / faithfulness to tools
- Tone and professionalism
- PII leakage
- Intent classification
- Latency, run errors, or required tools

There is one score per evaluator per trace.

### Step level — `SPAN`, `TOOL`, `GENERATION`, `CHAIN`

Step-level evaluators produce one score for each qualifying span in a trace. The score’s `observation_id` points to the exact span, allowing the result to render on the corresponding **S** row.

| Evaluator level | Which spans it considers |
|---|---|
| `SPAN` | Selected span types; default for LLM judges is `TOOL` and `GENERATION` |
| `TOOL` | Only `TOOL` spans |
| `GENERATION` | Only model-generation spans |
| `CHAIN` | Only orchestration/chain spans |

Use step level when the problem is about a specific operation rather than the final answer:

- Did a tool succeed?
- Was a model call grounded or safe?
- Was a chain node’s output valid?
- Did a particular step choose the right action?

💡 A step-level LLM judge is capped at 30 eligible spans by default (`max_spans` can change this). If capped, every emitted score says how much of the trace was evaluated so partial coverage is visible.

---

## 2. Evaluator types

Tracely currently has two executable evaluator families.

### A. Structural evaluators — deterministic and cheap ⚙️

Structural evaluators inspect recorded spans directly. They do not call an LLM, so they are fast, deterministic, and suitable for high-volume production evaluation.

| Check | Required level | What fails it |
|---|---|---|
| `run_outcome` | `AGENT_RUN` | Any span in the run has error status |
| `tool_success` | `TOOL` | A `TOOL` span has error status; emits one result per tool span |
| `tool_consistency` | `AGENT_RUN` | The model requested a tool that has no recorded execution/result evidence |
| `latency` | `AGENT_RUN` | Total trace duration exceeds `budget_ms` |
| `required_tools` | `AGENT_RUN` | One or more configured tool names were not executed |

The API rejects invalid structural level/check pairs. This matters: a run-level check stamped as a tool-level result would have no tool span id, and therefore no honest row to display it on.

### B. LLM judges — configurable qualitative grading 🧠

An LLM judge sends the appropriate scope context to the configured judge model and persists its structured response as a score. Calls go through Tracely’s shared LLM provider, so model choice and usage are recorded consistently.

Supported output types:

| Output type | Stored result | Verdict behavior |
|---|---|---|
| `score` | Numeric value clamped to `0..1` | PASS when value is at least `threshold` (default `0.6`) |
| `number` | Numeric value | Informational unless a threshold is supplied |
| `boolean` | Boolean as `1` or `0` | PASS / FAIL directly |
| `text` | Free text | Informational; no verdict |
| `json` | User-defined JSON object | Optional numeric `score` / `overall_score` can drive a verdict |
| `category` | Legacy categorical label | Optional `fail_categories` controls verdict |

For `json`, the configured JSON Schema is the contract. The stored payload contains the user-defined fields; Tracely does not inject an extra wrapper into it.

### Basic versus advanced LLM judges

**Basic mode** uses a rubric prompt plus context chosen automatically by the level.

**Advanced mode** is activated when the prompt contains `@VARIABLE`s. The author explicitly selects what the judge can see, for example:

- `@HISTORY` — formatted conversation history
- `@CURRENT_MESSAGE.input` / `.output` — the current turn
- `@CURRENT_STEPS` — steps in the current trace
- `@CURRENT_STEP.tool_call` / `.tool_result` — the evaluated step
- `@PREVIOUS_USER_MSG` / `@PREVIOUS_ASSISTANT_MSG`
- `@METRIC_PREVIOUS_RESULT` — the previous result in sequential mode

Advanced mode fetches the whole thread only when the chosen variables actually need it. That keeps ordinary step and message evaluation from paying for conversation context it does not use.

---

## 3. Batch versus sequential execution

This setting controls **whether items of the same evaluator influence the next item**. It does not make different evaluator columns run in parallel or serial; evaluator dependencies are handled separately.

| Mode | Meaning | Best for |
|---|---|---|
| **Batch** (default) | Each eligible item is evaluated independently | Most quality, safety, correctness, tool, and classification checks |
| **Sequential** | The previous result of this same metric is included in the next item’s evaluation context | Continuity, drift, escalation, repeated-question, or progression checks |

### Batch mode

Batch is independent:

- Step 2 does **not** see Step 1’s verdict.
- Turn 2 does **not** see Turn 1’s verdict.
- It is the right default when each result should stand on its own.

### Sequential mode

Sequential mode carries a compact representation of the prior result: value, verdict, reason, and—for JSON output—the structured payload.

The sequence depends on the evaluator level:

| Level | Sequence |
|---|---|
| `CONVERSATION` | No effect: there is only one grade for the thread |
| `AGENT_RUN` | Oldest turn → newest turn across the conversation |
| Step levels | First eligible step → last eligible step within a trace; the last result also seeds the next turn when the conversation continues |

### How production execution stays correct

This timing is deliberate:

1. A trace first becomes quiet after its ingest debounce window.
2. **Batch** message and step evaluators run immediately for that trace.
3. Tracely also schedules a trailing debounce for the conversation.
4. When the whole thread becomes quiet, Tracely runs its conversation evaluators **and** all **sequential** message/step evaluators over the complete thread in oldest-to-newest order.

This avoids a subtle but important error: running a sequential message evaluator independently as every trace arrives would give it no previous-turn result and silently behave like batch mode.

---

## 4. Dependencies between evaluator columns

An LLM judge can declare `depends_on: ["other.score.name"]`.

Before dispatch, Tracely topologically sorts the selected columns. A dependent judge receives completed dependency results as extra context:

- A run-level or conversation-level dependency applies to the whole current subject.
- A step-level dependency is matched by `span_id`, so a composite check for step N receives step N’s prerequisite result.
- A cycle is logged and falls back to creation order rather than crashing the entire evaluation run.

Dependencies are distinct from sequential execution:

- **Dependencies** connect different evaluator columns.
- **Sequential mode** connects consecutive items of the same evaluator column.

---

## 5. Targeting and sampling

Targeting controls automatic evaluation spend. It applies to the normal ingest path, not to an explicit manual “run evaluation now” action.

| Setting | Effect |
|---|---|
| `target_agent` | Run only when the trace agent id or registered agent slug matches |
| `target_env` | Run only in the chosen environment, such as `prod` or `ci` |
| `sampling` | Keep a deterministic fraction of eligible subjects from `0` to `1` |

Sampling is deterministic rather than random. For trace/message/step evaluation, the sampling bucket is derived from `(trace_id, score_name)`. Re-ingesting or re-evaluating the same trace therefore makes the same keep/drop decision.

For a conversation evaluator, the subject is the complete thread:

- it matches when **any turn** belongs to the selected agent/environment; and
- it samples using `(thread_id, score_name)`.

That means a conversation does not flicker between sampled and unsampled just because another turn arrives.

---

## 6. Score storage, identity, and failure meaning

Every result is written to ClickHouse’s `scores` table with:

- the stable evaluator `name` / score name;
- `evaluation_level`;
- a numeric/text/category value where applicable;
- `verdict`: `PASS`, `FAIL`, or empty for informational metrics;
- a comment/reason; and
- LLM judge token/model metadata when a model was used.

Score identity is deterministic:

| Scope | Stable identity |
|---|---|
| Conversation | `(thread_id, score_name)` |
| Message/run | `(trace_id, score_name)` |
| Step | `(trace_id, score_name, span_id)` |

Re-running an evaluator therefore replaces the existing score instead of creating a duplicate.

### What marks a trace or conversation as failed?

The shared verdict policy is:

> A subject fails when it has at least one `FAIL` from a **non-advisory** evaluator.

Advisory evaluators still show their own failure pill and are useful signals, but they do not flip the trace badge, conversation dot, or trend failure count. The seeded answer-quality LLM judge is advisory by default; structural failures are not.

---

## 7. Online, manual, and gate evaluation

### Online production evaluation

The normal path is:

```text
OTLP trace arrives
        ↓
trace spans are stored
        ↓
per-trace trailing debounce
        ↓
batch message/step evaluators
        ↓
per-thread trailing debounce
        ↓
conversation evaluators + sequential message/step evaluators
        ↓
scores persist and failing non-advisory results can feed failure clustering
```

The debounce is important. A single agent run can arrive in multiple OTLP export batches; evaluating every partial batch would be wasteful and could grade an incomplete trajectory. Redis tracks a generation number per trace/thread, and only the latest scheduled task runs.

### Manual evaluation from the UI

Manual runs use the same evaluator engine and score writer.

- Running a **conversation** evaluates every turn and then the conversation-level columns once.
- Running a **trace** evaluates that trace’s message/step columns only; it deliberately skips conversation grading.
- Explicit manual runs ignore automatic targeting and sampling because the user deliberately selected the subject.

### Regression and gate evaluation

Regression cases and gates also consume traces and evaluator concepts, but their primary contract is replay-based fail-to-pass validation. Gate verdicts are persisted separately as regression verdict scores. The online evaluator system is useful for detecting production failures; promoted regression cases make those failures reproducible in CI.

---

## 8. Evaluation traces: why they exist and why they do not loop 🔍

Tracely records evaluator work itself as an internal trace. This makes a judge debuggable: you can inspect the evaluator column, its resolved prompt/model call, and the emitted verdict rather than treating a bad score as opaque.

These traces are marked with `internal_kind = eval` and are hidden from normal production trace lists unless the **Evals** view is selected.

They are never evaluated again. There are two safeguards:

1. ingestion does not schedule evaluation for internal traces; and
2. `EvaluationService` refuses them even when called directly.

Without both, evaluating an evaluation would record another evaluation, which would be evaluated again forever. 🚫

---

## 9. A quick decision guide

| If you need to ask… | Choose |
|---|---|
| “Did the user ultimately get what they needed?” | Conversation-level LLM judge |
| “Was this answer helpful, correct, safe, or grounded?” | Message-level LLM judge |
| “Did this tool execution fail?” | `tool_success` structural evaluator at `TOOL` |
| “Did the whole run error, exceed latency, or miss required tools?” | Run-level structural evaluator at `AGENT_RUN` |
| “Was this exact tool/model/chain step good?” | Step-level LLM judge |
| “Did quality deteriorate turn by turn?” | Sequential message-level LLM judge |
| “Did the agent repeat a bad pattern across steps?” | Sequential step-level LLM judge |
| “Should one judge use another judge’s output?” | `depends_on`, not sequential mode |

## Final mental model

Think of an evaluator as a **column plus a scope**:

```text
column definition
  = what to judge + how to judge + where it applies + how often it runs

scope
  = one conversation | one message/run | one recorded step

result
  = an idempotent, inspectable score attached to that exact scope
```

That model keeps the system legible: broad outcomes live on conversation rows, response quality lives on message rows, and operational evidence lives on the exact steps that produced it.
