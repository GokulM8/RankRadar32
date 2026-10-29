# 06 — Evaluation

All numbers are from `outputs/metrics.json` (run 2026-10-29T17:35:44Z) unless marked otherwise.

## Result

**The GapLens opportunity score did not beat a naive baseline.** On 31 labelled topics:

| Ranking | Precision@10 | Precision@25 |
|---|---|---|
| GapLens opportunity score | **0.60** | **0.60** |
| Baseline: rank by competitor section count only | **0.80** | **0.64** |

The labels come from one AI-assisted labelling pass that could see the score column (§3), which, if anything, would bias them toward GapLens's ranking, and the baseline still won. Section 5 explains the root causes, and `08_EXECUTION_PLAN.md` sets out the v2 plan that addresses them.

## 1. What is evaluated

| Question | Method |
|---|---|
| Are the topic clusters coherent? | Silhouette scores, noise ratio, cluster sizes |
| Is the ranking robust to the weight choices? | ±0.1 weight sensitivity check on the top-10 |
| Does the ranking put real gaps first? | Precision@10 and Precision@25 against hand labels, compared with a baseline |
| Are the briefs safe to hand to a writer? | Schema validation, a code-level copy check, a post-run audit for copied text and invented numbers |
| Is it fast enough? | Runtime per stage |

## 2. Cluster quality

| Metric | Value |
|---|---|
| Sections clustered | 788 |
| Clusters | 50 |
| Noise | 126 sections (ratio 0.16) |
| Cluster size | min 5, median 10, mean 13.24, max 81 |
| Silhouette, original embeddings (cosine, non-noise) | 0.1325 |
| Silhouette, UMAP space (Euclidean, non-noise) | 0.6012 |

The clusters separate well in the reduced space but only weakly in the original space. That is expected for short agency blog sections that share a lot of vocabulary. Reading the clusters, most are recognisable topics (logistics AI, WhatsApp chatbots, cloud provider comparison, SaaS MVP costs). A few mix two source articles (noted by the labeller for clusters 0 and 30).

## 3. Labelling method

**What was done.** The 31 topics in `data/labels/gap_labels_template.csv` were labelled 1 ("a real gap Cynbit should plausibly write about, given its services") or 0 ("not a real gap": already covered by Cynbit, competitor self-promotion, outside Cynbit's services, or not a coherent topic). The 31 rows are the top 25 by opportunity score plus the extra topics in the baseline's top 25, so both rankings can be scored on the same labels.

- **One AI-assisted labelling pass with a fixed rubric.** A separate Claude Code session, which did not share this project's context, labelled every row against a written rubric (`label_source = ai_assisted_rubric_v1`). For each row it recorded a label, a one-line reason (`notes`) and a confidence level.
- **Not blind to scores.** The CSV the labeller worked from contained the `score` column (and `status`). The labels could therefore be biased toward GapLens's own ranking, which would make GapLens look *better* than it is. Even so, the baseline won.
- **0 human overrides.** I did not change any labels. All 31 are the rubric labels as produced.
- The filled file is `data/labels/gap_labels_filled.csv`.

| Label summary | Count |
|---|---|
| Labelled topics | 31 |
| Real gaps (1) | 19 |
| Not gaps (0) | 12 |
| Confidence: high / medium / low | 11 / 12 / 8 |
| Human overrides | 0 |
| Labellers | 1 |

**Limits of these labels.**

- **One labeller.** There is no second labeller and no agreement score. The labeller was an AI model; it is consistent, but it can share blind spots with an embedding-based pipeline that reads the same text.
- **Scores were visible**, so the labels are not an independent test of the ranking (see above).
- **Small sample.** With 10 or 25 items, one label changes Precision@10 by 0.10 and Precision@25 by 0.04. The differences are directional, not statistically significant.
- **No traffic data.** "Real gap" is a judgement about fit and coverage, not a measured outcome.

## 4. Ranking results

| Ranking | Precision@10 | Precision@25 |
|---|---|---|
| GapLens opportunity score | 0.60 (6 of 10) | 0.60 (15 of 25) |
| Baseline: competitor section count only | 0.80 (8 of 10) | 0.64 (16 of 25) |

**Robustness check, excluding the 8 low-confidence labels:**

| Ranking | Precision@10 | Precision@25 |
|---|---|---|
| GapLens opportunity score | 0.5556 (5 of 9 labelled) | 0.5263 (10 of 19 labelled) |
| Baseline | 0.7778 (7 of 9 labelled) | 0.60 (12 of 20 labelled) |

The baseline stays ahead with or without the uncertain labels.

**Sensitivity to the weights.** Shifting any single weight by ±0.1 keeps on average 9.88 of the top 10 (minimum 9; only intent +0.1 changed one topic). The ranking is stable. On these labels it is stably mediocre, not stably good.

**Post-hoc ablation (diagnostic only, not a result).** After seeing the labels, I re-scored with each component removed (other weights rescaled). These numbers come from the same 31 labels that motivated the analysis, are untuned, and are **not a claim that any variant is better**. Where a variant's top 25 includes unlabelled topics, precision is over the labelled ones only (in brackets). The shipped weights are unchanged.

| Variant | Precision@10 | Precision@25 |
|---|---|---|
| Full score (shipped) | 0.60 | 0.60 |
| Without relevance | 0.70 | 0.5909 (22 of 25 labelled) |
| Without competitor strength | 0.60 | 0.6522 (23 labelled) |
| Without intent | 0.60 | 0.625 (24 labelled) |
| Without effort | 0.60 | 0.60 |

The only use I make of this table is as a pointer to where to look: removing relevance moves Precision@10 the most, which is consistent with the root cause below. Whether a change helps must be tested on fresh labels (`08` v2 plan).

## 5. Error analysis and root causes

### Top-10 topics labelled 0

| Rank | Topic | Score | Labeller's reason (abridged) |
|---|---|---|---|
| 1 | AI business automation benefits (cluster 14) | 83.59 | Already covered by Cynbit's "How Small Businesses Can Automate Operations Using AI" |
| 3 | AI operational problem identification (47) | 71.82 | Already covered by the same post's "Step 1: Identifying the Automation-First Bottlenecks" |
| 6 | Payroll automation ROI (16) | 66.89 | Mixed topic; automation ROI already covered in "Top Productivity Automation Ideas" |
| 9 | Business Process Automation (17) | 54.25 | Already covered by "Best Business Automation Tools in 2026" |

All four are topics **Cynbit already writes about**. There are three root causes.

**Root cause 1: relevance is confounded with existing coverage.** Relevance measures how close a topic is to Cynbit's service descriptions. Cynbit's blog is written about those same services, so the most "relevant" topics are disproportionately the ones Cynbit has already covered. Relevance carries the largest weight (0.40), so it pushes already-covered topics to the top. Generic "AI automation for SMEs" is the closest possible match to Cynbit's service text, and it is also what Cynbit already blogs about most.

**Root cause 2: site-level cluster splitting creates false gaps.** Most clusters are dominated by one site's writing (`outputs/figures/topic_map.png`). When two sites write about the same subject in different styles, HDBSCAN can split it into two clusters, one per site, and the competitor's half then looks like a Gap. The clearest case is the small-business automation twin:

| Cluster | Label | Sections by site | Status | Score |
|---|---|---|---|---|
| 5 | AI automation for small businesses | Cynbit 5, Proeffico 4 | Covered | — |
| 14 | AI business automation benefits | Proeffico 17 | **Gap (rank 1)** | 83.59 |

Same subject, two clusters. Because Proeffico's 17 sections landed in their own cluster with no Cynbit sections, the top-ranked "gap" is a topic Cynbit covers.

**Root cause 3: the semantic coverage check only affected effort, not gap status.** The pipeline does measure how close Cynbit's nearest section is to each topic, but it uses that only for the *effort* component, where closeness *raises* the score ("cheap to expand"). It never changes a topic's status from Gap to Covered. Three of the four top-10 false positives were flagged "expand existing page", the strongest available signal that Cynbit already has the content. As a coverage detector it also barely separates the classes: mean nearest-Cynbit-section similarity is 0.816 for topics labelled 1 and 0.8069 for topics labelled 0, and precision is 0.50 for "expand existing page" topics (3 of 6) vs 0.64 for "new page" topics (16 of 25).

**What about a brand penalty?** GapLens has none. As a proxy I measured the share of a cluster's competitor sections that name their own company. It is higher on average for topics labelled 0 (0.2966) than for topics labelled 1 (0.1985), but it would be a poor filter: 5 of the 8 clusters at or above 0.3 are real gaps. The two clearest self-promotion clusters ("AI software development services", rank 11, and "AI development company India", rank 17, both labelled 0) are already outside the top 10.

### Topics labelled 1 that ranked low (rank > 15)

| Rank | Topic | Score |
|---|---|---|
| 16 | data modernization strategy (29) | 48.15 |
| 18 | breaking data silos (32) | 45.67 |
| 21 | AI implementation timeline (27) | 44.02 |
| 23 | GraphQL vs REST APIs (0) | 43.45 |
| 25 | software development project planning (31) | 41.05 |
| 26 | India vs Eastern Europe offshore developers (39) | 39.96 |
| 29 | AI in BFSI India (6) | 37.61 |
| 31 | data readiness for AI projects (22) | 37.36 |
| 38 | Approval workflow automation (11) | 34.60 |

These are mostly **specific, practical topics** (API design, estimation, approval workflows, data readiness) that one competitor covers in depth. They lose on relevance, because their wording is further from Cynbit's broad service sentences, and on competitor strength, because only one competitor covers them. Yet they are exactly where Cynbit's blog is thin. The relevance signal favours broad, generic topics; a strategist would often prefer the specific ones.

### Good and bad examples

**Good (labelled 1, ranked in the top 10):** AI logistics automation (#2), WhatsApp chatbot automation (#4), AI implementation in Indian healthcare (#5), cloud provider comparison (#7: Cynbit has only a 137-word post on serverless), custom CRM vs Salesforce costs (#8), on-prem LLM deployment for Indian enterprises (#10). These are concrete topics that map onto Cynbit services Cynbit's blog barely covers. Their briefs are usable as written.

**Bad:** the four "already covered" topics above, and two brief-level issues:

- The brief for cloud provider comparison is titled "… in 2025": the model copied the year from a competitor post written earlier. A writer would catch it, but it shows why briefs need a human pass.
- In a pre-release run, the brief for cluster 47 copied competitor sentences into its questions despite the prompt rule. I added a code-level copy check. In the final run it caught the same cluster on the first attempt and the retry passed (1 retry; 10 of 10 briefs from the LLM, 0 template fallbacks). A post-run audit against all competitor text found no shared 8-word sequence in any brief.

## 6. Runtime

| Stage | Seconds |
|---|---|
| Sectionize | 0.13 |
| Embed (cold cache) | 19.4 |
| Cluster | 6.04 |
| Label (50 LLM calls) | 48.95 |
| Gaps and score | 0.17 |
| Briefs (11 LLM calls) | 92.64 |
| Evaluate | 0.48 |
| **Total, excluding crawl** | **167.81** |

That is under 3 minutes on a laptop CPU, comfortably inside the 10-minute requirement (NFR-01); the LLM calls take most of it. The crawl itself took 4 min 21 s for 100 posts at a 1.5 s delay (from the crawl run's log, not part of `metrics.json`).

## 7. What I would change before trusting the ranking

The v2 plan is in `08_EXECUTION_PLAN.md`. In short: make coverage a hard gate before scoring, align topics across sites so one subject cannot split into a client cluster and a competitor cluster, then re-evaluate on fresh blind labels from two labellers with an agreement score, and finally on Search Console outcomes. I have deliberately not retuned the weights on these 31 labels.

## 8. Limits of offline evaluation and the online test I propose

Offline labels can only say whether a topic *looks* like a worthwhile gap. Whether it is worthwhile is measured in search data. The test I would run with a pilot client:

- **Design.** Take the client's GapLens ranking. Publish articles from briefs for the top 8–10 topics (treatment) and for 4–5 low-scored but in-scope topics (control), written by the same writers to the same standard.
- **Measure.** Google Search Console impressions, clicks, CTR and average position per new URL, weekly for 8–12 weeks. Use relative growth to account for different launch dates.
- **Success.** Treatment pages gain more impressions and clicks than control pages by week 12, and the opportunity score correlates positively with outcomes (Spearman rank correlation).
- **Use the data.** These outcomes become the labels for the supervised opportunity model in `04` §8, validated with client-grouped cross-validation.
