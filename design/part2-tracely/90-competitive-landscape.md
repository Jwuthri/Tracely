# Competitive Landscape: Agent Evaluation, LLM Observability, and CI/CD for Agents

> Research date: 2026-06-02. All claims cite primary/vendor sources inline. Where a statement is the author's interpretation rather than a vendor claim, it is marked **(synthesis)**.

## TL;DR

- **The market has converged on a "dataset-first" mental model.** Almost every incumbent (LangSmith, Braintrust, Arize Phoenix, Galileo, Maxim, Patronus, DeepEval, OpenAI Evals) frames evaluation as: build a **dataset** of examples → run a **task/app** over it → score with **evaluators** → compare **experiments**. Datasets are the noun everything hangs off of. Production traces feed *into* datasets, but the dataset remains the unit of evaluation. ([LangSmith eval concepts](https://docs.langchain.com/langsmith/evaluation-concepts), [Phoenix datasets & experiments](https://arize.com/docs/phoenix/datasets-and-experiments/overview-datasets), [Galileo experiments](https://v2docs.galileo.ai/sdk-api/experiments/running-experiments))
- **CI/CD gating is increasingly table-stakes, but shallow.** Braintrust, LangSmith, Galileo, Maxim, DeepEval, Promptfoo and Patronus all advertise "run evals in CI, fail the build on a threshold." But in every case the CI artifact being run is *a dataset experiment*, not *a regression test derived from a specific production failure*. The gate is "average score on my curated dataset didn't drop," not "the exact failure trajectory we saw in prod last Tuesday does not recur." ([Braintrust CI/CD review](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025), [LangSmith pytest](https://docs.langchain.com/langsmith/pytest), [Galileo CI](https://galileo.ai/blog/continuous-integration-ci-ai-fundamentals))
- **Trajectory awareness is real and improving** (LangSmith's `agentevals`, Galileo's tool-selection/flow-adherence metrics, Patronus Percival, OpenAI trace grading, DeepEval component-level evals). The strongest trace-first signals come from **OpenAI's trace grading** ("start with traces … then move to datasets") and the small open-source tool **aevals.ai** ("Evaluate agent behavior from real traces, not synthetic replays"). ([OpenAI trace grading](https://developers.openai.com/api/docs/guides/trace-grading), [aevals.ai](https://aevals.ai/), [agentevals](https://github.com/langchain-ai/agentevals))
- **The closest competitor to Tracely's thesis is Braintrust.** Braintrust explicitly markets "turn LLM production failures into regression tests" with a one-click trace→dataset flow and a GitHub Action gate. **But it is still dataset-first under the hood, prompt/LLM-app-centric rather than agent-first, and the promotion of a failing trace into a permanent regression case is a manual, human-curated act** — not an automated production→regression→gate pipeline that is the product's spine. ([Braintrust: failures→regression tests](https://www.braintrust.dev/articles/turn-llm-production-failures-into-regression-tests))
- **White space (synthesis):** No incumbent makes *the production trace the primary unit of regression testing*, auto-clusters failures into suite candidates, and gates *PRs that change an agent version* on multi-level trajectory replays. Everyone bolts CI onto a dataset/experiment substrate; Tracely's wedge is making **trace → failure cluster → regression suite → PR gate** the *native object graph*, agent-first, for multi-agent/multi-turn systems.

---

## Scoring rubric

For each tool, four axes:

1. **Core model** — Dataset-first vs Trace-first (where does evaluation "start"?).
2. **Eval approach** — LLM-as-judge / code / human; multi-level (turn/step/tool/agent) or final-answer only.
3. **CI/CD gating** — Native GitHub Action? Threshold-based merge block? What artifact runs in CI?
4. **Agent / trajectory awareness** — Does it score *trajectories* (tool calls, handoffs, planner steps), or just outputs?

---

## Detailed findings

### 1. Braintrust — the dataset-first incumbent closest to the thesis

- **Core model: dataset-first, with a strong trace→dataset on-ramp.** Braintrust's own docs define an evaluation as three parts: "Data — a dataset of test cases with inputs, optional expected outputs, and metadata." Production logs are pulled into datasets to "improve offline test coverage." ([Evaluate systematically](https://www.braintrust.dev/docs/evaluate))
- **The regression-test story is the most thesis-adjacent in the market.** Their article *How to turn LLM production failures into regression tests* describes a five-step **trace-first-flavored** workflow: capture failed trace → diagnose failure mode (hallucination, retrieval miss, tool-arg error, format violation) → **promote into a versioned regression dataset** → write a scorer → gate releases. They state: "High-confidence failures can be promoted automatically … Ambiguous outputs … should go through human review before the trace becomes a permanent regression case." ([turn-llm-production-failures-into-regression-tests](https://www.braintrust.dev/articles/turn-llm-production-failures-into-regression-tests))
- **CI/CD gating: native and mature.** `braintrustdata/eval-action` runs eval suites on every PR, posts score breakdowns as PR comments, ties experiments to git metadata, and can block deploys on scorer thresholds. ([Best AI eval tools for CI/CD 2026](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025))
- **Agent/trajectory awareness:** You can "inspect every trace and tool call," but the eval *unit* remains a dataset row scored by a scorer; trajectory-native scoring is not the headline. **(synthesis)**
- **Company:** $36M Series A (Oct 2024) led by a16z at ~$150M post; customers include Notion, Stripe, Vercel, Airtable, Instacart, Zapier. ([a16z announcement](https://a16z.com/announcement/investing-in-braintrust/), [Braintrust Series A blog](https://www.braintrust.dev/blog/announcing-series-a))
- **Why it's not Tracely (synthesis):** The trace→regression flow is a *workflow article*, not the product's spine. The object model is Dataset/Experiment/Scorer. Promotion is human-curated and per-trace; there is no automatic *failure clustering* into suites, and the framing is LLM-app/prompt-centric, not Agent / Agent Version / Agent Run as first-class entities.

### 2. LangSmith (+ LangGraph Platform) — dataset-first with the best trajectory tooling

- **Core model: explicitly hybrid, dataset-first for offline.** "A dataset is a collection of examples used for evaluating an application." Offline evals "act as unit tests for your LLM application"; online evals "score real-world production traffic in real-time." ([eval concepts](https://docs.langchain.com/langsmith/evaluation-concepts))
- **Dataset creation** explicitly supports promoting historical/production traces (esp. negative feedback or high-latency runs) into datasets, plus synthetic generation. ([eval concepts](https://docs.langchain.com/langsmith/evaluation-concepts), [LangSmith eval product](https://www.langchain.com/langsmith/evaluation))
- **Trajectory awareness: strongest among the incumbents.** The `agentevals` OSS library provides **trajectory match evaluators** in four modes — *strict* (same messages/tool calls, same order), *unordered* (same tool calls, any order), *subset* (no unnecessary calls), *superset* (critical calls present) — plus LLM-as-judge trajectory scoring and **graph trajectory evaluation for LangGraph** (node-based rather than message-based, with utilities to extract trajectories from threads incl. interrupts). ([agentevals](https://github.com/langchain-ai/agentevals)) The product page claims it captures "the full trajectory of steps, tool calls, and reasoning your agent took." ([LangSmith eval](https://www.langchain.com/langsmith/evaluation))
- **CI/CD gating: native and detailed.** Pytest/Vitest integrations: the `@pytest.mark.langsmith` decorator syncs each test case to a dataset example and creates an experiment per run; "run evals on every PR … set thresholds … fail pipelines automatically when scores drop." ([pytest docs](https://docs.langchain.com/langsmith/pytest), [pytest/vitest launch](https://blog.langchain.com/pytest-and-vitest-for-langsmith-evals/))
- **Why it's not Tracely (synthesis):** Even with the best trajectory evaluators, the CI artifact is *a dataset experiment* and the regression assertion is "new version outperforms baseline on dataset metrics." Trajectory eval is a *scoring function you point at a dataset*, not a production-failure-derived suite that gates the PR that changed the agent. LangGraph-centric gravity, though they claim framework-agnosticism.

### 3. Arize Phoenix (+ Arize AX) — observability-first, dataset-based experiments

- **Core model: trace-first for observability, dataset-first for evaluation.** Built on OpenTelemetry/OpenInference; ingests traces over OTLP with broad auto-instrumentation (LangGraph, OpenAI Agents SDK, CrewAI, LlamaIndex, Vercel AI SDK, etc.). ([What is Phoenix](https://arize.com/docs/phoenix), [Phoenix GitHub](https://github.com/arize-ai/phoenix))
- **Evaluation = datasets + experiments.** "Datasets … provide the inputs and, optionally, expected reference outputs." Run an experiment = define dataset → task fn → evaluators → run; "Dataset Evaluators serve as test cases … an evaluation harness similar to a unit test suite." ([datasets overview](https://arize.com/docs/phoenix/datasets-and-experiments/overview-datasets))
- **CI/CD gating:** Supported but DIY in OSS Phoenix — generally "writing custom Python scripts," no first-class GitHub Action (a gap Braintrust calls out). Arize AX (the paid tier) documents CI/CD for automated experiments and a GitHub Action. ([Braintrust CI review](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025), [Arize AX CI/CD](https://arize.com/docs/ax/develop/datasets-and-experiments/ci-cd-for-automated-experiments))
- **Agent/trajectory awareness:** Strong agent *tracing* and agent-eval recipes (LLM-as-judge over spans), but the regression *gate* still runs over a curated dataset, not a production-failure suite. **(synthesis)**
- **Why it's not Tracely (synthesis):** Phoenix is the strongest open-source *observability* analog and a great "steal" reference for the trace layer — but its evaluation/CI story is dataset-experiment-first and not packaged as a PR gate.

### 4. Galileo — agent metrics + eval-gates, small judge models

- **Core model: observability + dataset-driven experiments.** "Experiments take a dataset … pass it to a prompt template or a custom function [up to] a full agentic workflow … and a list of metrics to evaluate the traces." ([running experiments](https://v2docs.galileo.ai/sdk-api/experiments/running-experiments))
- **Agent-specific metrics are a genuine strength.** Purpose-built metrics for **Tool Selection Quality, Tool Call Error detection, flow/action adherence, task completion, conversation quality, session success** — backed by research-grade accuracy claims and proprietary **Luna-2** judge models running at sub-200ms / ~$0.02 per M tokens. ([Galileo Evaluate profile](https://agentsindex.ai/galileo-ai-evaluate), [Luna-2 docs](https://docs.galileo.ai/how-to-guides/luna/evaluate-with-luna/evaluate-with-luna))
- **CI/CD gating: "eval gates."** "Eval gates are automated quality checks for context adherence, instruction adherence, tool selection quality, and hallucination detection that run on every commit or prompt change … continuous quality scores across multiple dimensions" rather than binary pass/fail. ([Galileo CI fundamentals](https://galileo.ai/blog/continuous-integration-ci-ai-fundamentals))
- **Agent/trajectory awareness:** High — among the best metric libraries for tool/flow correctness.
- **Why it's not Tracely (synthesis):** Galileo is the strongest "metrics for trajectories" player, and its cheap judge models are directly relevant to Tracely's economics. But the regression substrate is still dataset/experiment + commit-triggered eval gates; failures don't auto-become a named regression case bound to an agent version.

### 5. Maxim AI — simulate + evaluate + observe, prompt-IDE heavy

- **Core model: dataset/prompt-version test runs + agent simulation.** "Set up test runs using datasets, prompt versions, and workflows … create test runs programmatically through its SDK." Strong **multi-scenario agent simulation** ("test agents at scale across thousands of scenarios"). ([Platform overview](https://www.getmaxim.ai/docs/introduction/overview), [agent simulation](https://www.getmaxim.ai/products/agent-simulation-evaluation))
- **CI/CD gating:** "Within your CI/CD script (GitHub Actions, Jenkins, GitLab CI), use the Maxim SDK to programmatically trigger evaluation runs … enforce quality gates based on faithfulness, bias, toxicity, or custom metrics." ([Maxim CI/CD overview](https://www.getmaxim.ai/)) Also ships **Bifrost**, a fast OpenAI-compatible AI gateway. ([Bifrost](https://github.com/maximhq/bifrost))
- **Agent/trajectory awareness:** Good — simulation-driven trajectories, but the eval anchor is prompt versions + datasets, with heavy prompt-management/Playground tooling Tracely explicitly does NOT want.
- **Why it's not Tracely (synthesis):** Center of gravity is prompt engineering + simulation, not production-trace-derived regression. Prompt management is a feature, not a distraction Tracely should copy.

### 6. Patronus AI — judge models + agent debugger (Percival)

- **Core model: evaluator-API-first + curated benchmark datasets.** Self-serve eval/guardrails API; proprietary judge models — **Lynx** (hallucination, CoT-trained), **GLIDER** (~3.8B general rubric judge with reasoning chains, 8k context). ([Patronus evaluators](https://www.patronus.ai/blog/patronus-evaluators), [features](https://www.patronus.ai/product/features))
- **Percival**: an *agentic* debugger that analyzes execution traces and detects **20+ agentic failure modes** across reasoning/execution/planning/domain categories, remembers prior errors, and suggests prompt/workflow fixes — claimed 60x faster debugging on code-gen agents. ([Patronus Agents](https://www.patronus.ai/agents))
- **CI/CD gating:** "Continuous evaluation and regression testing of LLM systems in CI/CD pipelines" via Python/TS SDKs. ([Patronus docs](https://docs.patronus.ai/docs))
- **Agent/trajectory awareness:** High at the *diagnosis* layer (Percival reads trajectories), but the regression/gate substrate is still experiments + datasets/benchmarks.
- **Why it's not Tracely (synthesis):** Percival is the closest thing to Tracely's "failure detection + suggested fixes from traces," and is a strong reference for failure-mode taxonomy. But Patronus is an *eval-API and debugger* layered on a dataset/benchmark model — not a trace-native CI/CD product where suites are derived objects gating PRs.

### 7. Confident AI / DeepEval — pytest-native, component-level

- **Core model: dataset/test-case-first, but unusually code-native.** "Open-source LLM evaluation framework … similar to Pytest but specialized for unit testing LLM apps," with 50+ metrics (G-Eval, task completion, tool-use, conversational, RAG, safety). ([DeepEval GitHub](https://github.com/confident-ai/deepeval), [intro](https://deepeval.com/docs/introduction))
- **Component-level (trajectory-ish) evals:** explicitly "best for agents, tool-using workflows, MCP systems … tracing your app and evaluating individual spans, tools, planners, retrievers, generators." ([component-level evals](https://deepeval.com/docs/evaluation-component-level-llm-evals))
- **CI/CD gating: best-in-class developer ergonomics.** `assert_test()` + `deepeval test run` plug into pytest so "every push (or every PR) runs the same evals you'd run locally." ([unit testing in CI/CD](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd)) Confident AI is the hosted layer (dashboards, regression tracking, monitoring). ([DeepEval](https://deepeval.com/))
- **Agent/trajectory awareness:** Component-level evals trace spans; closest OSS analog to "multi-level eval." Test cases are still authored, not auto-derived from production failure clusters.
- **Why it's not Tracely (synthesis):** DeepEval is the developer-ergonomics gold standard (the pytest feel Tracely should match) and its component-level model validates multi-level eval. But it's a *test-case authoring framework* — the test case is the unit, not the production trace; no native failure clustering or PR-diff-aware agent-version gate.

### 8. OpenAI Evals + Trace Grading + AgentKit — the platform-native trace-first signal

- **OpenAI Evals (OSS):** classic **dataset-first** framework + benchmark registry (jsonl samples, YAML eval definitions). ([openai/evals](https://github.com/openai/evals))
- **But OpenAI's *agent* story is explicitly trace-first.** Trace grading: "assigning structured scores or labels to an agent's trace — the end-to-end log of decisions, tool calls, and reasoning steps." **Trajectory evals score a whole agent run** (tool-call sequence + intermediate messages + final output), now first-class in the Agents API. Recommended workflow: "**Start with traces and trace grading while behavior is still being debugged. Then move to datasets** … when the workflow is stable." ([trace grading](https://developers.openai.com/api/docs/guides/trace-grading), [evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals))
- **CI/CD gating:** *Not* a focus — OpenAI's docs do not describe PR gates; the loop is trace → grade → dataset → (Codex acts on changes). ([agent improvement loop](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop))
- **Why it's not Tracely (synthesis):** This is the single best *validation of the trace-first sequencing thesis* from the most influential vendor — yet it stops at "trace → grade → dataset," has no CI/CD gate, and is locked to the OpenAI Agents SDK. The gating + agent-framework-agnostic + failure-cluster layers are wide open.

### 9. Adjacent / notable

- **aevals.ai** — small OSS tool that scores agent behavior **directly from OpenTelemetry/Jaeger traces, no re-runs**: "Evaluate agent behavior from real traces, not synthetic replays … No need to replay expensive LLM calls." Closest *philosophical* match to trace-native eval, but it's a CLI scorer, not a CI/CD platform with failure clustering and PR gates. ([aevals.ai](https://aevals.ai/)) **(strong signal the thesis is in the air, unowned at platform scale)**
- **Promptfoo** — strong OSS red-team/eval with native CI across GitHub Actions/GitLab/Jenkins/CircleCI + quality gates, but config/declarative and prompt-test-centric, not agent-trace-native. ([Braintrust CI review](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025))
- **Humanloop** — was a prompt-management + eval + observability platform; **team acqui-hired by Anthropic in Aug 2025 (no IP/assets acquired), product wound down.** Effectively out of the independent market. ([TechCrunch](https://techcrunch.com/2025/08/13/anthropic-nabs-humanloop-team-as-competition-for-enterprise-ai-talent-heats-up/), [humanloop.com](https://humanloop.com/))
- **Langfuse** — the reader's reference observability stack; trace-strong, but its evaluation is dataset/experiment-first and CI is DIY-Python (no native GitHub Action). Explicitly the "tracing to steal, evaluation to leave" baseline. ([Braintrust CI review](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025))

---

## Comparison matrix

| Tool | Core model | Multi-level / trajectory eval | CI/CD gate (native?) | Agent-first object model | Production-failure → regression test as the *spine* |
|---|---|---|---|---|---|
| **Braintrust** | Dataset-first (strong trace→dataset) | Tool/trace visible; scorer-on-dataset | **Yes** — GitHub Action, PR comments, deploy block | No (LLM-app/prompt-centric) | **Workflow exists, manual, not the spine** |
| **LangSmith** | Hybrid; dataset-first offline | **Best** — `agentevals` strict/unordered/subset/superset + LangGraph graph eval | **Yes** — pytest/Vitest + GH workflows, threshold fail | Partial (LangGraph gravity) | No (dataset-experiment is the unit) |
| **Arize Phoenix** | Trace-first obs; dataset-first eval | Agent tracing + span LLM-judge | Partial (DIY in OSS; AX has GH Action) | No | No |
| **Galileo** | Obs + dataset experiments | **Strong metrics** (tool selection, flow adherence, session success) | **Yes** — "eval gates" per commit/prompt change | Partial | No |
| **Maxim** | Dataset/prompt-version + simulation | Simulation trajectories | Yes — SDK-triggered in GH/Jenkins/GitLab | Partial | No (prompt + sim centric) |
| **Patronus** | Eval-API + benchmark datasets | **Percival** reads trajectories, 20+ failure modes | Yes — SDK-based CI | Partial | No (debugger, not gate spine) |
| **DeepEval/Confident** | Test-case/dataset-first, code-native | **Component-level** spans/tools/planners | **Yes** — pytest-native, best ergonomics | No | No (authored test cases) |
| **OpenAI Evals + Trace Grading** | OSS Evals dataset-first; **Agents = trace-first** | **Trajectory evals on whole runs** | No PR gate | OpenAI Agents SDK only | Partial seq ("trace→grade→dataset"), no gate |
| **aevals.ai** | **Trace-first** (OTel, no replay) | Trajectory match + LLM-judge | CLI/CI only | Agent-ish | Philosophically yes; not a platform |
| **Tracely (target)** | **Trace-first, agent-first** | **Multi-level: conv/turn/step/tool/agent/multi-agent trajectories** | **PR-time gate on the agent version that changed** | **Yes — Agent/Version/Run/Trace/Suite/Cluster** | **The spine: trace → failure cluster → regression suite → gate** |

*(Matrix cells are the author's synthesis from the cited vendor sources above.)*

---

## So what for Tracely

**1. The thesis sequencing is validated by the strongest vendor, but no one has built the platform.** OpenAI itself tells agent builders to *start with traces, then move to datasets* ([trace grading](https://developers.openai.com/api/docs/guides/trace-grading)); aevals.ai sells "evaluate from real traces, not synthetic replays" ([aevals.ai](https://aevals.ai/)); Braintrust publishes the exact "production failures → regression tests" workflow ([Braintrust](https://www.braintrust.dev/articles/turn-llm-production-failures-into-regression-tests)). The *idea* is in the air. **What's missing is a product where the trace is the literal primary key and regression suites are a derived object that gates PRs.** That gap is real and defensible. **(synthesis)**

**2. The decisive wedge is the object model, not a feature.** Every incumbent's schema bottoms out in Dataset → Experiment → Scorer. Tracely's bet is Agent → Agent Version → Agent Run → Trace → (Conversation/Turn/Step/Tool/LLM/Sub-Agent Call) → Failure Cluster → Evaluation Suite → CI Gate. Because suites are *derived from clustered production failures*, the "regression test" is automatically bound to the agent version and the specific trajectory that failed — something a dataset row can't express. The competitors would each have to re-platform to copy this. **(synthesis)**

**3. Steal these, specifically:**
   - **Trajectory evaluator semantics from LangSmith `agentevals`** — strict / unordered / subset / superset matching + graph (node-based) trajectory eval are the right primitives for trajectory regression; design Tracely's suite assertions on this vocabulary. ([agentevals](https://github.com/langchain-ai/agentevals))
   - **Cheap small judge models à la Galileo Luna-2** — sub-200ms, ~$0.02/M tokens makes per-PR multi-level replay economically viable; trace-native gating *requires* this cost structure or it won't run on every PR. ([Luna-2](https://docs.galileo.ai/how-to-guides/luna/evaluate-with-luna/evaluate-with-luna))
   - **DeepEval's pytest ergonomics** — `assert_test()` / `deepeval test run` is the developer feel to match; Tracely's gate should feel like a test runner, not a dashboard. ([DeepEval CI](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd))
   - **Braintrust's GitHub Action UX** — PR comments with per-case score deltas + git-metadata-linked experiments are the proven gate UX. ([Braintrust CI](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025))
   - **Patronus Percival's failure taxonomy** — 20+ agentic failure modes (reasoning/execution/planning/domain) is a ready-made starting ontology for Tracely's Failure Cluster labels. ([Patronus Agents](https://www.patronus.ai/agents))
   - **Phoenix/OpenInference OTel ingestion** — the OTLP + OpenInference convention is how you stay framework-agnostic (LangGraph, Agno, OpenAI Agents SDK, custom). Build ingestion on this, not a proprietary SDK. ([Phoenix](https://arize.com/docs/phoenix))

**4. Ignore these (distractions for the thesis):** prompt management / prompt IDEs (Maxim Playground++, Humanloop's old core), dataset-curation-as-the-product, benchmark registries (OpenAI Evals registry), and "Datadog-style" metric dashboards. They are adjacent revenue for incumbents but orthogonal to "production trace → regression test → CI gate." The reader has correctly excluded them. **(synthesis)**

**5. Sharpest defensible white space (one sentence):** *A trace-native, agent-first CI/CD platform where production traces are auto-clustered into failure suites and replayed as multi-level trajectory regression tests that gate the pull request changing an agent version* — is currently owned by no one; Braintrust is closest but is dataset-first, manual, and prompt-app-centric, and OpenAI validates the sequence but ships no gate and only for its own SDK. **(synthesis)**

---

### Source index

- Braintrust — [Evaluate](https://www.braintrust.dev/docs/evaluate), [failures→regression tests](https://www.braintrust.dev/articles/turn-llm-production-failures-into-regression-tests), [CI/CD tools 2026](https://www.braintrust.dev/articles/best-ai-evals-tools-cicd-2025), [Series A (a16z)](https://a16z.com/announcement/investing-in-braintrust/)
- LangSmith — [eval concepts](https://docs.langchain.com/langsmith/evaluation-concepts), [eval product](https://www.langchain.com/langsmith/evaluation), [pytest](https://docs.langchain.com/langsmith/pytest), [pytest/vitest launch](https://blog.langchain.com/pytest-and-vitest-for-langsmith-evals/), [agentevals](https://github.com/langchain-ai/agentevals)
- Arize Phoenix — [What is Phoenix](https://arize.com/docs/phoenix), [datasets & experiments](https://arize.com/docs/phoenix/datasets-and-experiments/overview-datasets), [GitHub](https://github.com/arize-ai/phoenix), [AX CI/CD](https://arize.com/docs/ax/develop/datasets-and-experiments/ci-cd-for-automated-experiments)
- Galileo — [Evaluate profile](https://agentsindex.ai/galileo-ai-evaluate), [Luna-2](https://docs.galileo.ai/how-to-guides/luna/evaluate-with-luna/evaluate-with-luna), [CI fundamentals](https://galileo.ai/blog/continuous-integration-ci-ai-fundamentals), [experiments](https://v2docs.galileo.ai/sdk-api/experiments/running-experiments)
- Maxim — [overview](https://www.getmaxim.ai/docs/introduction/overview), [agent simulation](https://www.getmaxim.ai/products/agent-simulation-evaluation), [site](https://www.getmaxim.ai/), [Bifrost](https://github.com/maximhq/bifrost)
- Patronus — [evaluators](https://www.patronus.ai/blog/patronus-evaluators), [features](https://www.patronus.ai/product/features), [Agents/Percival](https://www.patronus.ai/agents), [docs](https://docs.patronus.ai/docs)
- DeepEval / Confident AI — [GitHub](https://github.com/confident-ai/deepeval), [intro](https://deepeval.com/docs/introduction), [component-level](https://deepeval.com/docs/evaluation-component-level-llm-evals), [CI/CD](https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd)
- OpenAI — [Evals repo](https://github.com/openai/evals), [trace grading](https://developers.openai.com/api/docs/guides/trace-grading), [agent evals](https://developers.openai.com/api/docs/guides/agent-evals), [improvement loop](https://developers.openai.com/cookbook/examples/agents_sdk/agent_improvement_loop)
- Adjacent — [aevals.ai](https://aevals.ai/), [Humanloop→Anthropic (TechCrunch)](https://techcrunch.com/2025/08/13/anthropic-nabs-humanloop-team-as-competition-for-enterprise-ai-talent-heats-up/)
