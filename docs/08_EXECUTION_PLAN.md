# 08 — Execution Plan

GapLens grows in five phases, from the public-data PoC to a learned model inside Cynbit's SEO retainers. Each phase has a clear exit criterion, so Cynbit can stop or redirect after any of them.

## Phase A: PoC on public data (done)

**Built:** crawler, sectioning, embeddings, clustering, gap detection, scoring, LLM briefs with a template fallback, evaluation, Streamlit dashboard, notebook and documentation. Demonstrated on Cynbit's blog against Proeffico and Canny Technologies.

**What it showed:**

- The pipeline runs end to end in under 3 minutes plus the polite crawl, with or without an LLM key.
- It finds concrete, useful gaps (logistics AI, WhatsApp chatbots, cloud provider comparison, custom CRM costs, on-prem LLMs).
- **Its ranking did not beat a simple competitor-count baseline on my labels**: Precision@10 0.60 vs 0.80, Precision@25 0.60 vs 0.64 (`06_EVALUATION.md`). The v2 plan below addresses the root causes before any client sees a ranking.

## v2 plan: fix the ranking before the pilot (about 2 weeks)

The evaluation found three root causes: relevance is confounded with existing coverage; site-level cluster splitting creates false gaps; and the semantic coverage check only affected effort, not gap status. v2 changes the gap logic first and the weights last.

| Step | Change | Why |
|---|---|---|
| 1. Coverage as a hard gate | Before scoring, compare every candidate topic with Cynbit's pages at page level (whole-page embeddings and the best-matching sections). A topic Cynbit already covers becomes Covered (or Weak spot if the coverage is thin) and is never scored as a Gap. Relevance becomes a gate ("does it fit Cynbit's services at all?") rather than the largest weight. | Removes the "already covered" false positives at the source instead of re-weighting around them. |
| 2. Cross-site topic alignment | Stop one subject splitting into a client cluster and a competitor cluster. Options: merge clusters whose centroids are very close (for example clusters 5 and 14), match each competitor cluster to its nearest client content before assigning status, or cluster on text with site-specific boilerplate and style markers removed. | Fixes false gaps like "AI business automation benefits" (#1 Gap) vs "AI automation for small businesses" (Covered). |
| 3. Fresh blind labels | Draw a new sample of topics from the v2 ranking and the baseline. Two labellers (at least one human) label it from a file with **no score, status or rank columns**, in shuffled order; labels are joined back afterwards. Report inter-annotator agreement (Cohen's kappa) and adjudicate disagreements before computing precision. | The PoC labels came from one labeller who could see the scores. v2 must be judged on labels it was not designed around. |
| 4. Search Console outcome data | With a pilot client, connect Search Console and run the online test (`06` §8): publish briefs for high- and low-scored topics and compare impressions and clicks over 8–12 weeks. | Labels measure fit; only outcomes measure whether a gap was worth filling. |

**Exit criterion:** on the fresh blind labels, v2 beats the competitor-count baseline at Precision@10 with acceptable agreement between labellers. If it does not, the baseline (with the coverage gate) is what goes to the pilot.

**Rule kept from the PoC:** no weights are tuned on the 31 PoC labels.

## Phase B: Pilot with one Cynbit SEO client (2–4 weeks)

| Work | Detail |
|---|---|
| Start from v2 | Use the v2 ranking only if it passed its exit criterion; otherwise the coverage-gated baseline. |
| Search Console ingestion | Read-only OAuth for one consenting client: queries, impressions, clicks and position per page. Use it to mark topics the client already ranks for. |
| Keyword data | A SERP/keyword API (for example DataForSEO) for search volume and difficulty per cluster; add demand as a score component. |
| Strategist workflow | The Content Strategist reviews the top 15 gaps and the briefs, and writers produce 8–10 articles. Start the online test from `06` §8. |

**KPIs:** precision@10 against two human labellers ≥ 0.8 (and above the baseline); strategist time per audit cut from days to under half a day; briefs accepted with only minor edits ≥ 70%.

**Exit criterion:** the strategist would use the ranked list instead of a manual audit for the next client.

## Phase C: Productise (1–2 months)

| Work | Detail |
|---|---|
| Service | FastAPI service (`/runs`, `/gaps`, `/briefs`, `/feedback`) with authentication. |
| Storage | PostgreSQL for clients, pages, sections, clusters, gaps, briefs and outcomes; Pinecone for section vectors, one namespace per client. Both are already in Cynbit's listed stack. |
| Scheduling | Monthly re-crawl and re-score per client (cron, then Airflow if volume grows), with "new gaps" and "gaps closed since last run" views. |
| Reporting | Dashboard embedded in client reports; CSV and PDF export of gaps and briefs. |
| Quality | CI running the tests and the `--no-llm` path; monitoring for model deprecations (ADR-007). |

**KPIs:** a monthly run for every SEO retainer client without engineer involvement; under 30 minutes of strategist time per client per month.

## Phase D: Content refresh module

GapLens answers "what should we create?". The other half of content strategy is "what should we fix?": existing pages that are losing impressions or clicks.

I have built this before. In a previous internship I built a **content-refresh prioritisation model**: a Random Forest that ranked existing pages by their likelihood of declining, validated with client-grouped splits so it was always tested on unseen clients. It reached a **ROC-AUC of 0.955 against 0.687 for the rule-based baseline** it replaced.

For Cynbit, the refresh module would use the Search Console history ingested in Phase B: trend features (impressions and clicks over 4/8/12 weeks), position volatility, content age, and competitor content published on the same cluster since the page was written (from GapLens's own crawl). Combined, GapLens covers both "what to create" and "what to fix", in one monthly report per client.

**KPIs:** ROC-AUC above the rule baseline on client-grouped validation; refreshed pages recover impressions faster than unrefreshed declining pages.

## Phase E: Supervised opportunity model

Once several pilot clients have published briefs with 8–12 weeks of Search Console outcomes, replace the hand-set weights with a model trained on outcomes (`04` §8): features from GapLens plus keyword data, client-grouped cross-validation, and the weighted score and competitor-count baseline as the bars to beat. Keep the explanations (coefficients or SHAP) so strategists still see why a topic ranks high.

**KPIs:** a higher rank correlation between predicted and actual impressions than the weighted score, on clients the model has not seen.

## Team and effort estimate

| Phase | People | Effort |
|---|---|---|
| v2 | 1 ML engineer (me), plus a second labeller for about a day | ~2 weeks |
| B | 1 ML engineer (me), Content Strategist part-time, 1 writer | 2–4 weeks |
| C | 1 ML engineer, 1 backend developer part-time | 4–8 weeks |
| D | 1 ML engineer | 3–4 weeks, overlapping with C once Search Console data flows |
| E | 1 ML engineer | 2–3 weeks, after at least one quarter of pilot outcomes |

## Dependencies and risks to the plan

- **Client consent** for Search Console access (Phase B onward).
- **Budget** for a keyword/SERP API, which is priced per request.
- **Writer capacity.** The online test needs articles actually published on schedule.
- **LLM provider stability.** Model ids change (ADR-007), so the template fallback must stay working.
- **Enough outcome data for Phase E.** One client is not enough to train a model; plan on several clients and at least one full quarter.
