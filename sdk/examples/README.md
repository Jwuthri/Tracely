# `sdk/examples/` — one runnable example per way of tracing

Every example is the **same realistic agent**: a customer-support agent that answers _"Where is my
order ORD-4471, and is the Alpine Winter Coat back in stock?"_ by calling two tools against a fake
e-commerce DB ([`_fake_db.py`](_fake_db.py)) — `get_order_status` + `check_inventory` — then
summarizing. So each file shows a real tool-calling loop (plus thinking, in the `@observe`/manual
ones), not a toy single call. Each guards on its instrumentor + API key, printing setup hints instead
of crashing when a dependency or key is missing.

```bash
pip install "tracely-sdk[<extra>]"     # the extra named in each file's header
export TRACELY_API=http://localhost:8000           # your Tracely API (default shown)
export OPENAI_API_KEY=sk-...                        # (or the provider's key)
uv run python sdk/examples/<file>.py
```

## Ways of sending traces (the SDK layers)

| File | Layer | Shows |
|---|---|---|
| [`auto_agent.py`](auto_agent.py) | L2 + L3 | `@observe` agent + `trace()` → **AGENT → thinking · 2 generations · 2 tools** tree |
| [`dropin_openai.py`](dropin_openai.py) | R13 | non-patching `wrap_openai` — the tool-calling agent, nothing patched globally |
| [`dropin_anthropic.py`](dropin_anthropic.py) | R13 | non-patching `wrap_anthropic` — the Claude tool-calling agent |
| [`manual_spans.py`](manual_spans.py) | L4 | the manual escape hatch — full agent: thinking → llm → tools (one **errors**) → answer (no key needed) |

## Frontier providers (L1 — auto-instrumented, zero span code)

| File | `instrument=` | Extra | Key |
|---|---|---|---|
| [`auto_openai.py`](auto_openai.py) | `["openai"]` | `[openai]` | `OPENAI_API_KEY` |
| [`auto_anthropic.py`](auto_anthropic.py) | `["anthropic"]` | `[anthropic]` | `ANTHROPIC_API_KEY` |
| [`auto_gemini.py`](auto_gemini.py) | `["gemini"]` | `[google]` | `GEMINI_API_KEY` |
| [`auto_mistral.py`](auto_mistral.py) | `["mistral"]` | `[mistral]` | `MISTRAL_API_KEY` |
| [`auto_bedrock.py`](auto_bedrock.py) | `["bedrock"]` | `[bedrock]` | AWS creds + `AWS_REGION` |
| [`auto_openrouter.py`](auto_openrouter.py) | `["openai"]` | `[openai]` | `OPENROUTER_API_KEY` |

> **Gateways (OpenRouter, etc.) need no special handling** — they're OpenAI-wire-compatible, so the
> OpenAI instrumentor (or LangChain/LiteLLM/LlamaIndex's OpenRouter handler, traced by *its*
> instrumentor) captures them. Just set the `base_url`; the routed model (`vendor/model`) flows into
> `model_id`. `auto_openrouter.py` shows the direct OpenAI-SDK path + the framework variants.

## Harnesses (L1 — orchestration frameworks)

| File | `instrument=` | Extra | Agent pattern |
|---|---|---|---|
| [`auto_langchain.py`](auto_langchain.py) | `["langchain"]` | `[langchain]` | `create_tool_calling_agent` + `AgentExecutor` with the fake-DB tools |
| [`auto_langgraph.py`](auto_langgraph.py) | `["langchain"]` | `[langchain]` | `create_react_agent` (ReAct graph; node name → `step_name`) |
| [`auto_litellm.py`](auto_litellm.py) | `["litellm"]` | `[litellm]` | OpenAI-shaped tool-calling loop via one callback |
| [`auto_llama_index.py`](auto_llama_index.py) | `["llama-index"]` | `[llama-index]` | `ReActAgent` over `FunctionTool`s |
| [`auto_crewai.py`](auto_crewai.py) | `["crewai"]` | `[crewai]` | a `Crew` whose agent is equipped with the tools |

> `instrument="auto"` activates whichever of these are importable; when a harness instrumentor (e.g.
> LangChain) is present it owns the LLM spans and the provider instrumentors are skipped to avoid
> duplicate spans (override with an explicit list). See the docs [Automatic instrumentation](../../docs/pages/automatic.mdx) page.

## Demo data & CI-gate examples (not tracing how-tos)

| File | Shows |
|---|---|
| [`seed_conversations.py`](seed_conversations.py) | rich manual-API demo data — every observation type (`make seed-demo`) |
| [`seed_regression.py`](seed_regression.py) | promote a failing trace → red→green CI gates (`make seed-regression`) |
| [`seed_multicall.py`](seed_multicall.py) / [`seed_handler.py`](seed_handler.py) | repeated-call + handler fixtures for hermetic replay |
| [`weather_agent.py`](weather_agent.py) / [`weather_agent_cli.py`](weather_agent_cli.py) | a real agent wired for `tracely replay --entrypoint` / `--cmd` |
