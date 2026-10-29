# 01 — Software Requirements Specification: GapLens

Version 0.1 (PoC). Structure loosely follows IEEE 830.

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for the GapLens proof of concept: a pipeline and dashboard that finds content topics competitors cover and a client does not, scores them, and produces briefs for human writers. It is the contract the code is built against.

### 1.2 Scope

GapLens takes a client website and a set of competitor websites, crawls their public blog posts, groups the content into topics and outputs:

- a ranked table of content gaps with explanations (`outputs/gaps.csv`),
- content briefs for the top-N gaps (`outputs/briefs.json`),
- evaluation metrics and figures (`outputs/metrics.json`, `outputs/figures/`),
- an interactive Streamlit dashboard over these outputs.

It does not predict search rankings and does not publish content.

### 1.3 Definitions

| Term | Definition |
|---|---|
| **Page** | One crawled blog post: URL, title, headings, main text. |
| **Section** | A contiguous part of a page under one heading (H2/H3), merged or split to stay within configured word limits. The unit that is embedded and clustered. |
| **Cluster (topic)** | A group of semantically similar sections produced by HDBSCAN. Sections HDBSCAN cannot assign are **noise** (`cluster_id = -1`). |
| **Coverage** | For a cluster, the number of sections from the client and from each competitor. |
| **Client share** | `client_sections / total_sections` within a cluster. |
| **Gap** | A cluster with 0 client sections and at least 1 competitor covering it. |
| **Weak spot** | A cluster where the client has some sections but its share is below a threshold while competitors cover it strongly. |
| **Covered** | A cluster the client covers adequately. |
| **Client-only** | A cluster with client sections but no competitor sections. |
| **Opportunity score** | A transparent weighted score (0–100) used to prioritise Gaps and Weak spots. It is not a ranking prediction. |
| **Brief** | A structured writing plan for one gap: topic, why it matters, intent, title, outline, questions, references, internal link, score. |

### 1.4 References

- Cynbit services page: https://www.cynbit.in/services
- Google Search spam policies (scaled content abuse): https://developers.google.com/search/docs/essentials/spam-policies
- Robots Exclusion Protocol, RFC 9309: https://www.rfc-editor.org/rfc/rfc9309
- UMAP: McInnes, Healy, Melville (2018). HDBSCAN: Campello, Moulavi, Sander (2013).
- NVIDIA API catalog: https://build.nvidia.com

## 2. Overall description

### 2.1 Product perspective

GapLens is a standalone Python pipeline in the PoC. Each stage reads and writes files under `data/` and `outputs/`, so stages can be re-run independently and the dashboard only reads precomputed outputs. In production it would become a FastAPI service backed by PostgreSQL and a vector store (see `02_ARCHITECTURE.md`).

### 2.2 User classes

| User class | Interaction |
|---|---|
| SEO / content strategist | Configures sites, runs the pipeline, reviews gaps, adjusts weights. |
| Content writer | Reads briefs. |
| Account manager / client | Views the dashboard or exported tables in reports. |
| Reviewer (this assessment) | Runs the pipeline or opens the dashboard and notebook. |

### 2.3 Operating environment

- Python 3.10+; CPU only; macOS, Linux or Windows.
- Internet access for crawling and (optionally) the NVIDIA NIM API.
- Streamlit Community Cloud for the hosted demo.

### 2.4 Constraints

- Public pages only; robots.txt must be respected; 1–2 s between requests; ~60 posts per site.
- The LLM is optional: every stage must have a non-LLM path.
- Free-tier LLM rate limits: sequential calls, exponential backoff on HTTP 429, top-N cap on briefs.
- Secrets only in `.env`, never committed.

### 2.5 Assumptions

- Competitor blogs are a reasonable proxy for "topics the market expects an agency to cover".
- Heading structure in blog posts roughly reflects topical boundaries.
- Without traffic or keyword data, relevance to the client's services, competitor coverage, intent and effort are acceptable proxies for opportunity.

## 3. Functional requirements

| ID | Requirement | Input | Output | Priority |
|---|---|---|---|---|
| FR-01 | Crawl client and competitor URLs, discovering post URLs from listing pages, respecting robots.txt, a fixed delay, a clear User-Agent and a per-site page cap. Blocked sites are skipped and logged. | `config.yaml` sites | List of fetched post HTML; crawl log | Must |
| FR-02 | Extract clean main text, title, H1–H3 headings and URL from each post (trafilatura, BeautifulSoup fallback). | Post HTML | `data/raw/pages.jsonl` | Must |
| FR-03 | Split each page into heading-based sections; merge sections below `min_words`, split those above `max_words`; remove boilerplate repeated across pages of the same site. | `pages.jsonl` | `data/processed/sections.parquet` | Must |
| FR-04 | Generate L2-normalised sentence embeddings per section and cache them. | `sections.parquet` | `data/processed/embeddings.npy` | Must |
| FR-05 | Reduce dimensions with UMAP and cluster with HDBSCAN; mark noise as `-1`; keep a 2-D projection for plotting. | Embeddings | `data/processed/clusters.parquet` | Must |
| FR-06 | Label each cluster with keywords (KeyBERT / TF-IDF) and, if an LLM key is present, a short human-readable topic name. | Clusters + section text | Labels in `clusters.parquet` / `gaps.csv` | Must |
| FR-07 | Compute per-cluster coverage: client sections, competitor sections, distinct competitors covering, client share. | Clusters | Coverage columns in `gaps.csv` | Must |
| FR-08 | Classify each cluster as Gap / Weak spot / Covered / Client-only using configured thresholds. | Coverage | `status` column | Must |
| FR-09 | Score Gaps and Weak spots with a transparent weighted formula (relevance, competitor strength, intent, effort) and a plain-language `reason`. | Coverage, embeddings, service text | `score`, component columns, `reason` | Must |
| FR-10 | Generate briefs for the top-N gaps, grounded only in cluster excerpts and URLs; validate JSON; retry once; fall back to a template brief. | Top-N gaps | Brief objects | Must |
| FR-11 | Export `outputs/gaps.csv` and `outputs/briefs.json`. | Scored gaps, briefs | Files | Must |
| FR-12 | Streamlit dashboard with Overview, Topic Map, Gaps, Briefs and Method tabs, including live weight sliders that re-rank gaps. | Precomputed outputs | Web UI | Should |
| FR-13 | Evaluation: silhouette, noise ratio, cluster count and size distribution; a hand-label template for the top 25 gaps; Precision@10/@25 against hand labels vs a naive baseline; runtime per stage. | Outputs, hand labels | `outputs/metrics.json`, figures, `data/labels/gap_labels_template.csv` | Must |
| FR-14 | All URLs, limits, model names, thresholds, weights, top-N and seed are configurable in `config.yaml`. | — | — | Must |

## 4. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-01 | Performance | A full run (crawl excluded) completes in under 10 minutes on a laptop CPU for ~200 pages. Crawl time is bounded by the polite delay. |
| NFR-02 | Reliability | The pipeline completes end to end without `NVIDIA_API_KEY`. Network or LLM failures on one item do not abort the run. |
| NFR-03 | Reproducibility | Fixed random seeds for UMAP/HDBSCAN; pinned dependency versions; cached intermediate files; `--skip-crawl` re-runs on the same raw data. |
| NFR-04 | Security | No secrets in the repository; `.env` is git-ignored; `.env.example` documents required variables. |
| NFR-05 | Ethics | robots.txt respected; rate-limited crawling; public pages only; outputs are briefs for humans, never auto-published; briefs never copy competitor text. |
| NFR-06 | Transparency | Every opportunity score is decomposable into its components and accompanied by a plain-language reason. |
| NFR-07 | Maintainability | One module per stage; type hints and docstrings on public functions; basic tests in `tests/`. |

## 5. Acceptance criteria

- [ ] **AC-01 (FR-01, NFR-05):** Running the crawl writes per-site page counts; a site whose robots.txt disallows the crawler is skipped and logged; no site exceeds the page cap.
- [ ] **AC-02 (FR-02):** Every record in `pages.jsonl` has non-empty `url`, `site`, `role`, `title` and `text`.
- [ ] **AC-03 (FR-03):** All sections in `sections.parquet` are within `[min_words, max_words]`, except short pages that form a single section.
- [ ] **AC-04 (FR-04):** Embedding count equals section count and every vector has unit norm.
- [ ] **AC-05 (FR-05):** Each section has a `cluster_id`; noise is `-1`; silhouette and noise ratio are written to `metrics.json`.
- [ ] **AC-06 (FR-06):** Every non-noise cluster has keywords; with an LLM key, it also has a topic name.
- [ ] **AC-07 (FR-07, FR-08):** On a toy example in `tests/test_basic.py`, the status logic returns the expected Gap / Weak spot / Covered / Client-only labels.
- [ ] **AC-08 (FR-09):** All scores are within 0–100 and every scored row has a `reason`.
- [ ] **AC-09 (FR-10, FR-11):** `briefs.json` contains up to top-N briefs, each matching the brief schema, with `source` set to `llm` or `template`.
- [ ] **AC-10 (FR-12):** `streamlit run app/streamlit_app.py` loads and all five tabs render.
- [ ] **AC-11 (FR-13):** `gap_labels_template.csv` has 25 rows with blank `is_real_gap`; once filled, Precision@10/@25 and baseline precision appear in `metrics.json`.
- [ ] **AC-12 (FR-14):** Changing a weight or threshold in `config.yaml` changes the output without code changes.
- [ ] **AC-13 (NFR-01, NFR-02):** `python -m gaplens.pipeline --config config.yaml --skip-crawl --no-llm` completes in under 10 minutes.
- [ ] **AC-14 (NFR-04):** No API key or `.env` file is tracked by git.
