"""Grounded content briefs for the top-N gaps (FR-10, FR-11).

The LLM writes only the editorial fields (topic, why it matters, intent, title, outline,
questions). Reference URLs, the internal link and the score are filled in by code from the
pipeline's own data, so the model cannot invent them. Invalid output gets one retry, then
a template brief built from keywords is used instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

INTENTS = ("informational", "commercial", "transactional")

SYSTEM_PROMPT = """You are an SEO content strategist at a digital agency. You write content briefs that a human writer will use to write an original article for the agency's own blog.

Rules:
- Use only the excerpts and facts provided. Do not invent statistics, numbers, client names, case studies or quotes.
- Do not copy sentences or headings from the excerpts. They come from competitors; use them only to understand what the topic covers.
- Do not promise rankings, traffic or guaranteed results.
- Write for the client company described in the input, matching its services.
- Reply with one JSON object only, no markdown, no commentary."""

USER_TEMPLATE = """Client: {client}
Client services (summary): {services}

Topic cluster: {label}
Keywords: {keywords}
Status: {status} ({reason})
Detected search intent: {intent}

Competitor excerpts covering this topic (for understanding only, do not copy):
{excerpts}

Return a JSON object with exactly these keys:
{{
  "topic": "short topic name, 2-6 words",
  "why_it_matters": "2-3 sentences on why this topic matters for {client}'s audience and services, without statistics",
  "target_intent": "one of: informational, commercial, transactional",
  "suggested_title": "an original article title, max 70 characters",
  "outline": [{{"h2": "section heading", "h3": ["sub-heading", "..."]}}],
  "questions_to_answer": ["question the article should answer", "..."]
}}
The outline should have 4-7 H2 items, each with 0-3 H3 items. Give 4-8 questions."""


def validate_brief(data: Any) -> list[str]:
    """Return a list of schema problems (empty if the LLM part of the brief is valid)."""
    if not isinstance(data, dict):
        return ["not a JSON object"]
    errors = []
    for key in ("topic", "why_it_matters", "suggested_title"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key} missing or empty")
    if data.get("target_intent") not in INTENTS:
        errors.append("target_intent invalid")
    outline = data.get("outline")
    if not isinstance(outline, list) or not 2 <= len(outline) <= 10:
        errors.append("outline must be a list of 2-10 items")
    else:
        for item in outline:
            if not isinstance(item, dict) or not isinstance(item.get("h2"), str) or not isinstance(item.get("h3", []), list):
                errors.append("outline items need h2 (str) and h3 (list)")
                break
    qs = data.get("questions_to_answer")
    if not isinstance(qs, list) or not qs or not all(isinstance(q, str) for q in qs):
        errors.append("questions_to_answer must be a non-empty list of strings")
    return errors


ACRONYMS = {"saas": "SaaS", "mvp": "MVP", "bfsi": "BFSI", "ocr": "OCR", "llm": "LLM", "llms": "LLMs", "iot": "IoT"}


def _fmt(keyword: str) -> str:
    """Display form of a keyword: known acronyms and 2-3 letter tokens upper-cased."""
    return " ".join(ACRONYMS.get(w, w.upper() if len(w) <= 3 else w) for w in keyword.split())


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def template_brief(row: pd.Series, client: str) -> dict[str, Any]:
    """Deterministic brief from keywords and gap data, used without an LLM or after LLM failure."""
    kws = [_fmt(k) for k in str(row["top_keywords"]).split(", ") if k][:5] or [str(row["label"])]
    main = kws[0]
    topic_title = " and ".join(k if k[:1].isupper() else k.capitalize() for k in kws[:2])
    commercial = row["intent"] != "informational"

    outline = [{"h2": f"{topic_title}: what it is and why it matters", "h3": ["Who this is for", "Typical problems it solves"]}]
    outline += [{"h2": f"The role of {k}", "h3": ["Practical examples", "Common pitfalls"]} for k in kws[1:4]]
    if commercial:
        outline.append({"h2": "Choosing the right implementation partner", "h3": ["Questions to ask", "What a realistic timeline looks like"]})
    outline.append({"h2": f"How {client} approaches this", "h3": ["Relevant services", "Next steps for readers"]})

    questions = [
        f"What is {main} and which businesses need it?",
        f"What problems does {main} solve in day-to-day operations?",
    ]
    questions += [f"Where does {k} fit in, and what does it change?" for k in kws[1:3]]
    questions.append("How long does a first implementation usually take, and what does it depend on?")
    if commercial:
        questions.append("What should a business look for when choosing a partner for this?")

    coverage = "does not cover it" if row["status"] == "Gap" else "covers it only briefly"
    return {
        "topic": str(row["label"]),
        "why_it_matters": (
            f"Competitors publish on this topic ({_plural(int(row['competitor_sections']), 'section')} across "
            f"{_plural(int(row['competitors_covering']), 'competitor site')}) while {client}'s blog {coverage}. "
            f"It maps to {client}'s service: \"{str(row['closest_service']).rstrip('.')}\"."
        ),
        "target_intent": row["intent"],
        "suggested_title": f"{topic_title}: A Practical Guide for Growing Businesses"[:70],
        "outline": outline,
        "questions_to_answer": questions,
    }


def _excerpts(row: pd.Series, sections: pd.DataFrame, clusters: pd.DataFrame, labels: dict[int, dict[str, Any]], k: int = 5) -> str:
    """Representative competitor excerpts (about 120 words each) with their URLs."""
    rep_ids = labels.get(int(row["cluster_id"]), {}).get("representative_section_ids", [])
    in_cluster = clusters.loc[clusters["cluster_id"] == row["cluster_id"], "section_id"]
    sec = sections.set_index("section_id")
    ordered = [s for s in rep_ids if s in sec.index] + [s for s in in_cluster if s not in rep_ids]
    picked = [s for s in ordered if sec.loc[s, "role"] == "competitor"][:k]
    return "\n".join(
        f'- [{sec.loc[s, "url"]}] "{sec.loc[s, "heading"]}": {" ".join(sec.loc[s, "text"].split()[:120])}' for s in picked
    )


def build_brief(
    row: pd.Series,
    sections: pd.DataFrame,
    clusters: pd.DataFrame,
    labels: dict[int, dict[str, Any]],
    client: str,
    services_summary: str,
    llm_client=None,
) -> dict[str, Any]:
    """One brief: LLM fields (validated, one retry) or template fields, plus code-filled fields."""
    from gaplens.llm import parse_json

    body, source = None, "template"
    if llm_client is not None:
        user = USER_TEMPLATE.format(
            client=client,
            services=services_summary,
            label=row["label"],
            keywords=row["top_keywords"],
            status=row["status"],
            reason=row["reason"],
            intent=row["intent"],
            excerpts=_excerpts(row, sections, clusters, labels),
        )
        for attempt in range(2):
            try:
                raw = llm_client.chat(SYSTEM_PROMPT, user, purpose=f"brief:{row['cluster_id']}")
                data = parse_json(raw)
                errors = validate_brief(data)
            except Exception as exc:
                data, errors = None, [str(exc)]
            if not errors:
                body, source = data, "llm"
                break
            log.warning("Brief for cluster %s invalid (attempt %d): %s", row["cluster_id"], attempt + 1, errors)
            user += "\n\nYour previous reply was invalid: " + "; ".join(errors) + ". Return only the JSON object."

    if body is None:
        body = template_brief(row, client)

    competitor_urls = [u for u in str(row["competitor_urls"]).split("|") if u][:5]
    return {
        "cluster_id": int(row["cluster_id"]),
        "topic": body["topic"],
        "why_it_matters": body["why_it_matters"],
        "target_intent": body["target_intent"],
        "suggested_title": body["suggested_title"],
        "outline": [{"h2": o["h2"], "h3": list(o.get("h3", []))} for o in body["outline"]],
        "questions_to_answer": list(body["questions_to_answer"]),
        "competitor_reference_urls": competitor_urls,
        "internal_link_from": row["closest_client_url"] or None,
        "opportunity_score": float(row["score"]),
        "status": row["status"],
        "source": source,
        "model": llm_client.model if source == "llm" else None,
    }


def run_briefs(
    cfg: dict[str, Any],
    gaps: pd.DataFrame,
    sections: pd.DataFrame,
    clusters: pd.DataFrame,
    labels: dict[int, dict[str, Any]],
    llm_client=None,
) -> list[dict[str, Any]]:
    """Generate briefs for the top-N scored gaps and write briefs.json."""
    from gaplens.config import client_site

    client = client_site(cfg)
    services = " ".join(open(cfg["paths"]["services_text"], encoding="utf-8").read().split())[:900]
    top = gaps.dropna(subset=["score"]).head(cfg["briefs"]["top_n"])
    briefs = [build_brief(r, sections, clusters, labels, client, services, llm_client) for _, r in top.iterrows()]
    cfg["paths"]["briefs"].write_text(json.dumps(briefs, indent=2, ensure_ascii=False))
    return briefs
