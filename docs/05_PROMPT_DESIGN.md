# 05 — Prompt Design

The LLM is used for two small, well-bounded jobs: naming topic clusters and writing content briefs. Neither job affects scores or ranking (ADR-008), and the pipeline runs fully without it (ADR-005).

## 1. Model and client

| Setting | Value |
|---|---|
| Provider | NVIDIA API catalog (NIM), OpenAI-compatible endpoint `https://integrate.api.nvidia.com/v1` |
| Client | `openai` Python SDK with `base_url` and `api_key` from `NVIDIA_API_KEY` in `.env` |
| Model | `nvidia/nemotron-3.5-super-vl-120b-a12b` (the planned `llama-3.3-nemotron-super-49b-v1` is no longer listed; see ADR-007) |
| Reasoning | Off, via `extra_body={"chat_template_kwargs": {"enable_thinking": false}}`. This model ignored the `detailed thinking off` system line in my probe, so I removed that line. |
| Temperature | 0.2 |
| Max tokens | 60 for topic names, 1,500 for briefs |
| Calls | Sequential, with exponential backoff (2 s, doubling, up to 5 retries) on HTTP 429, timeouts, connection errors and 5xx |

## 2. Prompt 1: cluster topic name

**System prompt (exact text):**

```text
You name topic clusters for an SEO content strategist. Given excerpts from blog sections that belong to one topic, reply with JSON only: {"topic": "<a specific topic name of 2 to 6 words>"}. Use plain words a marketer would search for. Do not add commentary.
```

**User message:** the cluster's keywords, then the 5 sections closest to the centroid, each cut to 500 characters:

```text
Keywords: <kw1>, <kw2>, ...

Excerpts:
- <section 1 heading + text, max 500 chars>

- <section 2 ...>
```

**Validation:** the reply must parse as JSON with a `topic` of 1–10 words; otherwise the keyword label is kept.

## 3. Prompt 2: content brief

**System prompt (exact text):**

```text
You are an SEO content strategist at a digital agency. You write content briefs that a human writer will use to write an original article for the agency's own blog.

Rules:
- Use only the excerpts and facts provided. Do not invent statistics, numbers, client names, case studies or quotes.
- Do not copy sentences or headings from the excerpts. They come from competitors; use them only to understand what the topic covers.
- Do not promise rankings, traffic or guaranteed results.
- Write for the client company described in the input, matching its services.
- Reply with one JSON object only, no markdown, no commentary.
```

**User message template (exact text; `{…}` are filled by code):**

```text
Client: {client}
Client services (summary): {services}

Topic cluster: {label}
Keywords: {keywords}
Status: {status} ({reason})
Detected search intent: {intent}

Competitor excerpts covering this topic (for understanding only, do not copy):
{excerpts}

Return a JSON object with exactly these keys:
{
  "topic": "short topic name, 2-6 words",
  "why_it_matters": "2-3 sentences on why this topic matters for {client}'s audience and services, without statistics",
  "target_intent": "one of: informational, commercial, transactional",
  "suggested_title": "an original article title, max 70 characters",
  "outline": [{"h2": "section heading", "h3": ["sub-heading", "..."]}],
  "questions_to_answer": ["question the article should answer", "..."]
}
The outline should have 4-7 H2 items, each with 0-3 H3 items. Give 4-8 questions.
```

`{services}` is the first 900 characters of `data/client_services.txt` (taken from cynbit.in/services). `{excerpts}` is up to 5 competitor sections from the cluster (representative ones first), each cut to 120 words and prefixed with its URL and heading.

## 4. Output schema

The LLM fills only the editorial fields. Code adds the rest from the pipeline's own data, so the model cannot invent URLs or scores.

| Field | Filled by | Type |
|---|---|---|
| `topic`, `why_it_matters`, `suggested_title` | LLM | string |
| `target_intent` | LLM (must be informational / commercial / transactional) | string |
| `outline` | LLM | list of `{h2: str, h3: [str]}`, 2–10 items |
| `questions_to_answer` | LLM | non-empty list of strings |
| `competitor_reference_urls` | code (up to 5 URLs from the cluster) | list |
| `internal_link_from` | code (nearest Cynbit page) | string |
| `opportunity_score`, `status`, `cluster_id` | code | number / string |
| `source`, `model`, `llm_attempts`, `validation_failures` | code (audit trail) | mixed |

## 5. Grounding strategy

- **Context is limited to the cluster.** The model sees short excerpts from that topic's competitor sections plus Cynbit's own service summary, nothing else. This keeps briefs tied to what the topic actually covers and to what Cynbit actually sells.
- **Facts the model must not decide are kept out of its hands.** URLs, the internal link, the score and the status come from code.
- **The status and reason are passed in**, so "why it matters" can refer to real coverage ("Cynbit covers this only briefly") instead of guessing.

## 6. Guardrails and failure handling

1. `<think>…</think>` blocks and code fences are stripped before parsing, in case a model ignores the reasoning setting.
2. The reply is parsed as JSON, taking the outermost `{…}` if there is surrounding text.
3. **Schema validation** (`validate_brief`): required fields, a valid intent value, outline shape, non-empty questions.
4. **Copy check in code** (`copied_phrases`): if any field shares an 8-word sequence with the excerpts the model was shown, the brief is invalid. I added this after an audit of a pre-release run found that one brief (cluster 47) reused competitor sentences almost word for word in its questions, despite the "do not copy" rule.
5. **One retry.** The error list is appended to the prompt ("Your previous reply was invalid: … Return only the JSON object.").
6. **Template fallback.** If the retry also fails, a deterministic brief is built from keywords and gap data, and `source` is set to `template`.

## 7. Observed cost and latency (final run)

From `outputs/metrics.json` (run 2026-10-29T17:35:44Z):

| Metric | Value |
|---|---|
| LLM calls | 61 (50 topic names, 11 brief calls) |
| Prompt tokens | 48,939 |
| Completion tokens | 6,555 |
| Mean latency per call | 2.27 s |
| Max latency per call | 29.81 s |
| Stage time: labels | 48.95 s |
| Stage time: briefs | 92.64 s |
| Briefs from the LLM / template | 10 / 0 |
| Retries | 1 (cluster 47 failed the copy check on its first attempt and passed on the retry) |

The NVIDIA API catalog's free tier covered the run, so I have no dollar cost to report. The volume is small: about 49k input and 7k output tokens for a full client analysis. Cost on a paid endpoint is that volume times the provider's current per-token price.

After the run I checked every brief against **all** competitor text, not only the excerpts it saw. No brief shares an 8-word sequence with any competitor section. The only numbers in the briefs (a 2027 DPDP Act date, team sizes of 15/50/100 users and a year in one title) also appear in the competitor text for that topic, so none was invented. One of them is stale, though: brief 28's title says "in 2025" because a competitor post did. Section 6 of `06_EVALUATION.md` covers this.
