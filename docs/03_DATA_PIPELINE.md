# 03 — Data Pipeline

All figures below come from the run recorded in `outputs/metrics.json` (crawl on 29 October 2026; analysis run `run_at` 2026-10-29T17:27:59Z) and from `data/raw/crawl_log.jsonl`.

## 1. Sources

| Site | Role | Listing pages | Post URL pattern | Posts saved |
|---|---|---|---|---|
| Cynbit | client | `https://www.cynbit.in/blog?page=1` … `?page=5` | `cynbit.in/blog/<slug>` | 25 |
| Proeffico | competitor | `https://proeffico.ai/blog/` | `proeffico.ai/blog/<slug>` | 39 |
| Canny Technologies | competitor | `https://cannytechnology.com/blog` | `cannytechnology.com/blog/<slug>` | 36 |
| Automely | competitor | `https://automely.ai/blogs` | `automely.ai/blog(s)/<slug>` | 0 (skipped) |

**Automely was skipped.** In the pre-checks before this project, Automely's robots.txt refused an automated fetch. In this project the connection to `automely.ai/robots.txt` timed out every time: a manual `curl` check with my User-Agent and three crawler runs. RFC 9309 says a crawler must treat an unreachable robots.txt as a full disallow, so my crawler skipped the site and logged it:

```json
{"site": "Automely", "url": "https://automely.ai/blogs", "event": "site_skipped_robots",
 "detail": "robots.txt unreachable (ConnectTimeout); treated as full disallow per RFC 9309; ..."}
```

I did not try to work around this. The pipeline runs with two competitors, and every competitor count in the outputs uses the two sites that were actually crawled (`competitors_crawled: 2`).

## 2. Crawl policy

| Rule | Implementation |
|---|---|
| robots.txt | Fetched with my own User-Agent and parsed with `urllib.robotparser`. Following RFC 9309, a 404 means no restrictions; 401, 403, a 5xx or an unreachable file means the site is treated as disallowed. Every listing and post URL is checked with `can_fetch`. |
| User-Agent | `RankRadarBot/0.1 (content-gap research prototype; polite, robots.txt-aware)` |
| Delay | 1.5 s between requests per site, raised to the robots.txt `Crawl-delay` if that is higher (Cynbit's robots.txt sets 1 s). |
| Cap | 60 posts per site (no site reached it). |
| Scope | Public blog posts only. Listing, tag, category, author and paginated URLs are excluded by pattern. |
| Time | The full crawl of the three reachable sites took 4 min 21 s, almost all of it the polite delay. |

The raw HTML of every fetched post is cached in `data/raw/html/` (git-ignored), so extraction can be re-run without fetching again.

## 3. Extraction

For each post I run `trafilatura` (markdown output with headings) and a BeautifulSoup fallback, and keep the better result:

- The fallback walks H1–H3, paragraphs and list items inside the `<article>`/`<main>` element with the most paragraph text. Some pages have several `<article>` elements; on Cynbit's posts the first one is a related-post card.
- The fallback is used when trafilatura returns under 150 words, or when it keeps at least two fewer headings than the fallback while the fallback has at least 70% as many words. On Cynbit's posts trafilatura dropped most H2 headings.
- Some Proeffico posts serve raw markdown flattened onto one line (`... ## Where approvals get stuck Most approval delays ...`). I restore line breaks before inline `##`/`###` markers and end the heading at the first lowercase-to-capitalised word boundary. This is a heuristic: a heading containing a proper noun can be cut short, but the section boundary, which is what clustering uses, is still correct.
- When the server does not declare a charset, the page is decoded with the detected encoding (UTF-8). Without this, `requests` falls back to ISO-8859-1 and produces mojibake.
- The title is the page's H1, which avoids "| Site Blog" suffixes.

Result: 69 pages used the BeautifulSoup fallback and 31 used trafilatura. Median post length was 991 words for Cynbit, 1,601 for Proeffico and 798 for Canny Technologies, with no mojibake.

## 4. Cleaning and sectioning

1. Each page is split at its headings. Text before the first heading becomes an intro section headed by the page title.
2. **Page furniture is removed.** Sections headed "Table of Contents", "Share", "Tags" and similar are dropped. A heading such as "Related Insights", "Suggested Reading", "Written by" or "Join …" ends the page, because everything after it is cards, author boxes or newsletter blocks.
3. **Boilerplate is removed.** A paragraph that appears on 3 or more pages of the same site is dropped, as are short lines that look like calls to action ("subscribe", "book a call", "contact us").
4. Sections under **60 words** are merged into the next section (the last one merges backwards). Sections over **350 words** are split at paragraph boundaries.

| Site | Sections | Median words |
|---|---|---|
| Cynbit | 165 | 84 |
| Proeffico | 360 | 136 |
| Canny Technologies | 263 | 98 |
| **Total** | **788** | 104.5 (mean 126.7, min 21, max 350) |

The few sections under 60 words come from very short pages, which form a single section.

## 5. Embedding, clustering and outputs

Embeddings (`BAAI/bge-small-en-v1.5`, 384 dimensions, normalised) are cached in `data/processed/embeddings.npy` with a fingerprint of the model and texts, so they are recomputed only when sections change. Clustering, labelling and scoring are described in `04_MODELING_AND_SCORING.md`.

## 6. Schemas

The full data contracts are in `02_ARCHITECTURE.md` §3. In short:

| File | Grain | Committed to git |
|---|---|---|
| `data/raw/pages.jsonl` | one post | no (competitor full text is not redistributed) |
| `data/raw/html/*.html.gz` | one post | no |
| `data/raw/crawl_log.jsonl` | one skipped or failed URL | no |
| `data/processed/sections.parquet` | one section | no |
| `data/processed/embeddings.npy` | one section | no |
| `data/processed/clusters.parquet` | one section | no |
| `data/processed/cluster_labels.json` | one cluster | no |
| `outputs/gaps.csv` | one cluster | yes |
| `outputs/briefs.json` | one brief | yes |
| `outputs/topic_map.parquet` | one section (40-word excerpt only) | yes, for the dashboard |
| `outputs/metrics.json` | one run | yes |

`gaps.csv` also carries `relevance_raw` (cosine similarity before scaling), `closest_service` (the service sentence that matched) and `sites` (section counts per site) for transparency.

## 7. How production would add first-party and market data

The PoC only knows what competitors publish. A production version would add:

- **Google Search Console** (per client, with their consent): queries, impressions, clicks and average position per page. This lets RankRadar tell "topic Cynbit has never written about" apart from "topic Cynbit has a page for that gets impressions but few clicks", and it is the outcome data for a supervised model (see `04` and `08`).
- **A SERP / keyword API** (for example DataForSEO): search volume, keyword difficulty and the pages currently ranking for each cluster's keywords. This replaces competitor coverage as the main demand signal.
- **Scheduled re-crawls** (weekly or monthly) with HTTP caching (`ETag`/`Last-Modified`) to track new competitor content and gaps that close over time.
- **Storage** in PostgreSQL (pages, sections, clusters, gaps, briefs, outcomes) and Pinecone (section vectors, one namespace per client), as described in `02_ARCHITECTURE.md` §4.
