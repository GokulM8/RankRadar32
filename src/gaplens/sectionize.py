"""Split pages into heading-level sections (FR-03).

Rules:
1. A new section starts at every H2/H3 heading. Text before the first heading forms an
   intro section headed by the page title.
2. Paragraphs repeated on `boilerplate_min_pages` or more pages of the same site, and short
   call-to-action lines, are removed.
3. Sections shorter than `min_words` are merged into the next section (or the previous one
   at the end of a page). Sections longer than `max_words` are split at paragraph boundaries.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pandas as pd

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
CTA_RE = re.compile(
    r"\b(subscribe|newsletter|share this|follow us|book a (free )?(call|demo|consultation)|"
    r"contact us|get in touch|let'?s talk|schedule a call|read more|related posts?|table of contents)\b",
    re.IGNORECASE,
)


# Headings of page furniture rather than content. SKIP drops that section; END drops it and
# everything after it (related-post cards, author boxes and newsletter blocks sit at the end).
SKIP_HEADING_RE = re.compile(r"^(table of contents|contents|share( this)?( post| article)?|tags?|categories)\b", re.IGNORECASE)
END_HEADING_RE = re.compile(
    r"^(related (insights|posts?|articles?|reading|blogs?)|suggested reading|you may also like|written by|"
    r"about the author|join\b|subscribe\b|recent posts|latest (posts|articles)|more (posts|articles) from)",
    re.IGNORECASE,
)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _words(text: str) -> int:
    return len(text.split())


def parse_blocks(page: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Return [(heading, [paragraphs])] in document order, starting with the page-title intro."""
    sections: list[tuple[str, list[str]]] = [(page["title"], [])]
    for raw in page["text"].split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = HEADING_RE.match(line)
        if m:
            heading = m.group(2).strip("*_ ")
            level = len(m.group(1))
            if level == 1 and _norm(heading) == _norm(page["title"]):
                continue
            sections.append((heading, []))
        else:
            sections[-1][1].append(line)
    return sections


def find_boilerplate(pages: list[dict[str, Any]], min_pages: int) -> dict[str, set[str]]:
    """Per site, the normalised paragraphs that appear on at least `min_pages` distinct pages."""
    seen: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for page in pages:
        for _, paras in parse_blocks(page):
            for p in paras:
                seen[page["site"]][_norm(p)].add(page["page_id"])
    return {
        site: {p for p, ids in counts.items() if len(ids) >= min_pages}
        for site, counts in seen.items()
    }


def _is_noise(paragraph: str, boilerplate: set[str]) -> bool:
    n = _norm(paragraph)
    if not n or n in boilerplate:
        return True
    return _words(paragraph) < 25 and bool(CTA_RE.search(paragraph))


def _split_long(heading: str, paras: list[str], max_words: int) -> list[tuple[str, str]]:
    """Split a long section into chunks of at most ~max_words, at paragraph (then word) boundaries."""
    pieces: list[str] = []
    for p in paras:
        words = p.split()
        while len(words) > max_words:
            pieces.append(" ".join(words[:max_words]))
            words = words[max_words:]
        if words:
            pieces.append(" ".join(words))

    chunks: list[list[str]] = [[]]
    for p in pieces:
        if chunks[-1] and _words(" ".join(chunks[-1])) + _words(p) > max_words:
            chunks.append([])
        chunks[-1].append(p)
    if len(chunks) == 1:
        return [(heading, "\n".join(chunks[0]))]
    return [(f"{heading} (part {i + 1})", "\n".join(c)) for i, c in enumerate(chunks)]


def sectionize_page(page: dict[str, Any], boilerplate: set[str], min_words: int, max_words: int) -> list[dict[str, Any]]:
    """Turn one page into a list of section records."""
    blocks = []
    for heading, paras in parse_blocks(page):
        if END_HEADING_RE.match(heading.strip()):
            break
        paras = [p for p in paras if not _is_noise(p, boilerplate)]
        if paras and not SKIP_HEADING_RE.match(heading.strip()):
            blocks.append((heading, paras))
    if not blocks:
        return []

    # Merge short sections forward (the last one backward).
    merged: list[tuple[str, list[str]]] = []
    carry_heads: list[str] = []
    carry_paras: list[str] = []
    for heading, paras in blocks:
        heads = carry_heads + [heading]
        all_paras = carry_paras + paras
        if _words(" ".join(all_paras)) < min_words:
            carry_heads, carry_paras = heads, all_paras
            continue
        merged.append((" / ".join(heads), all_paras))
        carry_heads, carry_paras = [], []
    if carry_paras:
        if merged:
            h, ps = merged.pop()
            merged.append((" / ".join([h] + carry_heads), ps + carry_paras))
        else:
            merged.append((" / ".join(carry_heads), carry_paras))

    final: list[tuple[str, str]] = []
    for heading, paras in merged:
        final.extend(_split_long(heading, paras, max_words))

    return [
        {
            "section_id": f"{page['page_id']}-{i}",
            "page_id": page["page_id"],
            "url": page["url"],
            "site": page["site"],
            "role": page["role"],
            "page_title": page["title"],
            "heading": heading,
            "position": i,
            "text": text,
            "word_count": _words(text),
        }
        for i, (heading, text) in enumerate(final)
    ]


def sectionize(pages: list[dict[str, Any]], min_words: int, max_words: int, boilerplate_min_pages: int) -> pd.DataFrame:
    """Sectionize all pages; returns the sections table defined in docs/02_ARCHITECTURE.md."""
    boilerplate = find_boilerplate(pages, boilerplate_min_pages)
    rows: list[dict[str, Any]] = []
    for page in pages:
        rows.extend(sectionize_page(page, boilerplate.get(page["site"], set()), min_words, max_words))
    return pd.DataFrame(rows)


def run_sectionize(cfg: dict[str, Any]) -> pd.DataFrame:
    """Read pages.jsonl, write sections.parquet."""
    from gaplens.crawl import load_pages

    sc = cfg["sectionize"]
    df = sectionize(load_pages(cfg["paths"]["pages"]), sc["min_words"], sc["max_words"], sc["boilerplate_min_pages"])
    cfg["paths"]["sections"].parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cfg["paths"]["sections"], index=False)
    return df


def embedding_text(row: pd.Series) -> str:
    """The text that gets embedded for a section: heading plus body."""
    return f"{row['heading']}. {row['text']}"
