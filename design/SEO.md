# SEO plan — tracely-ai.com

Working document. Phase 1 shipped 2026-08-11 (commit `93dff69`). Phase 2 (keyword research) completed
2026-08-12 against live DataForSEO data — **185 of 500 OpenSEO credits spent, 315 remaining.**

The strategy in one line: **a new domain cannot win head terms, so win the low-competition,
high-intent queries first, and let docs + comparison pages accumulate the authority that makes head
terms reachable later.**

---

## 0. Where we are

| | Status |
|---|---|
| Crawlable | ✅ `robots.txt` + `sitemap.xml` live, 200 in prod |
| Indexable | ✅ real `<title>`, meta description, canonical, JSON-LD (`SoftwareApplication` + `Organization`) |
| Shareable | ✅ generated 1200×630 OG card at `/opengraph-image` |
| Not-indexable-on-purpose | ✅ `noindex` on `(app)`, `(auth)`, `/share/[token]` |
| Docs | ✅ 11 pages went from **no `<title>` at all** to unique titles + descriptions + self-canonicals |
| Crawler routes past the auth wall | ✅ `middleware.ts` — they used to 307 to `/login` in `AUTH_MODE=local` |
| Keyword map | ✅ 36 keywords saved to the OpenSEO project, validated against live SERPs |
| Search Console | ⚠️ both properties verified; **not yet linked inside OpenSEO** |
| Measurable results | ❌ nothing yet — needs ~2 weeks of impressions |

---

## 1. What the data actually said

Three findings changed the plan. All three contradict something I assumed before pulling numbers.

### Finding 1 — the CI/regression angle has no search demand

This is the important one. Tracely's entire differentiator is the CI gate, and **nobody searches for
it**:

| Query | Volume |
|---|---|
| `llm regression testing` | 10/mo |
| `llm unit testing` | 10/mo |
| `llm golden dataset` | 10/mo |
| `llm ci cd`, `ci cd for llm`, `agent regression testing`, `prompt regression testing`, `automated llm testing`, `llm evaluation ci`, `detect llm regressions`, `agent evaluation without dataset` | **no measurable volume** |

The category Tracely invented does not exist in search yet. That doesn't make the product wrong —
it makes it *early*, which is a different problem. **Implication: target the terms that have demand
(observability, evaluation, judge), and use the CI gate as the differentiator that converts, not as
the phrase we optimize for.** Optimizing for "trace-native CI/CD" would be optimizing for zero.

### Finding 2 — Braintrust is already claiming our angle

Braintrust ranks #3 for `langfuse alternatives` with the title:

> "1. Braintrust: Best LLM evaluation platform with **CI/CD deployment blocking**"

A funded competitor is using our exact positioning in the exact SERP we'd target. The differentiator
has to get sharper than "we gate CI": it's **hermetic replay of real production failures with no
hand-authored dataset**. That combination is still unclaimed — but "we block bad PRs" is not.

### Finding 3 — the money is in observability/judge terms, and they're softer than expected

| Keyword | Vol/mo | KD | CPC | SERP reality |
|---|---|---|---|---|
| `llm as a judge` | **2,400** | 31 | $10.90 | Educational SERP. Langfuse only #8; Wikipedia #5, arxiv #3 |
| `llm evaluation` | **1,000** | **14** | $17.81 | Best volume-to-difficulty ratio in the whole set |
| `ai observability` | 880 | **13** | **$50.73** | Enormous commercial value per click |
| `llm observability` | 590 | 19 | $31.11 | Langfuse #4 |
| `langfuse vs langsmith` | 480 | **0** | $9.03 | Langfuse ranks #3 on their own comparison |
| `langsmith pricing` | 480 | 8 | $5.63 | Commercial intent |
| `test prompt` / `testing prompts` | 390 ea | **0** | $12.67 | Langfuse only #7/#9 — weakly held |
| `agent observability` | 320 | **13** | **$51.93** | Highest CPC in the set |
| `llm testing` | 210 | **4** | $10.54 | Langfuse #5 with a *blog post* — beatable |
| `llm observability tools` | 210 | 6 | $23.90 | Reddit #1; pure listicle SERP |
| `langsmith alternative` | 140 | **0** | $27.19 | |
| `langfuse alternatives` | 140 | **0** | **$36.73** | Every competitor has this page |
| `llm trace` | 140 | **0** | $15.68 | |
| `ai agent testing` | 90 | **1** | $25.17 | Mixed intent — see below |
| `langgraph testing` | 20 | **1** | $6.75 | competition 0.05 — nearly uncontested |

Note the CPCs. `agent observability` at $51.93 and `ai observability` at $50.73 mean advertisers are
paying ~$50 a click. Organic position there is worth real money.

**One SERP caveat:** `ai agent testing` is mixed-intent — half the page-1 results are about *AI
agents that do software testing* (UiPath, mabl, momentic), not testing your AI agents. Half that
volume is the wrong audience.

---

## 2. Phase 3 — the pages, revised

Rewritten against the data. Ordered by expected return per hour.

### Shipped

- **`/llm-evaluation`** — pillar guide. `llm evaluation` (1,000, KD 14) + `llm evals` (480) +
  `llm evaluation metrics` (260). `TechArticle` + `BreadcrumbList` + `FAQPage` schema.
- **`/llm-as-a-judge`** — deep dive, the category's biggest term. `llm as a judge` (2,400, KD 31) +
  `llm judge` (260) + `what is llm as a judge` (110). `TechArticle` + `BreadcrumbList` + `FAQPage`.
- **`/langfuse-alternatives`** — `langfuse alternatives` (140, KD 0, $36.73 CPC).
  `BreadcrumbList` + `FAQPage`.

Cluster structure: `/llm-evaluation` is the pillar, `/llm-as-a-judge` the deep dive on one method,
reciprocally linked so they reinforce rather than cannibalise each other.

Both are in `sitemap.ts`, the shell nav, the landing footer, and cross-link each other. `docs/pages/evaluations.mdx`
and `replay.mdx` link out to them, which is how docs authority reaches the marketing pages.

**Two rules for every future page on this site**, both learned the hard way:
1. Verify competitor claims against their *live docs*, never the design dossier — it's pinned to
   Langfuse v3.177.1 and they've shipped CI/CD experiments since.
2. Before listing something as a competitor's downside, check Tracely doesn't do the same thing.
   "Self-hosting means ClickHouse + Postgres + Redis + S3" shipped as a Langfuse trade-off before
   someone noticed that is exactly our stack.

### Tier 1 — do first

**`/llm-as-a-judge`** — target `llm as a judge` (2,400) + `llm judge` (260) + `llm as judge evaluation` (50)
The biggest term in the category and the SERP is definitional guides, not product pages — winnable
with a genuinely good one. Critically, Tracely has a differentiated sub-angle nobody else on page 1
covers well: **how do you know the judge is right?** Hamel Husain's post at #20 is about exactly
this (human-vs-judge agreement) and Tracely ships it as a feature (judge calibration). Lead with the
method, and the calibration section becomes the natural product mention.

**`/llm-evaluation`** — target `llm evaluation` (1,000, KD 14) + `llm evals` (480) + `llm evaluation metrics` (260)
Best volume-to-difficulty ratio available. A comprehensive guide page.

**`/vs/langfuse`** (targeting `langfuse alternatives` — **plural**, that's where the volume is) and
**`/vs/langsmith`** (`langsmith alternative` 140 + `langsmith pricing` 480 + `is langsmith open source` 90)
KD 0 on all of them. But be clear-eyed: **every competitor already has this page** — Braintrust,
Laminar, MLflow, Mirascope, Helicone, Confident AI, ZenML, Cekura, LangWatch, OpenObserve, and
Langfuse themselves. This is table stakes, not a moat. What wins is being the honest one: the "when
you should pick them instead" section is what earns links and trust when every other result is a
thinly-veiled ad.

### Tier 2

**`/ai-agent-observability`** — target `agent observability` (320, KD 13, **$51.93 CPC**) + `ai agent monitoring` (90)
Highest commercial value per visitor in the set.

**`/llm-testing`** — target `llm testing` (210, **KD 4**) + `llm testing framework` (50) + `test prompt`/`testing prompts` (390 each, KD 0)
Langfuse holds #5 here with a blog post. This is where the CI-gate story finally has a home: the
query has demand, and the differentiator answers it.

**`/ai-agent-testing`** — target `ai agent testing` (90, KD 1) + `ai agent testing framework` (40)
Discount the volume for mixed intent, but KD 1 against generic IBM/Salesforce content is cheap.

### Tier 3 — framework pages, cheapest to write

`/integrations/langchain` (`langchain observability` 90, KD 26) · `/langgraph` (`langgraph observability` 50 +
`langgraph testing` 20 at **competition 0.05**) · `/litellm` (`litellm observability` 30, KD 8) · `/crewai`

The SDK already supports all of these and the docs already explain them. Each is a natural link
target from the corresponding docs page.

### Tier 4 — blog, deliberately crude

Three posts as plain `.tsx` under `app/(marketing)/blog/`. **No MDX pipeline** — that gets added at
post #10. Topics that already exist as work: the hermetic replay design, the false-green gate bug,
judge calibration vs human labels. These earn HN/Reddit links, which is the actual point.

---

## 3. Phase 4 — off-page (the actual bottleneck)

**This is the work that matters now.** More pages won't help until the domain has authority, and
authority is referring domains.

### What we're up against, measured

Langfuse's profile (pulled 2026-08-12): **43,930 backlinks from 4,014 referring domains, rank 57.**
Twelve months ago it was 1,268 referring domains — they added ~2,750 in a year, currently running
**200–400 new referring domains per month.** Tracely is starting from approximately zero.

That gap doesn't close with content. But their profile shows *exactly* how they built it, and most
of it is mechanical rather than clever.

### Where their links actually come from — ranked by how copyable it is

**1. Integration partners (the biggest replicable win).** `dify.ai`, `lamatic.ai`, `llamaindex.ai`,
`crewai.com`, `railway.com`, `pipedream.com`, `microsoft.github.io`, `stripe.com` all link to
Langfuse — because Langfuse integrates with them and appears in *their* docs and integration
directories. These are high-authority, permanent, editorially-given links.

Tracely's SDK already supports OpenAI, Anthropic, Gemini, LangChain, LangGraph, LiteLLM, CrewAI and
Mistral. **Every one of those projects has an integrations page or ecosystem list we are not on.**
That's the single highest-value backlink action available, and it's a PR to a docs repo, not
outreach. Pair each one with the matching `/integrations/<framework>` page from Tier 3.

**2. Package registries.** `pypi.org` and `npmjs.com` both link to Langfuse. `tracely-ai` is on
PyPI already — make sure the package metadata points at `tracely-ai.com`, not just the repo.
Free link, already earned, possibly not claimed.

**3. Self-host and OSS directories.** `selfhost.directory`, `saashub.com`, `webcatalog.io`,
`mcp.directory`, `toolerific.ai`, `seektool.ai`, `aitoolsatlas.ai`, `bestfreeai.tools`. Individually
low quality, collectively a real chunk of their 4,014. Tracely being MIT with a `docker compose` path
is a strong fit for the self-host ones specifically. An afternoon of form-filling.

**4. Dev communities.** `dev.to`, `zenn.dev`, `qiita.com`, `deepwiki.com`. Note that two of those are
Japanese — Langfuse has meaningful JP developer traction and nobody in this category is competing
there.

**5. The listicles.** ~15 "best LLM observability tools" posts rank for the money terms —
confident-ai, langchain, posthog, galileo, mirascope, openobserve, comet, braintrust, mlflow,
voltagent, zenml, cekura, langwatch. Tracely is in none. Each is a backlink *and* a referral from a
page that already ranks. Most accept submissions.

**6. Awesome lists** — `awesome-llmops`, `awesome-llm-observability`, `awesome-selfhosted`. Cheap,
permanent PRs.

**7. Reddit.** Ranks **#1** for `llm observability tools` and top-5 for `ai agent testing` and
`llm testing`. Not a backlink (nofollow) but the audience is identical and it converts faster than
anything above. Participate, don't drop links.

### What NOT to copy

Langfuse's single largest referring domain is `pebbleai.app` (4,051 backlinks, spam score 14), and
several others in the top 10 are scraper sites with spam scores of 25–39. Those are noise, not
strategy. Their `clickhouse.com` links (2,461) come from the acquisition — not replicable.

### The order to do it in

1. Integration-partner docs PRs — highest authority, permanent, and we've earned them by shipping
   the integrations.
2. PyPI/npm metadata — free, five minutes.
3. Self-host + OSS directories — one afternoon, ~20 links.
4. Listicle submissions — email, slow, but each one also sends referral traffic.
5. Awesome-list PRs.
6. Show HN on a real engineering post, never on the product page.

---

## 4. Phase 5 — measure

| When | Check | Pass condition |
|---|---|---|
| +3 days | GSC → Pages → indexed | homepage + docs indexed, no "Discovered - not indexed" |
| +2 weeks | GSC → Performance | non-zero impressions; brand terms appearing |
| +30 days per page | GSC average position for that page's target query | trending down, impressions rising |
| Monthly | OpenSEO `get_search_opportunities` | pages at position 4–20 — cheapest wins, one edit each |

**Ignore rankings as a headline metric.** Impressions and average position per query are the signal.

**Honest timeline:** technical fixes register in days. New content pages take 2–6 months. If traffic
is needed sooner, that's Phase 4, not more pages.

---

## 5. Deferred, on purpose

- **`doc.tracely-ai.com` → `/docs`** — real win (docs attract the links; on a subdomain that
  authority doesn't fully flow to root) but a genuine migration with redirects. Revisit once the
  docs have inbound links worth consolidating.
- **MDX blog pipeline** — at post #10.
- **Rank tracker** — `run_rank_tracker` spends credits per keyword per device per check. Pointless
  until pages exist to track. GSC covers it free, if less precisely.
- **Programmatic SEO** — only once a hand-written template is proven to rank.

---

## 6. What only you can do

1. **Link Search Console inside OpenSEO** — unlocks `get_search_console_performance`, `inspect_urls`,
   `get_search_opportunities`. Without it I work from third-party estimates.
2. **Submit the sitemap** in GSC → Sitemaps; Request Indexing on the homepage.
3. **Inspect `doc.tracely-ai.com`** — those 11 pages just got titles for the first time.
4. **Bing Webmaster Tools** — import from GSC. Also feeds ChatGPT's web search.
5. **Approve the comparison-page claims** before they publish. I can describe what Langfuse and
   LangSmith do; publicly asserting a competitor's limitation is your call.
6. **Decide on the positioning question Finding 2 raises** — Braintrust is already selling "CI/CD
   deployment blocking". Is Tracely's public differentiator still the gate, or is it the hermetic
   replay of production failures with no authored dataset? The pages should say the same thing the
   homepage does, and right now the homepage leads with the gate.

---

## Appendix — credit ledger

| Call | Cost | Result |
|---|---|---|
| `get_keyword_metrics` × 75 keywords | 54 | volume/KD/intent/CPC for every hypothesis |
| `get_domain_keyword_suggestions` langfuse.com | 31 | 100 ranking keywords; surfaced `langfuse alternatives`, `llm trace`, `test prompt` (all KD 0) |
| `get_serp_results` × 5 | 100 | ground-truth page-1 for the decisive queries |
| **Total** | **185** | **315 credits remaining** |

Cheapest remaining high-value calls: `get_domain_keyword_suggestions` on `braintrust.dev` or
`confident-ai.com` (~31 each) if we want more discovery before writing.
