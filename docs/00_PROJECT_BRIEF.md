# 00 — Project Brief: Cynbit GapLens

> **See the content your competitors cover and you don't.**

## 1. Problem

Cynbit Technologies sells Technical SEO, Funnel Optimization and Performance Ads as part of its digital marketing practice (https://www.cynbit.in/services). One recurring task in any SEO engagement is the **content gap audit**: working out which topics competitors publish about that the client does not, and deciding which of those topics are worth writing.

Done by hand, this audit takes a strategist several days. They open competitor blogs, skim posts, build a spreadsheet of topics, compare it with the client's site and make a judgement call on priority. The result depends heavily on who does it, is hard to repeat a quarter later, and rarely documents *why* a topic was ranked above another.

## 2. Target users

| User | What they need |
|---|---|
| Cynbit SEO / content strategist | A ranked, explainable list of content gaps per client, produced in minutes instead of days. |
| Cynbit content writers | Clear briefs (intent, outline, questions to answer, references) they can write from. |
| Cynbit account / growth manager | A repeatable deliverable to include in SEO retainers and to show progress quarter over quarter. |
| Cynbit's clients (indirect) | A transparent explanation of what content to invest in and why. |

## 3. The opportunity

GapLens turns the content gap audit into a repeatable, data-backed pipeline:

1. Crawl the client's blog and 2–3 competitor blogs (public pages only).
2. Split every page into heading-level sections.
3. Embed the sections and cluster them by meaning into topics.
4. For each topic, measure how much the client covers it versus competitors.
5. Flag **Gaps** (client does not cover the topic) and **Weak spots** (client covers it thinly).
6. Rank them with a transparent **opportunity score** and explain each score in plain words.
7. Generate **content briefs** for the top gaps, for human writers.

Why this matters for Cynbit specifically:

- It strengthens an existing service line instead of creating a new one. It plugs directly into SEO retainers.
- It uses only public data, so I can demonstrate it without access to Cynbit's internal systems.
- It is built on the stack Cynbit already lists on its services page (Python, FastAPI, PostgreSQL, Pinecone), so a production version fits the team's existing skills.
- **Build vs buy:** tools such as Surfer or Clearscope exist, but they are per-seat SaaS products, focused on single-page optimisation, and not white-labelled. An in-house engine lets Cynbit brand the output, tune the scoring to each client's services, keep the data, and keep the margin.

## 4. Why now

- Open-source sentence embedding models are now good enough, and small enough, to run topic clustering on a laptop CPU in minutes.
- Hosted LLM APIs (here NVIDIA NIM with Nemotron) make it cheap to turn a cluster of excerpts into a readable topic name and a structured brief.
- Google's guidance on scaled content abuse makes "generate 100 articles automatically" a liability. The value has shifted to *choosing the right topics* and briefing human writers well, which is exactly what GapLens does.
- Cynbit is hiring a Content Strategist and a Growth Manager, which suggests content is a growing part of its work.

## 5. Success definition for the PoC

The proof of concept is successful if:

1. The pipeline runs end to end on real public data (Cynbit's blog vs at least two competitor blogs) with one command, in under 10 minutes on a laptop CPU.
2. It runs without an LLM key (keyword-based labels and template briefs) and improves with one.
3. It produces a ranked `gaps.csv` where every score has a plain-language reason, and `briefs.json` for the top-N gaps.
4. Cluster quality is reported with standard metrics (silhouette, noise ratio), and ranking quality is measured as Precision@10 / Precision@25 against my own hand labels, compared with a naive baseline.
5. A Streamlit dashboard lets a reviewer explore the topic map, the gaps and the briefs.
6. Every number in the documentation comes from an actual run.

## 6. Scope

**In scope**

- Crawling public blog posts (robots.txt respected, rate-limited, max ~60 posts per site).
- Section-level embeddings, UMAP + HDBSCAN clustering, keyword and optional LLM labels.
- Gap / weak-spot detection, weighted opportunity score, sensitivity check on weights.
- Grounded content briefs (LLM with template fallback).
- Offline evaluation, Streamlit dashboard, walkthrough notebook, documentation.

**Out of scope**

- Predicting Google rankings or traffic. GapLens produces an *opportunity score* for prioritisation, not a ranking forecast.
- Generating or publishing full articles. Outputs are briefs for human writers.
- Keyword volume / difficulty data, Google Search Console data, backlinks (planned for the production version).
- Authentication, multi-tenant storage, scheduling (planned for production).

## 7. Demo case

I run GapLens on **Cynbit's own blog** (https://www.cynbit.in/blog) as the client, against competitor agency blogs with overlapping services:

| Site | Role | Listing |
|---|---|---|
| Cynbit | Client | https://www.cynbit.in/blog (paginated, `?page=1` to `?page=5`) |
| Proeffico | Competitor | https://proeffico.ai/blog/ |
| Canny Technologies | Competitor | https://cannytechnology.com/blog |
| Automely | Competitor (conditional) | https://automely.ai/blogs, only if its robots.txt allows my crawler |

The output answers one question: **which topics is Cynbit's own content missing, and which should it write first?**

## 8. Deliverables

1. `reports/AI_OPPORTUNITY_REPORT.md`: the opportunity analysis and why I chose GapLens.
2. The working PoC: pipeline, Streamlit app and notebook.
3. `reports/TECHNICAL_APPROACH_REPORT.md`: architecture, modelling, evaluation and execution plan.
