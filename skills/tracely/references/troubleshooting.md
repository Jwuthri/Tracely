# Troubleshooting

Work top-down: most "Tracely is broken" reports are one of the first four rows.

## Nothing arrives

| Symptom | Cause | Fix |
|---|---|---|
| No trace at all after a script run | Process exited before the exporter flushed | `tracely.flush()` before exit — always in scripts, tests, Lambdas, CLI runs |
| No trace, no error | Wrong `endpoint` — it must be the **API** host, not the UI | `http://localhost:8000` (API), not `:3001` (UI). Hosted: `https://api.tracely-studio.xyz` |
| `401` / traces vanish | Wrong or missing ingest key | The key **is** the workspace: Settings → API keys. Self-host dev seed is `tracely_dev_key` |
| Traces appear seconds late | Normal — evaluation is debounced ~4s to absorb late spans | Wait, then refresh |
| Spans arrive, nothing renders | Hand-written OTLP with **hex** span ids | OTLP span ids are **base64**. Hex doesn't error, it yields a 24-byte id nothing can look up. Use a real OTLP exporter |

## The tree is wrong

| Symptom | Cause | Fix |
|---|---|---|
| Every span is its own root | The call isn't inside `trace()` / an `@observe` span | Wrap the run; nesting is OTel-context-based |
| Spans from a worker thread float free | Auto-nesting is contextvar-based, in-process | `tracely.run_in_thread(fn, arg)` copies the context |
| Turns don't group into a conversation | Missing or per-turn-different `conversation` id | Pass the **same** `conversation=` to every turn. Raw OTLP: set `tracely.conversation.id` (or `gen_ai.conversation.id`) |
| Everything is under one `default` agent | Nothing declared `tracely.agent.id` — framework attributes like `gen_ai.agent.name` are ignored on purpose | Set `init(service_name="…")` (it names the agent), `init(agent="…")` to override, or `agent=` per run on `trace()`/`agent()`. Raw OTLP: set `tracely.agent.id` |
| Every LLM call appears twice | Two instrumentors on the same call | LangChain + provider, or LiteLLM + provider. Under `"auto"` LangChain wins automatically; otherwise name one path, or disable the overlap with `OTEL_PYTHON_DISABLED_INSTRUMENTATIONS` |
| Google ADK produces nothing | ADK patches at import time | `init(instrument=["google-adk"])` **before** `import google.adk` |
| I/O renders as a half-text/half-JSON smush | Payload isn't in a recognised shape | Use a message array, a `{role, content}` object, or typed content blocks (`manual.md` § structured I/O) |

## Numbers are missing

| Symptom | Cause | Fix |
|---|---|---|
| Streamed calls have no tokens or cost | OpenAI omits usage on streams unless asked | `stream_options={"include_usage": True}` |
| Cost is blank | Cost is **derived** from model name + tokens; an unrecognised model id has no rate | Check the model id that reached the span (gateways rewrite it); usage must be present |
| Manual spans have no tokens | `set_usage` never called | `tracely.set_usage(span, input_tokens=…, output_tokens=…)` |
| State drawer is empty | `set_state()` called with no active span | Inside a framework callback there is no current span (`trace()` is a marker, not a span). Pass `span=` explicitly — a bare call warns rather than dropping the write |
| PII still visible | `redact` set on a later `init()` | The exporter is built on the **first** `init()` and reused |

## Evaluators don't grade

| Symptom | Cause | Fix |
|---|---|---|
| A new column is blank | New evaluators grade traces ingested **from now on** | Backfill from the Evaluations UI |
| Column blank on some traces only | `target_agent` / `target_env` / `sampling` | Those apply to the automatic run only; an explicit re-run from the UI always grades |
| Judge columns all blank | No LLM key | Structural checks still run; judges degrade rather than crash. Set the workspace's OpenRouter key (Settings) |
| API rejects the evaluator | Structural level mismatch | The level is fixed per check: `tool_success`→`TOOL`, everything else →`AGENT_RUN` |
| One rubric turns the whole workspace red | A subjective judge flipping the roll-up | Set `advisory: true` — the verdict still shows, it just stops failing runs |
| Judge disagrees with humans | Uncalibrated | Label verdicts on the Calibration page; check `false_fail` before letting it gate |
| Trace count doubled after enabling evaluators | Tracely records its own eval runs as traces | They're excluded from lists and metrics by design and live behind the **Evals** filter chip — if they're leaking into counts, that's a bug worth reporting |

## The gate is lying

| Symptom | Cause | Fix |
|---|---|---|
| Green, but nothing was actually checked | Conversations ran and produced no scores | That's `UNGRADED` — it counts against the pass rate; all-ungraded reports `NO_COVERAGE` and blocks. If it went green anyway, the suite has no evaluators targeting it |
| Tool expectations all report `SKIP` | Your service didn't continue the `traceparent` | Wrap the handler in `tracely.trace(traceparent=request.headers.get("traceparent"))` — without it Tracely sees text in / text out |
| An adversarial suite always passes | Polarity confusion | Goal **achieved** = attack succeeded = FAIL. Also: no LLM key → the scenario is skipped, not passed |
| An agent silently isn't gated | No enabled scenario | `--all` derives from the scenario list; an agent with no enabled scenario is skipped by design. No endpoint + enabled scenarios → `NO_COVERAGE`, which blocks |
| The job is green but an agent was red | Two posts overwriting each other | Not possible via the CLI — all agents share one status and one comment, worst-wins. If you see it, you're posting statuses yourself |
| Exit code 2 | Never got an answer: timeout, unreachable API, or a server-side ERROR run | Not a pass. Check `--timeout` (default 900s, whole command) and API reachability |
| Replay makes real API calls | `--live`, or the provider isn't covered by the fixture patch | Hermetic covers `@observe` tools, OpenAI `chat.completions`, Anthropic `messages`. Elsewhere use the `call_tool`/`call_llm` seam |

## Self-hosted stack

| Symptom | Fix |
|---|---|
| Worker code changes have no effect | The Celery worker **does not hot-reload** — `docker compose restart worker`. Backend and frontend are volume-mounted and do reload |
| Worker restarts on first deploy | Expected while the backend creates the schema — it self-heals |
| Forms refuse to save an OpenRouter key or endpoint token | `SECRETS_ENCRYPTION_KEY` unset — it refuses rather than storing plaintext |
| Prod refuses to boot | `AUTH_MODE=dev` or a seeded `tracely_dev_key` in prod is a hard guard |
| Frontend login loops | `NEXT_PUBLIC_AUTH_MODE` must match the backend's `AUTH_MODE` |

## Debug procedure when nothing above fits

1. Reduce to the smallest reproduction: `init()` → one provider call → `flush()`.
2. Confirm the raw POST: the SDK targets `POST {endpoint}/v1/traces` with
   `Authorization: Bearer <key>`. A 2xx means ingest accepted it and the problem is downstream.
3. Look at one span in the UI's span panel — attributes tell you which convention was recognised.
4. Ask the MCP server: `list_traces(limit=5)` then `get_trace(trace_id)` shows exactly what landed,
   which is faster than reading the UI when you're already in an editor.
