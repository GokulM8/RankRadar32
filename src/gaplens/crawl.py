"""Polite crawler and main-text extraction (FR-01, FR-02).

For each configured site: check robots.txt, discover post URLs from the listing pages,
fetch each post with a fixed delay and a clear User-Agent, and extract title, headings
and main text. Results go to `pages.jsonl`; every skipped or failed URL goes to the crawl log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
import trafilatura
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*\S)\s*$")


def page_id(url: str) -> str:
    """Stable short id for a URL."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def normalize_url(url: str) -> str:
    """Drop query string and fragment, and any trailing slash on the path."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


class PoliteSession:
    """A requests session that enforces a minimum delay between requests."""

    def __init__(self, user_agent: str, delay: float, timeout: float) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.8"})
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self._last = 0.0

    def get(self, url: str) -> requests.Response:
        """GET a URL, sleeping first if the previous request was too recent."""
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            return self.session.get(url, timeout=self.timeout, allow_redirects=True)
        finally:
            self._last = time.monotonic()


def load_robots(session: PoliteSession, base_url: str) -> RobotFileParser:
    """Fetch and parse robots.txt with our own User-Agent.

    Follows RFC 9309: 4xx (other than 401/403) means no restrictions; 401/403 or a
    server error means we treat the whole site as disallowed.
    """
    parts = urlsplit(base_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = RobotFileParser(robots_url)
    try:
        resp = session.get(robots_url)
    except requests.RequestException as exc:
        log.warning("robots.txt unreachable for %s (%s); treating site as disallowed", parts.netloc, exc)
        rp.disallow_all = True
        rp.gaplens_note = f"robots.txt unreachable ({type(exc).__name__}); treated as full disallow per RFC 9309"
        return rp
    rp.gaplens_note = f"robots.txt HTTP {resp.status_code}"
    if resp.status_code in (401, 403) or resp.status_code >= 500:
        rp.disallow_all = True
    elif resp.status_code >= 400:
        rp.allow_all = True
    else:
        rp.parse(resp.text.splitlines())
    return rp


def discover_post_urls(
    session: PoliteSession,
    rp: RobotFileParser,
    site: dict[str, Any],
    exclude_patterns: list[str],
    cap: int,
    log_event,
) -> list[str]:
    """Collect post URLs from a site's listing pages, in listing order, up to `cap`."""
    pattern = re.compile(site["post_url_pattern"])
    found: list[str] = []
    seen: set[str] = set()
    for listing in site["listing_urls"]:
        if not rp.can_fetch(session.user_agent, listing):
            log_event(listing, "blocked_by_robots", "listing page")
            continue
        try:
            resp = session.get(listing)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log_event(listing, "fetch_error", str(exc))
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            url = normalize_url(urljoin(resp.url, a["href"]))
            if url in seen or not pattern.match(url) or any(p in url for p in exclude_patterns):
                continue
            seen.add(url)
            found.append(url)
        if len(found) >= cap:
            break
    return found[:cap]


def _markdown_from_soup(soup: BeautifulSoup) -> str:
    """Fallback extractor: walk headings, paragraphs and list items of the main content."""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]):
        tag.decompose()
    # Pages may contain several <article>/<main> elements (e.g. related-post cards); take the one
    # with the most paragraph text.
    candidates = soup.find_all(["article", "main"]) or [soup.body or soup]
    root = max(candidates, key=lambda el: sum(len(p.get_text(" ", strip=True).split()) for p in el.find_all("p")))
    lines: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "p", "li"]):
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text:
            continue
        if el.name in ("h1", "h2", "h3"):
            lines.append(f"{'#' * int(el.name[1])} {text}")
        elif el.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n\n".join(lines)


INLINE_HEADING_RE = re.compile(r"\s(#{2,3})\s+")


def _split_inline_heading(level: str, rest: str) -> str:
    """Turn 'Where approvals get stuck Most approval delays...' into a heading line and a body.

    The heading ends at the first lowercase word followed by a capitalised word, within 14 words.
    """
    words = rest.split()
    cut = next(
        (i for i in range(1, min(len(words), 14)) if words[i - 1][:1].islower() and words[i][:1].isupper()),
        min(len(words), 8),
    )
    return f"\n\n{level} {' '.join(words[:cut])}\n\n{' '.join(words[cut:])}"


def recover_inline_markdown(text: str) -> str:
    """Some sites render raw markdown flattened onto one line ("... ## Heading Body ..."). Restore line breaks."""
    text = text.replace("\\*", "*").replace("\\_", "_").replace("\\-", "-")
    if not INLINE_HEADING_RE.search(text):
        return text
    parts = INLINE_HEADING_RE.split(text)
    out = parts[0]
    for level, rest in zip(parts[1::2], parts[2::2]):
        out += _split_inline_heading(level, rest)
    # Flattened bullet lists: " - **Item.**" -> new line
    return re.sub(r"\s-\s(?=\*\*)", "\n- ", out)


def extract_page(html: str, url: str) -> dict[str, Any]:
    """Extract title, H1–H3 headings and main text (markdown-like) from a post's HTML."""
    text = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_formatting=True,
        include_comments=False,
        include_tables=False,
        include_links=False,
        include_images=False,
        favor_recall=True,
    ) or ""
    method = "trafilatura"
    soup = BeautifulSoup(html, "html.parser")

    def n_headings(t: str) -> int:
        return sum(1 for line in t.splitlines() if HEADING_RE.match(line))

    # Prefer the BeautifulSoup fallback when trafilatura missed most of the text, or kept clearly
    # fewer headings while the fallback has comparable text.
    fallback = _markdown_from_soup(BeautifulSoup(html, "html.parser"))
    t_words, f_words = len(text.split()), len(fallback.split())
    if (t_words < 150 and f_words > t_words) or (
        n_headings(fallback) >= n_headings(text) + 2 and f_words >= 0.7 * t_words
    ):
        text, method = fallback, "beautifulsoup"
    text = recover_inline_markdown(text)

    headings = [
        {"level": len(m.group(1)), "text": m.group(2).strip("*_ ")}
        for m in (HEADING_RE.match(l) for l in text.splitlines())
        if m
    ]
    # The post's H1 is the cleanest title (no "| Site Blog" suffix); fall back to metadata.
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta and meta.title else "") or (soup.title.get_text(strip=True) if soup.title else "")
    return {
        "title": title.strip(),
        "headings": headings,
        "text": text.strip(),
        "word_count": len(text.split()),
        "extractor": method,
    }


def crawl_site(site: dict[str, Any], crawl_cfg: dict[str, Any], log_event) -> Iterator[dict[str, Any]]:
    """Crawl one site and yield page records. Yields nothing if robots.txt blocks it."""
    session = PoliteSession(crawl_cfg["user_agent"], crawl_cfg["delay_seconds"], crawl_cfg["timeout_seconds"])
    rp = load_robots(session, site["listing_urls"][0])
    robots_delay = rp.crawl_delay(session.user_agent)
    if robots_delay:
        session.delay = max(session.delay, float(robots_delay))

    if not rp.can_fetch(session.user_agent, site["listing_urls"][0]):
        note = getattr(rp, "gaplens_note", "")
        log_event(site["listing_urls"][0], "site_skipped_robots", f"{note}; crawling not permitted for {session.user_agent!r}")
        log.warning("Skipping %s: %s", site["name"], note)
        return

    urls = discover_post_urls(session, rp, site, crawl_cfg["exclude_patterns"], crawl_cfg["max_pages_per_site"], log_event)
    log.info("%s: discovered %d post URLs", site["name"], len(urls))
    for url in urls:
        if not rp.can_fetch(session.user_agent, url):
            log_event(url, "blocked_by_robots", "")
            continue
        try:
            resp = session.get(url)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log_event(url, "fetch_error", str(exc))
            continue
        content_type = resp.headers.get("Content-Type", "text/html")
        if "text/html" not in content_type:
            log_event(url, "not_html", content_type)
            continue
        if "charset" not in content_type.lower():
            resp.encoding = resp.apparent_encoding or "utf-8"  # requests defaults to ISO-8859-1 otherwise
        page = extract_page(resp.text, url)
        if page["word_count"] < 100:
            log_event(url, "too_little_text", f"{page['word_count']} words")
            continue
        yield {
            "page_id": page_id(url),
            "url": url,
            "site": site["name"],
            "role": site["role"],
            "title": page["title"],
            "headings": page["headings"],
            "text": page["text"],
            "word_count": page["word_count"],
            "extractor": page["extractor"],
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


def run_crawl(cfg: dict[str, Any]) -> dict[str, int]:
    """Crawl all configured sites; write pages.jsonl and the crawl log. Returns page counts per site."""
    pages_path: Path = cfg["paths"]["pages"]
    log_path: Path = cfg["paths"]["crawl_log"]
    pages_path.parent.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    with open(pages_path, "w", encoding="utf-8") as pages_f, open(log_path, "w", encoding="utf-8") as log_f:
        for site in cfg["sites"]:

            def log_event(url: str, event: str, detail: str, _site: str = site["name"]) -> None:
                log_f.write(json.dumps({"site": _site, "url": url, "event": event, "detail": detail}) + "\n")
                log_f.flush()

            counts[site["name"]] = 0
            for record in crawl_site(site, cfg["crawl"], log_event):
                pages_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                pages_f.flush()
                counts[site["name"]] += 1
            log.info("%s: saved %d pages", site["name"], counts[site["name"]])
    return counts


def load_pages(path: Path) -> list[dict[str, Any]]:
    """Read pages.jsonl into a list of dicts."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


if __name__ == "__main__":
    from gaplens.config import load_config

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    counts = run_crawl(load_config())
    for name, n in counts.items():
        print(f"{name:25s} {n:4d} pages")
