# 06 — Evaluation

All numbers are from `outputs/metrics.json` (run 2026-10-29T17:35:44Z) unless marked otherwise. The headline result is honest and not flattering: **on my labels, GapLens's opportunity score did not beat a naive baseline.** The error analysis below explains why and what I would change.

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

**How the labels were made.** The 31 topics in `data/labels/gap_labels_template.csv` were labelled 1 ("a real gap Cynbit should plausibly write about, given its services") or 0 ("not a real gap": already covered by Cynbit, competitor self-promotion, outside Cynbit's services, or not a coherent topic). The 31 rows are the top 25 by opportunity score plus the extra topics in the baseline's top 25, so both rankings can be scored on the same labels.

- **AI-assisted, with a fixed rubric.** I generated the labels in a separate Claude Code session that did not share this project's context, using a written rubric (`label_source = ai_assisted_rubric_v1`). For each row it recorded a label, a one-line reason (`notes`) and a confidence level.
- **Blind to scores.** The labelling session worked from a blinded copy of the rows, and the labels were joined back to `cluster_id` through a separate mapping file. That blinded copy and the mapping file are not in this repository. The filled file `data/labels/gap_labels_filled.csv` has the scores joined back for analysis.
- **Human review of uncertain rows.** I reviewed the 20 medium- and low-confidence rows. Any row I changed would be marked `label_source = human_override`. **The file contains 0 human overrides**: all 31 labels are the rubric labels.

| Label summary | Count |
|---|---|
| Labelled topics | 31 |
| Real gaps (1) | 19 |
| Not gaps (0) | 12 |
| Confidence: high / medium / low | 11 / 12 / 8 |
| Human overrides | 0 |

**Limits of these labels.**

- **One labeller.** There is no second labeller, so no inter-annotator agreement. The labeller was an AI model following a rubric, which is consistent but can share blind spots with the embedding-based pipeline it is judging (both read the same text).
- **Small sample.** With 10 or 25 items, one label changes Precision@10 by 0.10 and Precision@25 by 0.04. The differences below are directional, not statistically significant.
- **No traffic data.** "Real gap" is a judgement about fit and coverage, not a measured outcome. A topic labelled 1 may still attract no searches.
- **"Already covered" depends on reading Cynbit's blog,** which the labeller did and the pipeline only does section by section. This matters for the error analysis.

## 4. Ranking results

| Ranking | Precision@10 | Precision@25 |
|---|---|---|
| **GapLens opportunity score** | **0.60** (6 of 10) | **0.60** (15 of 25) |
| Baseline: competitor section count only | 0.80 (8 of 10) | 0.64 (16 of 25) |

**Robustness check, excluding the 8 low-confidence labels:**

| Ranking | Precision@10 | Precision@25 |
|---|---|---|
| GapLens opportunity score | 0.5556 (5 of 9 labelled) | 0.5263 (10 of 19 labelled) |
| Baseline | 0.7778 (7 of 9 labelled) | 0.60 (12 of 20 labelled) |

The baseline stays ahead with or without the uncertain labels.

**Post-hoc component ablation** (drop one component, rescale the others). This is a diagnostic; I did not retune the shipped weights on these labels.

| Variant | Precision@10 | Precision@25 |
|---|---|---|
| Full score | 0.60 | 0.60 |
| Without relevance | 0.70 | 0.5909 (22 of 25 labelled) |
| Without competitor strength | 0.60 | 0.6522 (23 labelled) |
| Without intent | 0.60 | 0.625 (24 labelled) |
| Without effort | 0.60 | 0.60 |

When a variant's top 25 includes topics outside the labelled set, precision is computed over the labelled ones only (shown in brackets).

**Sensitivity to the weights.** Shifting any single weight by ±0.1 keeps on average 9.88 of the top 10 (minimum 9; only intent +0.1 changed one topic). The ranking is stable. On these labels it is stably mediocre, not stably good.

## 5. Error analysis

### Top-10 topics labelled 0: why they scored high

| Rank | Topic | Score | Labeller's reason (abridged) |
|---|---|---|---|
| 1 | AI business automation benefits (cluster 14) | 83.59 | Already covered by Cynbit's "How Small Businesses Can Automate Operations Using AI" |
| 3 | AI operational problem identification (47) | 71.82 | Already covered by the same post's "Step 1: Identifying the Automation-First Bottlenecks" |
| 6 | Payroll automation ROI (16) | 66.89 | Mixed topic; automation ROI already covered in "Top Productivity Automation Ideas" |
| 9 | Business Process Automation (17) | 54.25 | Already covered by "Best Business Automation Tools in 2026" |

All four false positives are topics **Cynbit already writes about**. They scored high for two connected reasons:

1. **The Gap rule only sees sections, not overall coverage.** A cluster is a Gap or Weak spot when few or none of Cynbit's *sections* fall into it. Cynbit's posts on these subjects split into sections that HDBSCAN placed in neighbouring clusters. The clearest example: cluster 5, "AI automation for small businesses", is **Covered** (5 Cynbit sections), while cluster 14, "AI business automation benefits", is the **#1 Gap**. They are the same subject from two angles.
2. **Relevance rewards being close to Cynbit's services.** Generic "AI automation for SMEs" is the closest possible match to Cynbit's service text, so it gets maximum relevance. But that is also exactly what Cynbit already blogs about. The ablation supports this: removing relevance lifts Precision@10 from 0.60 to 0.70.

**Did the semantic coverage check help? No, not as built.** The pipeline does measure how close Cynbit's nearest section is to each topic, but it uses that only for *effort*, where closeness raises the score as "cheap to expand". As a coverage detector it barely separates the classes: mean nearest-Cynbit-section similarity is 0.816 for topics labelled 1 and 0.8069 for topics labelled 0. Precision is 0.50 for topics flagged "expand existing page" (3 of 6) and 0.64 for "new page" (16 of 25). Three of the four top-10 false positives were flagged "expand existing page".

**Would a brand penalty have helped? GapLens has no brand penalty, so I checked a simple proxy instead:** the share of a cluster's competitor sections that name their own company. It is higher on average for topics labelled 0 (0.2966) than for topics labelled 1 (0.1985), but it would be a poor filter: 5 of the 8 clusters at or above 0.3 are real gaps (for example "breaking data silos", "AI in BFSI", "data readiness for AI"). The two clearest self-promotion clusters ("AI software development services", rank 11, and "AI development company India", rank 17, both labelled 0) are already outside the top 10.

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

1. **Coverage at the page level.** Compare each topic with whole Cynbit pages (or the mean of a page's sections), not only with individual sections. A topic close to an existing page should drop to Weak spot or Covered, not be scored as a Gap with "low effort".
2. **Re-think relevance.** Use relevance as a gate ("does this fit Cynbit's services at all?") rather than a 40% weight that rewards generic topics.
3. **Re-label with a fresh sample** before and after these changes, ideally with two human labellers, so the improvement is measured on labels the change was not designed around.

## 8. Limits of offline evaluation and the online test I propose

Offline labels can only say whether a topic *looks* like a worthwhile gap. Whether it is worthwhile is measured in search data. The test I would run with a pilot client:

- **Design.** Take the client's GapLens ranking. Publish articles from briefs for the top 8–10 topics (treatment) and for 4–5 low-scored but in-scope topics (control), written by the same writers to the same standard.
- **Measure.** Google Search Console impressions, clicks, CTR and average position per new URL, weekly for 8–12 weeks. Use relative growth to account for different launch dates.
- **Success.** Treatment pages gain more impressions and clicks than control pages by week 12, and the opportunity score correlates positively with outcomes (Spearman rank correlation).
- **Use the data.** These outcomes become the labels for the supervised opportunity model in `04` §8, validated with client-grouped cross-validation.
