# Architecture Decision Records

Each record follows: context → decision → alternatives → consequences.

---

## ADR-001: Sentence-transformers instead of paid embedding APIs

**Context.** I need embeddings for a few thousand short sections. The PoC must run without paid keys, on a CPU, and reproducibly.

**Decision.** I use `BAAI/bge-small-en-v1.5` via `sentence-transformers` (384 dimensions, normalised), with `all-MiniLM-L6-v2` as a fallback. Embeddings are cached to disk.

**Alternatives.** OpenAI / Cohere / NVIDIA embedding APIs; larger local models (bge-base, e5-large).

**Consequences.** Free, offline after the first download, deterministic, and fast enough on CPU at this scale. Quality is slightly below the best hosted models, which matters little for topic-level grouping. The model name is in `config.yaml`, so swapping is a one-line change.

---

## ADR-002: UMAP + HDBSCAN instead of k-means

**Context.** I do not know in advance how many topics exist across the sites, and blog content always has sections that do not belong to any coherent topic (intros, CTAs, one-off anecdotes).

**Decision.** I reduce embeddings with UMAP (cosine metric, fixed seed) and cluster with HDBSCAN. Sections HDBSCAN cannot place confidently are labelled noise (`-1`) and excluded from gap detection.

**Alternatives.** k-means or agglomerative clustering on raw embeddings; BERTopic as a packaged solution.

**Consequences.** No preset `k`, density-based clusters of varying size, and an explicit noise label, so stray sections do not create fake gaps. The trade-offs are sensitivity to `min_cluster_size` and UMAP parameters, and that the silhouette score is only computed on non-noise points. I report the noise ratio alongside it. BERTopic uses the same building blocks, but writing the steps directly keeps each stage visible and testable.

---

## ADR-003: Heading-level sections instead of whole pages

**Context.** A single blog post often covers several subtopics. Embedding the whole page averages them into one vector and hides the specific subtopics where gaps usually appear.

**Decision.** I split pages at H2/H3 headings, merge sections shorter than `min_words` into their neighbour and split sections longer than `max_words`. Text repeated across many pages of the same site (CTAs, newsletter blocks) is removed.

**Alternatives.** Whole-page embeddings; fixed-size token windows.

**Consequences.** Finer-grained, more interpretable topics, and a client page can partly cover a topic (useful for Weak spots and for the "expand existing page" effort signal). It depends on authors using headings sensibly; pages without headings fall back to length-based splits.

---

## ADR-004: Transparent weighted score instead of a trained model

**Context.** A supervised model would need outcome labels, such as which published topics later gained impressions or clicks. I have no such data in the PoC.

**Decision.** I use a weighted linear score over four interpretable components (relevance to the client's services, competitor strength, intent, effort), with weights in `config.yaml`, a plain-language reason per row, and a sensitivity check showing how the top-10 changes when weights move ±0.1.

**Alternatives.** Train on proxy labels; an LLM-judged priority score.

**Consequences.** Easy to explain to a strategist or client, and easy to tune. The weights are subjective, so I document the reasoning and measure sensitivity. Once pilot outcome data exists, this score becomes a baseline and a feature set for a supervised model (planned in `08_EXECUTION_PLAN.md`).

---

## ADR-005: LLM optional, with a keyword fallback

**Context.** LLM labels and briefs read better, but the free NVIDIA NIM tier is rate-limited, keys may be missing for a reviewer, and LLM output can be invalid or hallucinated.

**Decision.** Keywords (KeyBERT / TF-IDF) are always computed. If `NVIDIA_API_KEY` is set and `--no-llm` is not passed, Nemotron (via the OpenAI-compatible NIM endpoint) produces topic names and briefs. Invalid JSON gets one retry, then a template brief built from keywords and headings.

**Alternatives.** Require an LLM; skip LLMs entirely.

**Consequences.** The pipeline always completes, and the evaluation of clustering and scoring does not depend on the LLM. Each brief records its `source` (`llm` or `template`) so the difference is visible.

---

## ADR-006: Briefs for humans, not generated articles

**Context.** It would be technically easy to generate full articles for each gap. Google's spam policies name scaled content abuse (producing many pages mainly to manipulate rankings, including with automation) as a violation, and copying competitor content creates copyright risk.

**Decision.** RankRadar outputs briefs only: topic, why it matters, intent, title, outline, questions, references and an internal link. The LLM sees only short excerpts as grounding and is told not to copy text, invent statistics or promise rankings.

**Alternatives.** Full draft generation; auto-publishing to a CMS.

**Consequences.** A human writer stays responsible for quality and originality, which protects Cynbit's clients. The tool saves strategist time on research and planning rather than replacing writers.

---

## ADR-007: Nemotron 3.5 Super instead of the planned Llama 3.3 Nemotron Super 49B

**Context.** My plan named `nvidia/llama-3.3-nemotron-super-49b-v1`. Before the first call I listed the models on the NVIDIA API catalog endpoint: that id was no longer listed. I then sent the same small JSON task to the listed Nemotron chat models. `nemotron-3-super-120b-a12b`, `llama-3.1-nemotron-ultra-253b-v1`, `llama-3.1-nemotron-70b-instruct` and `nemotron-nano-3-30b-a3b` returned HTTP 404 for my key. `nemotron-3.5-super-vl-120b-a12b` and `nemotron-3-ultra-550b-a55b` both answered correctly.

**Decision.** I use `nvidia/nemotron-3.5-super-vl-120b-a12b`, the closest current Super-class model, through the same OpenAI-compatible client. It ignores the `detailed thinking off` system line (it still produced a reasoning trace in my probe), so I dropped that line and switch reasoning off with `chat_template_kwargs: {enable_thinking: false}` in `config.yaml`. With that setting it returned clean JSON with no reasoning tokens.

**Alternatives.** Nemotron 3 Ultra (larger and slower for the same short JSON tasks); keeping reasoning on (more tokens and latency, and nothing gained for naming a topic).

**Consequences.** The model id and the request options live in config, so changing back is a config edit. Code strips `<think>` blocks and code fences anyway, in case a model ignores the setting.

---

## ADR-008: Opportunity scores do not depend on the LLM

**Context.** At first the intent rules read the cluster label as well as its keywords. With the LLM on, the label is an LLM topic name, so the scores, and the ranking my hand labels evaluate, would change depending on whether a key was present.

**Decision.** Intent is classified from keywords, section headings and page titles only. The LLM affects topic names and brief wording, never scores or ranks.

**Consequences.** `--no-llm` and LLM runs produce the same `gaps.csv` scores and order, so precision results hold in both modes.

---

## ADR-009: Rename the project to RankRadar

**Context.** The project was built and evaluated under a previous working name (recorded in the git history before the rename commit). I chose a final name for the submission.

**Decision.** The project, Python package (`rankradar`), CLI (`python -m rankradar.pipeline`), crawler User-Agent (`RankRadarBot/0.1`), dashboard and documents are now called RankRadar, with the tagline "RankRadar: spot the content gaps between you and your competitors." Because the name could suggest rank tracking, the README and the opportunity report state plainly that RankRadar prioritises content opportunities and does not predict or track search rankings (see also risk 6 in `07_RISKS_AND_ETHICS.md`).

**Alternatives.** Keep the working name (more literal, but not the name I wanted to present).

**Consequences.** This is a rename only: no logic, configuration values (other than the User-Agent string) or weights changed. A `--no-llm` run after the rename reproduces the pre-rename outputs exactly, apart from names. Commits before the rename use the old name.
