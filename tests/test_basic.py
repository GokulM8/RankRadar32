"""Basic tests: config, sectionizer, score range, gap status logic, JSON parsing, brief validation."""

import pandas as pd
import pytest

from rankradar.briefs import template_brief, validate_brief
from rankradar.config import load_config
from rankradar.gaps import classify, coverage
from rankradar.llm import parse_json
from rankradar.score import classify_intent, opportunity_score, perturbed_weights
from rankradar.sectionize import sectionize_page

WEIGHTS = {"relevance": 0.4, "competitor_strength": 0.25, "intent": 0.2, "effort": 0.15}


def test_config_loads():
    cfg = load_config("config.yaml")
    assert sum(cfg["scoring"]["weights"].values()) == pytest.approx(1.0)
    assert sum(s["role"] == "client" for s in cfg["sites"]) == 1
    assert cfg["paths"]["gaps"].is_absolute()


def _page(text: str) -> dict:
    return {"page_id": "p1", "url": "https://x.test/blog/a", "site": "X", "role": "client", "title": "Title", "text": text}


def test_sectionizer_splits_on_headings_and_merges_short():
    body = " ".join(["word"] * 80)
    text = f"Intro {body}\n\n## First\n\n{body}\n\n## Tiny\n\nshort bit\n\n## Second\n\n{body}"
    secs = sectionize_page(_page(text), set(), min_words=60, max_words=350)
    headings = [s["heading"] for s in secs]
    assert headings[0] == "Title"
    assert "Tiny / Second" in headings  # short section merged forward
    assert all(s["word_count"] >= 60 for s in secs)


def test_sectionizer_splits_long_sections_and_drops_boilerplate():
    long_body = "\n\n".join(" ".join(["alpha"] * 100) for _ in range(5))
    text = f"## Long\n\n{long_body}\n\nSubscribe to our newsletter today"
    secs = sectionize_page(_page(text), set(), min_words=60, max_words=200)
    assert len(secs) >= 3
    assert all(s["word_count"] <= 200 for s in secs)
    assert not any("newsletter" in s["text"] for s in secs)


@pytest.mark.parametrize(
    "rel,comp,intent,effort",
    [(0, 0, 0, 1), (1, 1, 1, 0), (0.5, 0.3, 0.7, 1), (1.2, 1, 1, -0.5)],
)
def test_score_within_bounds(rel, comp, intent, effort):
    s = opportunity_score(rel, comp, intent, effort, WEIGHTS)
    assert 0 <= s <= 100


def test_score_extremes():
    assert opportunity_score(1, 1, 1, 0, WEIGHTS) == 100
    assert opportunity_score(0, 0, 0, 1, WEIGHTS) == 0


def test_gap_status_logic():
    assert classify(0, 5, 0.0, 0.2, 3) == "Gap"
    assert classify(1, 9, 0.1, 0.2, 3) == "Weak spot"
    assert classify(1, 2, 0.33, 0.2, 3) == "Covered"
    assert classify(1, 2, 0.1, 0.2, 3) == "Covered"  # too few competitor sections for a weak spot
    assert classify(4, 0, 1.0, 0.2, 3) == "Client-only"


def test_coverage_on_toy_example():
    cfg = {"gaps": {"weak_share_threshold": 0.2, "min_competitor_sections": 3}}
    sections = pd.DataFrame(
        {
            "section_id": [f"s{i}" for i in range(10)],
            "site": ["C", "A", "B", "A", "C", "C", "A", "A", "A", "B"],
            "role": ["client", "competitor", "competitor", "competitor", "client", "client", "competitor", "competitor", "competitor", "competitor"],
            "url": [f"https://t/{i}" for i in range(10)],
        }
    )
    clusters = pd.DataFrame({"section_id": sections["section_id"], "cluster_id": [0, 0, 0, 1, 2, 2, 3, 3, 3, -1]})
    cov = coverage(sections, clusters, cfg).set_index("cluster_id")
    assert cov.loc[0, "status"] == "Covered"
    assert cov.loc[1, "status"] == "Gap"
    assert cov.loc[2, "status"] == "Client-only"
    assert cov.loc[3, "status"] == "Gap"
    assert cov.loc[0, "competitors_covering"] == 2
    assert -1 not in cov.index


def test_perturbed_weights_sum_to_one():
    w = perturbed_weights(WEIGHTS, "relevance", 0.1)
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["relevance"] == pytest.approx(0.5)


def test_intent_rules():
    rules = {"transactional": ["pricing", "hire", "cost"], "commercial": ["best", "vs", "tools"]}
    assert classify_intent("pricing and cost to hire an agency", rules) == "transactional"
    assert classify_intent("best tools compared: x vs y", rules) == "commercial"
    assert classify_intent("what is a vector database", rules) == "informational"


def test_parse_json_strips_think_and_fences():
    raw = '<think>hmm</think>\n```json\n{"topic": "AI agents"}\n```'
    assert parse_json(raw) == {"topic": "AI agents"}


def test_template_brief_is_valid():
    row = pd.Series(
        {"cluster_id": 3, "label": "ai voice agents", "top_keywords": "voice agents, call automation, ivr",
         "status": "Gap", "intent": "commercial", "competitor_sections": 6, "competitors_covering": 2,
         "closest_service": "AI voice agents for voice-driven communication."}
    )
    assert validate_brief(template_brief(row, "Cynbit")) == []


def test_inline_markdown_recovery_leaves_normal_headings_alone():
    from rankradar.crawl import recover_inline_markdown

    normal = "Intro text.\n\n## How to choose a vendor\n\nBody text here."
    assert recover_inline_markdown(normal) == normal
    flat = "Intro text here. ## Where approvals get stuck Most delays come from design."
    fixed = recover_inline_markdown(flat)
    assert "\n## Where approvals get stuck\n" in fixed
    assert "Most delays come from design." in fixed


class FakeLLM:
    """Returns queued replies in order, to exercise validation, retry and fallback."""

    model = "fake-model"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, system, user, purpose, max_tokens=None):
        return self.replies.pop(0)


def _gap_row():
    return pd.Series(
        {"cluster_id": 7, "label": "approval workflow automation", "top_keywords": "approvals, routing, escalation",
         "status": "Gap", "intent": "commercial", "competitor_sections": 9, "competitors_covering": 1,
         "client_share": 0.0, "reason": "Gap: ...", "score": 55.0, "closest_client_url": "https://c.test/blog/x",
         "closest_service": "LLM automation to automate manual data entry.", "competitor_urls": "https://a.test/1|https://a.test/2"}
    )


def test_brief_retries_once_then_uses_llm_output():
    from rankradar.briefs import build_brief

    good = ('{"topic": "Approval automation", "why_it_matters": "x", "target_intent": "commercial", '
            '"suggested_title": "t", "outline": [{"h2": "a", "h3": []}, {"h2": "b", "h3": ["c"]}], '
            '"questions_to_answer": ["q?"]}')
    sections = pd.DataFrame(columns=["section_id", "role", "url", "heading", "text"])
    clusters = pd.DataFrame(columns=["section_id", "cluster_id"])
    b = build_brief(_gap_row(), sections, clusters, {}, "Cynbit", "services", FakeLLM(["not json", good]))
    assert b["source"] == "llm" and b["topic"] == "Approval automation"
    assert b["competitor_reference_urls"] == ["https://a.test/1", "https://a.test/2"]  # filled by code, not the LLM


def test_brief_falls_back_to_template_after_two_failures():
    from rankradar.briefs import build_brief

    sections = pd.DataFrame(columns=["section_id", "role", "url", "heading", "text"])
    clusters = pd.DataFrame(columns=["section_id", "cluster_id"])
    b = build_brief(_gap_row(), sections, clusters, {}, "Cynbit", "services", FakeLLM(["{}", "{\"topic\": 1}"]))
    assert b["source"] == "template" and b["model"] is None


def test_copy_check_flags_verbatim_competitor_wording():
    from rankradar.briefs import copied_phrases

    source = "What are the processes that consume disproportionate manual effort every cycle in your team?"
    brief = {"topic": "Ops", "why_it_matters": "x", "suggested_title": "t", "outline": [],
             "questions_to_answer": ["What are the processes that consume disproportionate manual effort every cycle?"]}
    assert copied_phrases(brief, source)
    brief["questions_to_answer"] = ["Which manual processes take the most time each month?"]
    assert copied_phrases(brief, source) == []


def test_brief_with_copied_text_retries_then_falls_back():
    from rankradar.briefs import build_brief

    sections = pd.DataFrame(
        {"section_id": ["s1"], "role": ["competitor"], "url": ["https://a.test/1"], "heading": ["H"],
         "text": ["Approval workflows route purchase orders through thresholds escalations and audit trails for finance teams"]}
    )
    clusters = pd.DataFrame({"section_id": ["s1"], "cluster_id": [7]})
    copied = ('{"topic": "Approvals", "why_it_matters": "x", "target_intent": "commercial", "suggested_title": "t", '
              '"outline": [{"h2": "a", "h3": []}, {"h2": "b", "h3": []}], '
              '"questions_to_answer": ["Approval workflows route purchase orders through thresholds escalations and audit trails?"]}')
    b = build_brief(_gap_row(), sections, clusters, {}, "Cynbit", "services", FakeLLM([copied, copied]))
    assert b["source"] == "template"
