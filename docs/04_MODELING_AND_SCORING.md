# 04 — Modeling and Scoring

Numbers are from `outputs/metrics.json` (final run, 2026-10-29T17:27:59Z, 788 sections from 100 posts).

## 1. Embeddings

| Choice | Value | Why |
|---|---|---|
| Model | `BAAI/bge-small-en-v1.5` (384-d) | Strong retrieval/clustering quality for its size, runs on CPU, free and offline after download (ADR-001). |
| Fallback | `sentence-transformers/all-MiniLM-L6-v2` | Used automatically if the main model cannot load. |
| Input text | `heading + ". " + section body` | The heading adds topic signal that the body alone often lacks. |
| Normalisation | L2 (unit vectors) | Dot product equals cosine similarity throughout. |
| Runtime | 19.4 s for 788 sections on an Apple-silicon laptop CPU (cold cache) | |

A practical detail: bge similarities sit in a narrow, high band. In a check during development on this same data, sections were 0.82–0.93 similar to their own cluster centroid (10th to 90th percentile), and the median Gap topic's nearest Cynbit section was 0.78. Any fixed similarity threshold must be calibrated for the model (see effort below).

## 2. Dimensionality reduction and clustering

| Step | Parameters | Reasoning |
|---|---|---|
| UMAP | `n_components=10`, `n_neighbors=15`, `min_dist=0.0`, `metric=cosine`, `random_state=42` | 10 dimensions keep more structure than 2 for clustering; `min_dist=0` packs dense regions tightly, which suits HDBSCAN; 15 neighbours balances local and global structure for about 800 points. The fixed seed forces single-threaded UMAP, so runs are reproducible (the notebook re-runs it and gets identical cluster ids). |
| HDBSCAN | `min_cluster_size=5`, `min_samples=3`, `cluster_selection_method=eom` | 5 sections is the smallest group I would call a topic. `min_samples=3` is a little less conservative than the default, so fewer borderline sections become noise. |
| Plotting | separate 2-D UMAP, `min_dist=0.1` | For the topic map only, never for clustering. |

**Results.**

| Metric | Value |
|---|---|
| Clusters | 50 |
| Noise sections | 126 of 788 (noise ratio 0.16) |
| Cluster size | min 5, median 10, mean 13.24, max 81 |
| Silhouette, original embeddings, cosine (non-noise) | 0.1325 |
| Silhouette, UMAP space, Euclidean (non-noise) | 0.6012 |

I report both silhouettes because they answer different questions. In UMAP space the clusters separate clearly (0.60). In the original 384-d space separation is weak (0.13), which is normal for short business texts that share a lot of vocabulary ("AI", "automation", "business"). I treat clusters as useful groupings for a strategist to review, not as crisp categories.

Most clusters are dominated by one site (see the topic map in `outputs/figures/topic_map.png`). Each agency writes about its own niches in its own style. This matters for evaluation (`06`): a single-competitor cluster can be a real market topic or one agency's niche.

## 3. Labelling

- **Keywords (always).** Class-based TF-IDF over 1–3-grams picks terms that are distinctive for a cluster compared with the other clusters. KeyBERT then re-ranks those candidates by similarity to the cluster's text, with MMR (diversity 0.5) to avoid near-duplicates. English stop words, generic agency words ("business", "help", years) and the site names themselves are excluded, so "cynbit" or "proeffico" never become a topic keyword.
- **LLM topic name (when a key is present).** The 5 sections closest to the centroid are sent to Nemotron, which returns a 2–6-word name (prompt in `05`). In the final run all 50 clusters received an LLM name.
- **Representative sections** (closest to the centroid) are also used for the sample excerpt in `gaps.csv` and as grounding for briefs.

## 4. Gap rules

For each non-noise cluster I count client sections, competitor sections, distinct competitors covering it, and the client's share of sections.

| Status | Rule | Clusters |
|---|---|---|
| **Gap** | Client has 0 sections, at least one competitor has ≥1 | 30 |
| **Weak spot** | Client share < 0.20 **and** competitors have ≥3 sections | 10 |
| **Covered** | Otherwise, with sections from both sides | 5 |
| **Client-only** | No competitor sections | 5 |

Only Gaps and Weak spots are scored (40 clusters).

## 5. Opportunity score

```
score = 100 × ( 0.40 × relevance
              + 0.25 × competitor_strength
              + 0.20 × intent
              + 0.15 × (1 − effort) )
```

| Component | Definition | Range |
|---|---|---|
| **relevance** | Cosine similarity between the cluster centroid and the closest sentence in Cynbit's service descriptions (`data/client_services.txt`, taken from cynbit.in/services), min-max scaled across clusters. | 0–1 |
| **competitor_strength** | 0.5 × (competitors covering ÷ competitors crawled) + 0.5 × log(1 + competitor sections) ÷ log(1 + max competitor sections). | 0–1 |
| **intent** | Keyword rules over the cluster's keywords, section headings and page titles: transactional (pricing, cost, hire, agency, …) = 1.0, commercial (best, vs, comparison, ROI, tools, …) = 0.7, informational = 0.4. The rules live in `config.yaml`. The LLM topic name is deliberately not used, so scores do not depend on the LLM (ADR-008). | 0.4 / 0.7 / 1.0 |
| **effort** | 0 if Cynbit's nearest section is at least as similar to the centroid as a typical cluster member, meaning "expand an existing page"; otherwise 1, "new page". The threshold is the 25th percentile of member-to-centroid similarity across all clusters, **0.8483** in this run. | 0 or 1 |

**Why these weights.** Relevance gets the largest weight (0.40) because a gap is only worth filling if it supports something Cynbit sells; a competitor's niche that doesn't map to Cynbit's services is not an opportunity. Competitor strength (0.25) is the only demand proxy available without keyword data: two agencies independently writing about a topic suggests the market expects it. Intent (0.20) favours topics close to a buying decision, because Cynbit's blog exists to generate leads. Effort (0.15) is a tie-breaker that favours quick wins. These are judgement calls, which is why the weights are in config, adjustable live in the dashboard, and tested for sensitivity below.

**Score distribution.** The 40 scored clusters range from 25.56 to 83.59 (median 44.175). The scored set contains 24 commercial, 8 transactional and 8 informational clusters (`outputs/figures/score_distribution.png`).

Every row in `gaps.csv` has a `reason`, for example:

> Gap: 17 competitor sections from 1 of 2 competitors, none on Cynbit. High relevance to Cynbit's services (closest service: "AI automation suite: autonomous AI agents and cognitive automation that transform business operations through intelligent execution"). Commercial intent. Effort: expand the existing page https://www.cynbit.in/blog/small-business-ai-automation (similarity 0.86).

## 6. Sensitivity analysis

I shift each weight by ±0.1, rescale the other three so the weights still sum to 1, and compare the new top-10 with the default top-10.

| Weight shifted | −0.1 | +0.1 |
|---|---|---|
| relevance | 10/10 | 10/10 |
| competitor_strength | 10/10 | 10/10 |
| intent | 10/10 | 9/10 |
| effort | 10/10 | 10/10 |

Mean overlap is 9.88 of 10 and the minimum is 9. The top-10 is robust to reasonable disagreement about the weights. Stability is not the same as correctness, though: `06_EVALUATION.md` shows that the ranking is consistent, but it does not beat a simple baseline on my labels.

## 7. What the evaluation says about the score

On the hand labels, the score did not beat a naive baseline: Precision@10 0.60 vs 0.80, Precision@25 0.60 vs 0.64 (`06`). The root causes are in the design described above:

1. **Relevance is confounded with existing coverage.** The topics most similar to Cynbit's service text are the ones Cynbit has already blogged about, and relevance has the largest weight.
2. **Site-level cluster splitting creates false gaps.** Cluster 5, "AI automation for small businesses" (Cynbit 5, Proeffico 4 sections), is **Covered**. Its twin, cluster 14, "AI business automation benefits" (Proeffico 17), is the **#1 Gap**.
3. **The semantic coverage check only affects effort, not gap status** (§5): closeness to a Cynbit page raises the score instead of removing the topic from the Gap list.

A post-hoc ablation without relevance gave Precision@10 0.70. It is untuned, measured on the labels that motivated it, and not a claim. I have not retuned the shipped weights on these 31 labels; the v2 plan in `08` changes the gap logic and then re-evaluates on fresh labels.

## 8. From a weighted score to a supervised model

The weighted score is a starting point for prioritisation, not a prediction. Once briefs are published for pilot clients, the path to a learned model is:

1. **Outcome label.** For each published gap topic, whether the new page reached a meaningful level of Search Console impressions and clicks within 8–12 weeks (relative to the client's baseline), or a continuous target such as log impressions.
2. **Features.** The current components (relevance, competitor strength, intent, effort) plus data the PoC lacks: search volume, keyword difficulty, current SERP competitors, the client's domain-level Search Console performance and topical authority (how many related client pages already rank).
3. **Model.** Start with logistic regression or gradient-boosted trees; both stay explainable through coefficients or SHAP values, so strategists still see why a topic ranks high.
4. **Validation without leakage.** Cross-validation **grouped by client**, so the model is always tested on clients it has not seen. Topics from the same client share domain authority and audience, so random splits would overstate performance. I used the same client-grouped approach in a previous content-refresh model (see `08_EXECUTION_PLAN.md`).
5. **Baseline to beat.** The current weighted score and the competitor-count baseline, on the same grouped splits.
