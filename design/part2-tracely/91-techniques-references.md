# Techniques Reference: Trajectory Evaluation, Failure Clustering, and Root-Cause / Test Generation

> Research brief for Tracely (trace-native CI/CD for AI agents). This document catalogs **established, implementable techniques** for the three engineering problems at the heart of the "Production Trace → Failure Detection → Regression Test → CI/CD Gate" pipeline. Every load-bearing claim is cited inline. Sections labeled **[Synthesis]** are my interpretation/recommendation, not a sourced fact.

---

## TL;DR

- **Trajectory evaluation is a solved-enough problem to build on.** The field has converged on a small set of metrics: **exact-match / inclusion over the tool sequence**, **tool-args correctness** (schema/format/value checks), and an **LLM-judge "trajectory-satisfy"** fallback when no gold trace exists. TRAJECT-Bench formalizes these ([arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1)); LangChain's open-source `agentevals` package ships them as code with four match modes — `strict / unordered / subset / superset` — plus configurable arg matching ([github.com/langchain-ai/agentevals](https://github.com/langchain-ai/agentevals)). **Steal `agentevals`' match-mode taxonomy wholesale** — it is exactly the vocabulary a regression-test gate needs.
- **Exact-match is too brittle alone** because agents reach valid outcomes via different paths; the established practice is **multiple reference trajectories + fuzzy/LLM judging for free-text, and order-relaxed structural matching for tool calls** ([galileo.ai](https://galileo.ai/blog/agent-evaluation-framework-metrics-rubrics-benchmarks)).
- **LLM-as-judge works (~80% human agreement on the MT-Bench task) but is biased.** Documented, reproducible failure modes: **position bias** (swapping answer order flips judgments, >10% accuracy swing on code), **verbosity bias**, **self-preference / family bias**, and **overconfident miscalibration** ([arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685), [adaline.ai](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias)). Mitigations are known and cheap: randomize position / swap-and-average, reference-guided grading, cross-provider judge, human spot-check calibration.
- **Failure clustering at scale = embeddings → dim-reduction → density clustering → label.** The canonical stack is **sentence embeddings → UMAP → HDBSCAN → c-TF-IDF labels** (this *is* BERTopic) ([maartengr.github.io/BERTopic](https://maartengr.github.io/BERTopic/algorithm/algorithm.html)). For the **structured-log / stack-trace** half, use **Drain3** — an online fixed-depth-tree log-template miner that runs streaming with persistence to Kafka/Redis/file ([github.com/logpai/Drain3](https://github.com/logpai/Drain3)).
- **Dedup near-duplicate failures with MinHash + LSH** (the same technique used to dedup LLM training corpora at trillion scale) before clustering, so one flaky bug doesn't dominate a cluster ([milvus.io](https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md)).
- **Pick representatives = medoid (closest to centroid) + a diversity term.** Cluster-based representative selection and coreset/k-center-greedy methods are the standard ([link.springer.com](https://link.springer.com/chapter/10.1007/978-3-540-24775-3_46), [arxiv.org/html/2505.17799v1](https://arxiv.org/html/2505.17799v1)).
- **Auto-generating regression tests from failures is real and benchmarked.** The pattern is **understand → generate candidate test → execute → refine on feedback** (LIBRO, Issue2Test). State of the art reproduces ~**30–33% of real issues** as fail-to-pass tests on SWT-bench-lite ([arxiv.org/abs/2503.16320](https://arxiv.org/abs/2503.16320)). For Tracely the input is richer than a text issue — it's a full trace — so the achievable rate should be higher.
- **Root-cause analysis from traces is an active research area, not a commodity.** The credible direction unifies **traces + logs + metrics into a causal/temporal graph** and reasons over it (event-graph RCA, multimodal LLM-agent RCA like TAMO) ([arxiv.org/html/2408.00803v1](https://arxiv.org/html/2408.00803v1), [arxiv.org/html/2504.20462v1](https://arxiv.org/html/2504.20462v1)). For agents specifically, the **"first failing step"** heuristic (label the earliest error; upstream errors cause downstream noise) is the cheap, high-leverage starting point ([hamel.dev](https://hamel.dev/blog/posts/evals-faq/why-is-error-analysis-so-important-in-llm-evals-and-how-is-it-performed.html)).

---

## 1. Agent Trajectory Evaluation

### 1.1 The metric vocabulary (well-established)

The current consensus, crystallized by **TRAJECT-Bench** (a trajectory-aware tool-use benchmark), is that evaluating only the final answer "overlooks the detailed tool usage trajectory, i.e., whether tools are selected, parameterized, and ordered correctly" ([arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1)). It defines four metrics that map cleanly onto Tracely's needs:

| Metric | What it measures | Computation |
|---|---|---|
| **Trajectory Exact-Match (EM)** | Did the predicted *tool sequence* (names only) match ground truth exactly? | Ordered-set comparison of tool names |
| **Trajectory Inclusion** | What proportion of the required tools appear in the prediction (order-independent)? | `|gold ∩ pred| / |gold|` |
| **Tool-Usage (Usage)** | Are predicted tool *parameters* correct? | Schema-constraint, format, and value checks against gold args |
| **Trajectory-Satisfy** | When no gold trace exists, how well does the predicted trajectory solve the query? | **LLM-judge** (Claude-4 default) score |

Source: [arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1).

A broader practitioner list (Galileo) adds **step-level precision/recall, in-order vs any-order matching to a reference plan, tool-selection accuracy, parameter correctness, convergence, and path efficiency** ([galileo.ai](https://galileo.ai/blog/agent-evaluation-framework-metrics-rubrics-benchmarks)).

### 1.2 The reference implementation to steal: LangChain `agentevals`

LangChain's open-source [`agentevals`](https://github.com/langchain-ai/agentevals) package ([PyPI](https://pypi.org/project/agentevals/)) is the most directly reusable artifact found. It expects trajectories as **OpenAI-format message dicts** (`role`, `content`, `tool_calls[].function.name/arguments`) or LangChain `BaseMessage` objects, and exposes `create_trajectory_match_evaluator` with these knobs ([docs.langchain.com/langsmith/trajectory-evals](https://docs.langchain.com/langsmith/trajectory-evals), [github.com/langchain-ai/agentevals](https://github.com/langchain-ai/agentevals)):

**`trajectory_match_mode`** (the core decision a regression gate has to make):
- **`strict`** — same messages, same order, same tool calls (but *allows* differences in message *content*).
- **`unordered`** — same tool calls in *any* order. ("Allow flexibility in how an agent obtains the proper information, but still care that all info was retrieved.")
- **`subset`** — actual called *no extra* tools beyond the reference set.
- **`superset`** — reference tools were *all* called; extra calls are acceptable.

**`tool_args_match_mode`**: `exact` (default, all args match), `ignore` (any two calls to the same tool are equal), or `subset`/`superset` (partial arg overlap). Plus **`tool_args_match_overrides`**: per-tool dict mapping a tool name to a mode, a list of fields requiring exact match, or a **user-defined comparator function** ([github.com/langchain-ai/agentevals](https://github.com/langchain-ai/agentevals)).

**LLM-judge variant**: `create_trajectory_llm_as_judge(prompt, model, continuous=bool, few_shot_examples=[...])` returns `{key, score, comment}` and judges the trajectory with or without a `{reference_outputs}` template var ([github.com/langchain-ai/agentevals](https://github.com/langchain-ai/agentevals)).

LangSmith productizes the same primitives plus **multi-turn evals** and an "Insights Agent" for surfacing patterns ([blog.langchain.com](https://blog.langchain.com/insights-agent-multiturn-evals-langsmith/)).

### 1.3 Known failure modes the evaluator must catch

TRAJECT-Bench's empirical analysis names four dominant agent failure modes — directly useful as a built-in failure taxonomy ([arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1)):
1. **Similar-tool confusion** — conflating tools with overlapping capabilities (Spotify Search vs YouTube Music Search). Weak discrimination between semantically similar options.
2. **Parameter-blind selection** — choosing a tool by description match while ignoring its input/output parameter requirements.
3. **Redundant tool calling** — unnecessary calls, either conservative-but-unhelpful or hallucinated/unrelated.
4. **Hard-query intent misinterpretation** — indirect phrasing causes systematic mis-selection.

Empirically, **Inclusion consistently exceeds EM** (especially for weaker models): agents can identify the *relevant* tools but fail to recover the *exact* set/order ([arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1)). **[Synthesis]** This is the single most important design implication for trajectory gates: default to **order-relaxed (`unordered`/`superset`) matching with a separate, explicit order-sensitivity flag**, because strict ordering will produce false regressions on legitimately re-ordered-but-correct runs.

For **multi-agent** systems, the **MAST** taxonomy (14 failure modes in 3 buckets) is the reference: **specification/system-design issues ≈ 41.8%**, **inter-agent misalignment / coordination ≈ 36.9%**, **task verification gaps ≈ 21.3%**, built from 1600+ annotated traces across 7 frameworks with high inter-annotator agreement (κ = 0.88) ([arxiv.org/abs/2503.13657](https://arxiv.org/abs/2503.13657), [github.com/multi-agent-systems-failure-taxonomy/MAST](https://github.com/multi-agent-systems-failure-taxonomy/MAST)). **[Synthesis]** MAST is the closest thing to a ready-made label set for multi-agent failure clusters — adopt its three top-level buckets as default cluster categories.

### 1.4 LLM-as-judge over trajectories — and its reliability pitfalls

**It works, with caveats.** The foundational result (MT-Bench / Chatbot Arena) is that strong LLM judges like GPT-4 reach **>80% agreement with human preferences — the same level humans agree with each other** ([arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685)). But that 80% is on *multi-turn open-ended chat*; agreement is **higher on closed tasks** (factual QA, deterministic code checks) and **lower where humans themselves disagree** (creative/opinion) ([arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685)).

**G-Eval** is the standard recipe for the judge prompt itself: **generate chain-of-thought evaluation steps, then score via a form-filling paradigm**; it reaches Spearman 0.514 with humans on summarization, beating prior methods ([arxiv.org/pdf/2303.16634](https://arxiv.org/pdf/2303.16634), [aclanthology.org/2023.emnlp-main.153](https://aclanthology.org/2023.emnlp-main.153/)).

**Documented, reproducible biases** (this is the "known reliability pitfalls" the brief asks for):
- **Position bias** — judge favors responses by presentation order; swapping positions *flips* GPT-4's judgment, and in pairwise code judging order-swap causes **>10% accuracy shifts**. Judge-model choice has higher impact on positional bias than task complexity or output length ([adaline.ai](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias)).
- **Verbosity bias** — judges prefer longer/more-fluent answers regardless of substance, an artifact of pretraining + RLHF ([adaline.ai](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias), [sebastiansigl.com](https://www.sebastiansigl.com/blog/llm-judge-biases-and-how-to-fix-them/)).
- **Self-preference & family bias** — models (e.g. GPT-4o, Claude 3.5 Sonnet) score their own / same-provider outputs higher ([researchgate.net (Self-Preference Bias)](https://www.researchgate.net/publication/385353198_Self-Preference_Bias_in_LLM-as-a-Judge), [adaline.ai](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias)).
- **Overconfident miscalibration** — judges express high confidence even when wrong; scalar scoring schemes encourage false precision ([deepchecks.com](https://deepchecks.com/llm-judge-calibration-automated-issues/)).
- **Complexity degradation** — even when Traj-Satisfy correlates strongly with EM on *simple* tasks (Claude-4: 8.549↔0.846), the correlation degrades on *hard* tasks (4.882↔0.445), so judge reliability drops exactly where it matters most ([arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1)).

**Mitigations with research backing** ([adaline.ai](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias), [deepchecks.com](https://deepchecks.com/llm-judge-calibration-automated-issues/), [cameronrwolfe.substack.com](https://cameronrwolfe.substack.com/p/llm-as-a-judge)):
1. **Randomize / swap-and-average positions** in pairwise comparisons.
2. **Reference-guided grading** when a correct reference exists (turns an open task into a near-closed one).
3. **Cross-provider judge** (judge from a different family than the generator).
4. **Calibrate against human spot-checks** for *your* domain; prefer binary/low-cardinality rubrics over fine scalar scores.
5. **Meta-judge over debate** — multi-model debate amplifies bias.

### 1.5 So what for Tracely — trajectory evaluation

- **[Synthesis] Build the evaluator around the `agentevals` match-mode taxonomy** (`strict/unordered/subset/superset` × `exact/ignore/subset/superset` args). It is the right abstraction and it's MIT-licensed Python you can fork. Map it onto Tracely's entities: a `Step`/`Tool Call` stream *is* the trajectory; a saved "good" Agent Run *is* the reference trajectory.
- **A regression test = (input trace prefix) + (reference trajectory + match mode) + (optional LLM-judge rubric).** This is the concrete shape of Tracely's core artifact, and it's derivable directly from a production trace — no dataset required.
- **Make order-sensitivity a per-test setting, defaulting to relaxed.** Inclusion > EM empirically; strict ordering manufactures false regressions.
- **Tier the judge:** deterministic structural match (tool names/args) first — cheap, unbiased, CI-friendly — and reserve LLM-judge for free-text turn/conversation quality where structure can't decide. Always store the judge's CoT (`comment`) for auditability.
- **Bake in bias mitigations as defaults** (position swap, cross-provider judge, reference-guided when a gold trace exists). These are the difference between a trustworthy gate and a flaky one.
- **Ship MAST's 3 buckets + TRAJECT-Bench's 4 tool-failure modes as the seed failure taxonomy** so clusters get human-legible names from day one.

---

## 2. Failure Clustering at Scale

The problem: turn millions of raw failing traces into a small, deduplicated, human-reviewable set of **Failure Clusters**, each with a representative example and a label. There are two complementary embeddings-vs-templates approaches; production systems use both.

### 2.1 Embedding → reduce → density-cluster → label (the BERTopic stack)

The dominant pattern for *semantic* clustering of free text (error messages, model outputs, user turns) is a 4-stage pipeline that **BERTopic** packages end-to-end ([maartengr.github.io/BERTopic/algorithm](https://maartengr.github.io/BERTopic/algorithm/algorithm.html), [github.com/MaartenGr/BERTopic](https://github.com/MaartenGr/BERTopic)):

1. **Embed** with sentence-transformers (context-aware; groups same-meaning/different-words text).
2. **Reduce dimensionality with UMAP.** Critical: *embeddings cannot be clustered directly in high dimensions because distance metrics are uninformative there*; UMAP embeds into a low-dim manifold preserving local neighborhoods ([futureagi.com](https://futureagi.com/blog/what-is-error-analysis-llm-2026), [maartengr.github.io/BERTopic/algorithm](https://maartengr.github.io/BERTopic/algorithm/algorithm.html)).
3. **Cluster with HDBSCAN** — density-based, **auto-discovers the number of clusters**, and **marks rare/outlier points as noise** (no `k` to guess) ([maartengr.github.io/BERTopic/algorithm](https://maartengr.github.io/BERTopic/algorithm/algorithm.html)). HDBSCAN "runs DBSCAN at every density threshold simultaneously," so it adapts to clusters of *different densities* — exactly the case for failure data where one bug is huge and another is tiny ([letsdatascience.com](https://letsdatascience.com/blog/mastering-hdbscan-clustering-variable-density-data-made-easy)).
4. **Label with c-TF-IDF** — treat each cluster as one concatenated document, run class-based TF-IDF across clusters to extract the most distinctive terms per cluster ([maartengr.github.io/BERTopic/algorithm](https://maartengr.github.io/BERTopic/algorithm/algorithm.html)).

**Algorithm tradeoffs** (decision-useful):
- **HDBSCAN** — best default for failure data: no `k`, handles variable density, emits noise/outliers (useful — outliers are *novel* failures). Costs: **memory blows up on large datasets (~500k points reported OOM)** ([github.com/scikit-learn-contrib/hdbscan#345](https://github.com/scikit-learn-contrib/hdbscan/issues/345)); some GPU impls only support L2 distance ([github.com/rapidsai/cuml#5414](https://github.com/rapidsai/cuml/issues/5414)). Mitigate with UMAP first and/or GPU HDBSCAN.
- **k-means** — fast, scalable, but needs `k` up front and assumes roughly spherical equal-density clusters → poor fit for text embeddings ([letsdatascience.com](https://letsdatascience.com/blog/mastering-hdbscan-clustering-variable-density-data-made-easy)). Use only after dim-reduction and when you accept fixed `k` (e.g. dashboard top-N).
- **Agglomerative (hierarchical)** — gives a dendrogram (merge clusters at chosen granularity), no `k` if you cut by distance; O(n²) memory limits raw scale → run on cluster medoids or a sample.

**For safety/abuse-style monitoring specifically**, IEEE's writeup confirms **BERTopic over BERT embeddings** as a working production approach to monitor LLM safety failures ([computer.org](https://www.computer.org/publications/tech-news/community-voices/llm-safety)).

### 2.2 Log-template / stack-trace clustering: Drain3

For *structured* failure signal — exceptions, stack traces, tool-error strings, framework logs — embeddings are overkill. The standard is **Drain3**, "a robust streaming log template miner" ([github.com/logpai/Drain3](https://github.com/logpai/Drain3)), originally from the **Drain** paper ("An Online Log Parsing Approach with Fixed Depth Tree," He et al.) ([netman.aiops.org/.../phe_icws2017_drain.pdf](https://netman.aiops.org/~peidan/ANM2023/6.LogAnomalyDetection/phe_icws2017_drain.pdf)). Mechanics ([github.com/logpai/Drain3](https://github.com/logpai/Drain3), [deepwiki.com/logpai/Drain3](https://deepwiki.com/logpai/Drain3/3-drain-algorithm)):

- **Fixed-depth parse tree** (default depth 4) keeps search fast and the tree balanced; per message: tokenize → navigate tree by token-count + leading tokens → similarity-match candidates → create/update a template cluster.
- **Similarity threshold `sim_th`** (default 0.4): below this fraction of matching tokens, a new cluster is spawned.
- **Masking/preprocessing** with regex (IP, NUM, HEX, etc.) replaces variable parts with `<*>` *before* mining → better generalization.
- **Streaming & online**: `add_log_message()` updates templates continuously, no batch step. **Persistence** to Kafka / Redis / file / memory; snapshots on cluster creation/change or interval.
- **Bounded memory**: `max_clusters` with **LRU eviction**, `max_children` per node.
- **Limitations**: degrades on extreme-cardinality logs; LRU may evict important rare patterns; accuracy depends on good masking regex ([github.com/logpai/Drain3](https://github.com/logpai/Drain3)).

**[Synthesis]** Drain3's streaming + bounded-memory + pluggable-persistence design is a near-perfect fit for Tracely's ingestion path: run it inline on every trace's error/log fields to assign a `template_id` *at ingest time*, cheaply, before any embedding work. The `template_id` becomes a free first-pass clustering key and a dedup key.

### 2.3 Online / streaming clustering (cluster as traces arrive)

Because Tracely ingests a continuous trace stream, batch re-clustering everything is wasteful. The mature **stream-clustering** algorithms split work into an **online micro-cluster summarization phase** + an **offline macro-cluster phase** ([en.wikipedia.org/wiki/Data_stream_clustering](https://en.wikipedia.org/wiki/Data_stream_clustering)):
- **CluStream** — maintains micro-clusters (temporal Cluster-Feature vectors) online, generates final clusters offline; needs `k`, assumes spherical clusters ([riverml.xyz/.../CluStream](https://riverml.xyz/dev/api/cluster/CluStream/)).
- **DenStream / DBSTREAM** — density-based for *evolving* streams; DBSTREAM keeps a **shared-density graph** between micro-clusters and reconstructs clusters by density connectivity ([riverml.xyz/.../DenStream](https://riverml.xyz/dev/api/cluster/DenStream/), [deepwiki.com/online-ml/river](https://deepwiki.com/online-ml/river/6-clustering)).
- **`river`** (Python) ships incremental `KMeans`, `DenStream`, `CluStream` ready to use ([deepwiki.com/online-ml/river](https://deepwiki.com/online-ml/river/6-clustering)). MOA is the JVM equivalent ([moa.cms.waikato.ac.nz](https://moa.cms.waikato.ac.nz/details/stream-clustering/)).

**[Synthesis]** A pragmatic two-tier design: **online micro-clustering (Drain3 templates + DenStream over embeddings) for live grouping**, then **periodic offline BERTopic/HDBSCAN re-clustering** (nightly) for high-quality, stable cluster boundaries and labels. This mirrors the online/offline split these algorithms already assume.

### 2.4 Deduplicating near-duplicate failures: MinHash + LSH

Before/within clustering, collapse near-identical failures (same bug, slightly different IDs/timestamps) so one noisy failure doesn't swamp a cluster or inflate counts. The industry-standard scalable technique is **MinHash + LSH** ([mbrenndoerfer.com](https://mbrenndoerfer.com/writing/minhash-algorithm-jaccard-similarity-lsh-deduplication), [milvus.io](https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md)):
- **MinHash** compresses each document into a compact signature approximating **Jaccard similarity**.
- **LSH banding** splits signatures into bands/rows; docs sharing a band become candidate pairs → drastically fewer comparisons. Two-stage: **coarse LSH filter → fine exact-Jaccard verify** ([mbrenndoerfer.com](https://mbrenndoerfer.com/writing/minhash-algorithm-jaccard-similarity-lsh-deduplication)).
- This is the *same* method used to dedup C4, RefinedWeb, RedPajama at LLM-training scale ([mbrenndoerfer.com](https://mbrenndoerfer.com/writing/minhash-algorithm-jaccard-similarity-lsh-deduplication)); scales to billions of docs, with newer variants like **LSHBloom** giving 12× throughput over standard MinHashLSH ([arxiv.org/pdf/2411.04257](https://arxiv.org/pdf/2411.04257)). `datasketch` is the common Python lib; Milvus offers a native `MINHASH_LSH` index ([milvus.io](https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md)).

**[Synthesis]** For Tracely, MinHash-LSH over the normalized error template + key trajectory features gives a fast "is this the same failure we've already seen?" check — the basis for **failure de-dup, occurrence counting, and 'first seen / last seen' on a Failure Cluster** without an LLM in the loop.

### 2.5 Picking representatives + the human-in-the-loop methodology

**Representative selection**: the standard cluster-based method is "select from each cluster the most representative example — the one **closest to the cluster's centroid** (medoid)" ([link.springer.com](https://link.springer.com/chapter/10.1007/978-3-540-24775-3_46)). For a *diverse* sample (not just the center), use **coreset / k-center-greedy / Determinantal Point Process (DPP)** selection ([arxiv.org/html/2505.17799v1](https://arxiv.org/html/2505.17799v1), [arxiv.org/pdf/1901.05954](https://arxiv.org/pdf/1901.05954)). Multi-criteria active-learning frameworks combine **uncertainty + representativeness + diversity** ([pmc.ncbi.nlm.nih.gov/.../PMC4144157](https://pmc.ncbi.nlm.nih.gov/articles/PMC4144157/)). **[Synthesis]** Per Failure Cluster, surface **the medoid (canonical example) + 2–3 diverse boundary cases** so a human sees both the typical failure and its variants when deciding whether to promote it to a regression test.

**Don't fully automate the labeling.** The Husain/Shankar "error analysis" methodology (widely adopted in LLM-eval practice) is explicit ([hamel.dev](https://hamel.dev/blog/posts/evals-faq/why-is-error-analysis-so-important-in-llm-evals-and-how-is-it-performed.html)):
- **Open coding**: a human ("benevolent dictator") reads raw traces and writes free-form notes — *you can't outsource this to an LLM because it lacks your tribal knowledge.*
- **Axial coding**: group notes into a **failure taxonomy**; after **30–50 hand-coded traces**, an LLM can *propose* groupings but you review/refine.
- **Review ≥100 traces**; **note the *first* failure in a trace** because upstream errors cause downstream ones.

**[Synthesis]** This maps directly onto Tracely UX: automated clustering does the heavy lifting (the "axial coding" grouping), but the product must keep a human in the loop for naming/confirming clusters and promoting them to tests. The "first failure" rule is also the bridge to root-cause analysis (§3).

### 2.6 So what for Tracely — failure clustering

- **[Synthesis] Two-stage clustering pipeline**: (a) **ingest-time**: Drain3 template-ID + MinHash-LSH dedup → cheap online grouping and occurrence counting; (b) **batch**: embeddings → UMAP → HDBSCAN → c-TF-IDF (BERTopic) for high-quality semantic Failure Clusters with auto-labels.
- **HDBSCAN is the right default clusterer** (no `k`, variable density, noise=novel-failures) — just always reduce with UMAP first and watch memory past ~hundreds-of-thousands of points.
- **Each Failure Cluster's representative = medoid + diverse variants**; this is what gets promoted into Evaluation Cases.
- **Keep the human in the loop for labels** (open/axial coding); use the LLM only to *propose* cluster names. Ship MAST + TRAJECT-Bench taxonomies as priors.
- **Outliers (HDBSCAN noise) are a feature** — they're candidate *novel* failures / new regressions and deserve their own surfacing.

---

## 3. Root-Cause Analysis & Auto-Generated Test Cases

### 3.1 Root-cause analysis from traces/logs

This is the **least commoditized** of the three areas — it's active research, and a founding engineer should treat heavy automated RCA as a later-stage bet, not v1. The credible directions:

- **Unify traces + logs + metrics into a temporal/causal representation.** A comprehensive survey of RCA in micro-services frames the core challenge as fault propagation across services + high-dimensional multimodal telemetry, and surveys methods that build causality from this data ([arxiv.org/html/2408.00803v1](https://arxiv.org/html/2408.00803v1)).
- **Event-graph RCA**: construct a real-time causality graph using heterogeneous events (from metrics/logs) as nodes and infer causal edges ([arxiv.org/html/2408.00803v1](https://arxiv.org/html/2408.00803v1)). For agents, the analog is the **trace/span tree itself** — it already encodes the call topology and parent-child causality, so Tracely gets the "graph" for free.
- **LLM-agent RCA over multimodal data**: **TAMO** is a tool-assisted LLM agent that does fine-grained RCA over multi-modality observation data (logs, traces, metrics) ([arxiv.org/html/2504.20462v1](https://arxiv.org/html/2504.20462v1)). **RC-LLM** reframes RCA as **deep temporal causal reasoning**, hierarchically fusing trace/metric/log via a residual mechanism ([arxiv.org/html/2602.08804v1](https://arxiv.org/html/2602.08804v1)). Microsoft/industry reports confirm LLMs meaningfully **cut RCA time from hours to minutes** in incident response ([dzone.com](https://dzone.com/articles/llms-automated-root-cause-analysis-incident-response)), and there's an ACM-FSE study specifically on **LLM-based agents for RCA** ([dl.acm.org/doi/10.1145/3663529.3663841](https://dl.acm.org/doi/10.1145/3663529.3663841)).
- **The cheap, high-leverage v1 heuristic**: **find the first failing step.** Because upstream errors cause downstream errors, labeling the *earliest* error in a trace localizes root cause most of the time ([hamel.dev](https://hamel.dev/blog/posts/evals-faq/why-is-error-analysis-so-important-in-llm-evals-and-how-is-it-performed.html)). For multi-agent, MAST's distribution tells you *where* to look first: ~42% of failures are **specification** issues and ~37% **inter-agent coordination/misalignment** ([arxiv.org/abs/2503.13657](https://arxiv.org/abs/2503.13657)).

**[Synthesis]** Tracely's trace is structurally richer than the log piles these RCA papers wrestle with — it already has the span tree (causality topology), the LLM I/O at each step, and the tool args/results. So the pragmatic RCA stack is: **(1) deterministic first-failing-step localization on the span tree → (2) LLM "RCA agent" that reads the localized sub-trace + its inputs and proposes a root-cause hypothesis + a human-readable explanation**, citing the specific span. Don't try to do cross-service causal-graph inference at the start; the span tree is your causal graph.

### 3.2 Auto-generating test cases from failures (well-established pattern)

This is the payoff of the whole pipeline, and it's a benchmarked research area. The universal pattern is **generate-and-validate with an execution-feedback refinement loop**:

- **LIBRO** — uses an LLM to generate bug-reproducing tests from *bug reports*; on **Defects4J it reproduces 33% (251/750)** of cases, using **feedback loops and stack traces** to refine ([arxiv.org/pdf/2209.11515](https://arxiv.org/pdf/2209.11515)).
- **Issue2Test** — three phases: **Understanding** (extract context/repro-steps/expected behavior) → **Generation** (candidate tests) → **Refinement loop** (execute; on failure, feed execution output back to revise). Result: **reproduces 30.4% of SWT-bench-lite issues, +40.1% relative over best prior** (one revision reports 32.9% / +16.3%); a Fail-to-Pass test **fails on the buggy code, passes after the fix** ([arxiv.org/abs/2503.16320](https://arxiv.org/abs/2503.16320), [arxiv.org/html/2503.16320v4](https://arxiv.org/html/2503.16320v4)). Prior **Auto-TDD** got 21.7% on the same set.
- **SWT-bench** is the standard benchmark for "generate a test that validates a real bug-fix" ([swtbench.com](https://swtbench.com/), [proceedings.neurips.cc/.../2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/94f093b41fc2666376fb1f667fe282f3-Paper-Conference.pdf)).
- **TestART** and **ChatUniTest** generalize the loop as **co-evolution of generation + repair** / **generation-validation-repair**, with TestART reporting +18% pass-rate and +20% coverage over baselines ([arxiv.org/html/2408.03095v6](https://arxiv.org/html/2408.03095v6)).
- **BRMiner** mines *literal inputs* from bug reports to make generated tests more relevant ([arxiv.org/html/2312.14898](https://arxiv.org/html/2312.14898)) — the analog for Tracely is mining the *exact inputs/tool args* straight out of the failing trace.

**The Fail-to-Pass definition is the key contract**: a good generated test **fails on the buggy version and passes on the fixed version** ([arxiv.org/abs/2503.16320](https://arxiv.org/abs/2503.16320)). **[Synthesis]** For Tracely this generalizes to: *a regression test derived from a failing trace must (a) fail when replayed against the failing agent version, and (b) be expected to pass against the fixed version.* That's the validation gate for "is this a real, non-flaky regression test?"

### 3.3 So what for Tracely — RCA & test generation

- **[Synthesis] RCA v1 = first-failing-step localization on the span tree + an LLM explanation agent.** The trace *is* the causal graph; don't reinvent micro-service causal inference. Use MAST's distribution to prioritize where to look in multi-agent traces.
- **Test generation is the killer feature and it's a known recipe**: **understand the failing trace → synthesize a regression test (input = the trace's actual inputs/tool args, à la BRMiner) → validate via the Fail-to-Pass contract (replay must fail on the broken version) → refine on execution feedback (LIBRO/Issue2Test loop).**
- **Set realistic expectations**: SoTA reproduces ~30–33% of *text-issue* failures. Tracely starts from a **full trace**, not a terse text report — strictly more signal (exact inputs, tool args, intermediate state) — so the achievable auto-reproduction rate should be meaningfully higher. **Frame auto-generated tests as candidate drafts a human confirms**, not fully autonomous test authoring.
- **The whole thing only works because the trace is the source of truth**: trajectory metrics (§1) detect the failure, clustering (§2) groups + dedups + picks the representative, RCA localizes it, and test-gen turns the localized failing trace into a Fail-to-Pass regression test that becomes a CI/CD gate. Every step is *derived from the trace* — which is exactly Tracely's thesis.

---

## Appendix: Source index (primary sources in bold)

**Trajectory evaluation**
- **TRAJECT-Bench** — [arxiv.org/html/2510.04550v1](https://arxiv.org/html/2510.04550v1) | [pdf](https://arxiv.org/pdf/2510.04550)
- **`agentevals` (LangChain)** — [github.com/langchain-ai/agentevals](https://github.com/langchain-ai/agentevals) | [PyPI](https://pypi.org/project/agentevals/) | [docs](https://docs.langchain.com/langsmith/trajectory-evals)
- LangSmith multi-turn/Insights — [blog.langchain.com](https://blog.langchain.com/insights-agent-multiturn-evals-langsmith/)
- Agent eval framework (metrics) — [galileo.ai](https://galileo.ai/blog/agent-evaluation-framework-metrics-rubrics-benchmarks)
- **MAST multi-agent failure taxonomy** — [arxiv.org/abs/2503.13657](https://arxiv.org/abs/2503.13657) | [github](https://github.com/multi-agent-systems-failure-taxonomy/MAST)

**LLM-as-judge**
- **MT-Bench / Chatbot Arena (80% agreement)** — [arxiv.org/abs/2306.05685](https://arxiv.org/abs/2306.05685)
- **G-Eval** — [arxiv.org/pdf/2303.16634](https://arxiv.org/pdf/2303.16634) | [ACL](https://aclanthology.org/2023.emnlp-main.153/)
- Bias survey/mitigations — [adaline.ai](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias) | [deepchecks.com](https://deepchecks.com/llm-judge-calibration-automated-issues/) | [Self-Preference Bias](https://www.researchgate.net/publication/385353198_Self-Preference_Bias_in_LLM-as-a-Judge) | [cameronrwolfe.substack.com](https://cameronrwolfe.substack.com/p/llm-as-a-judge)

**Failure clustering**
- **BERTopic** — [algorithm docs](https://maartengr.github.io/BERTopic/algorithm/algorithm.html) | [github](https://github.com/MaartenGr/BERTopic)
- **HDBSCAN** — [how it works](https://letsdatascience.com/blog/mastering-hdbscan-clustering-variable-density-data-made-easy) | [OOM issue #345](https://github.com/scikit-learn-contrib/hdbscan/issues/345) | [cuML L2-only #5414](https://github.com/rapidsai/cuml/issues/5414)
- **Drain / Drain3** — [github.com/logpai/Drain3](https://github.com/logpai/Drain3) | [paper](https://netman.aiops.org/~peidan/ANM2023/6.LogAnomalyDetection/phe_icws2017_drain.pdf) | [algorithm](https://deepwiki.com/logpai/Drain3/3-drain-algorithm)
- **Stream clustering (CluStream/DenStream/river)** — [Wikipedia](https://en.wikipedia.org/wiki/Data_stream_clustering) | [river DenStream](https://riverml.xyz/dev/api/cluster/DenStream/) | [river CluStream](https://riverml.xyz/dev/api/cluster/CluStream/) | [river clustering](https://deepwiki.com/online-ml/river/6-clustering)
- **MinHash + LSH dedup** — [explainer](https://mbrenndoerfer.com/writing/minhash-algorithm-jaccard-similarity-lsh-deduplication) | [Milvus](https://milvus.io/blog/minhash-lsh-in-milvus-the-secret-weapon-for-fighting-duplicates-in-llm-training-data.md) | [LSHBloom](https://arxiv.org/pdf/2411.04257)
- Representative/coreset selection — [cluster-centroid AL](https://link.springer.com/chapter/10.1007/978-3-540-24775-3_46) | [coreset survey](https://arxiv.org/html/2505.17799v1) | [diverse mini-batch AL](https://arxiv.org/pdf/1901.05954)
- **Error analysis methodology (Husain/Shankar)** — [hamel.dev](https://hamel.dev/blog/posts/evals-faq/why-is-error-analysis-so-important-in-llm-evals-and-how-is-it-performed.html)
- LLM safety monitoring via BERTopic — [computer.org](https://www.computer.org/publications/tech-news/community-voices/llm-safety)

**RCA & test generation**
- RCA survey (micro-services) — [arxiv.org/html/2408.00803v1](https://arxiv.org/html/2408.00803v1)
- **TAMO (tool-assisted LLM-agent RCA)** — [arxiv.org/html/2504.20462v1](https://arxiv.org/html/2504.20462v1)
- RC-LLM (temporal causal) — [arxiv.org/html/2602.08804v1](https://arxiv.org/html/2602.08804v1)
- LLM RCA in incident response — [dzone.com](https://dzone.com/articles/llms-automated-root-cause-analysis-incident-response) | [ACM FSE](https://dl.acm.org/doi/10.1145/3663529.3663841)
- **LIBRO (bug-repro tests)** — [arxiv.org/pdf/2209.11515](https://arxiv.org/pdf/2209.11515)
- **Issue2Test** — [arxiv.org/abs/2503.16320](https://arxiv.org/abs/2503.16320) | [html](https://arxiv.org/html/2503.16320v4)
- **SWT-bench** — [swtbench.com](https://swtbench.com/) | [NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/94f093b41fc2666376fb1f667fe282f3-Paper-Conference.pdf)
- TestART / co-evolution — [arxiv.org/html/2408.03095v6](https://arxiv.org/html/2408.03095v6)
- BRMiner (inputs from reports) — [arxiv.org/html/2312.14898](https://arxiv.org/html/2312.14898)
