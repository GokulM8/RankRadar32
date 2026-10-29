"""Cluster labelling (FR-06).

Keywords are always computed: class-based TF-IDF picks n-grams that are distinctive for a
cluster compared with the other clusters, and KeyBERT re-ranks those candidates by semantic
closeness to the cluster's text (with MMR for diversity). If an LLM is available, it also
writes a short human-readable topic name from the most representative sections.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer, ENGLISH_STOP_WORDS

from gaplens.sectionize import embedding_text

log = logging.getLogger(__name__)

# Words that appear everywhere in agency blogs and say nothing about the topic.
DOMAIN_STOP_WORDS = {
    "business", "businesses", "company", "companies", "use", "using", "used", "help", "helps",
    "new", "way", "ways", "make", "like", "need", "needs", "also", "just", "including", "based",
    "part", "2023", "2024", "2025", "2026",
}
STOP_WORDS = sorted(ENGLISH_STOP_WORDS | DOMAIN_STOP_WORDS)

LABEL_SYSTEM = (
    "You name topic clusters for an SEO content strategist. "
    "Given excerpts from blog sections that belong to one topic, reply with JSON only: "
    '{"topic": "<a specific topic name of 2 to 6 words>"}. '
    "Use plain words a marketer would search for. Do not add commentary."
)


def representative_indices(embeddings: np.ndarray, idx: np.ndarray, k: int) -> np.ndarray:
    """Indices (into the full matrix) of the k sections closest to the cluster centroid."""
    vecs = embeddings[idx]
    centroid = vecs.mean(axis=0)
    centroid /= np.linalg.norm(centroid) + 1e-12
    order = np.argsort(-(vecs @ centroid))
    return idx[order[:k]]


def ctfidf_candidates(docs: dict[int, str], top_n: int = 30, extra_stop_words: set[str] | None = None) -> dict[int, list[str]]:
    """Class-based TF-IDF: per cluster, the n-grams most distinctive versus other clusters."""
    ids = list(docs)
    stop = sorted(set(STOP_WORDS) | (extra_stop_words or set()))
    vec = CountVectorizer(ngram_range=(1, 3), stop_words=stop, min_df=1, token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-]+\b")
    counts = vec.fit_transform([docs[i] for i in ids]).astype(float)
    tf = counts.multiply(1.0 / (counts.sum(axis=1) + 1e-12)).tocsr()
    avg_words = counts.sum() / len(ids)
    idf = np.log(1 + avg_words / (np.asarray(counts.sum(axis=0)).ravel() + 1e-12))
    scores = tf.multiply(idf).tocsr()
    vocab = np.array(vec.get_feature_names_out())
    out: dict[int, list[str]] = {}
    for row, cid in enumerate(ids):
        r = scores.getrow(row).toarray().ravel()
        top = np.argsort(-r)[:top_n]
        out[cid] = [vocab[j] for j in top if r[j] > 0]
    return out


def keywords_for_clusters(docs: dict[int, str], embed_model, top_k: int, extra_stop_words: set[str] | None = None) -> dict[int, list[str]]:
    """Distinctive keywords per cluster (c-TF-IDF candidates re-ranked by KeyBERT)."""
    candidates = ctfidf_candidates(docs, extra_stop_words=extra_stop_words)
    try:
        from keybert import KeyBERT

        kb = KeyBERT(model=embed_model)
    except Exception as exc:  # KeyBERT is a nicety; c-TF-IDF alone is a valid fallback
        log.warning("KeyBERT unavailable (%s); using c-TF-IDF keywords only", exc)
        return {cid: c[:top_k] for cid, c in candidates.items()}

    out: dict[int, list[str]] = {}
    for cid, doc in docs.items():
        cands = candidates.get(cid) or []
        if len(cands) <= top_k:
            out[cid] = cands
            continue
        kws = kb.extract_keywords(doc[:20000], candidates=cands, top_n=top_k, use_mmr=True, diversity=0.5)
        out[cid] = [k for k, _ in kws]
    return out


def llm_topic_name(client, excerpts: list[str], keywords: list[str], cluster_id: int) -> str | None:
    """Ask the LLM for a short topic name; None on any failure."""
    from gaplens.llm import parse_json

    user = (
        f"Keywords: {', '.join(keywords)}\n\nExcerpts:\n"
        + "\n\n".join(f"- {e[:500]}" for e in excerpts)
    )
    try:
        data = parse_json(client.chat(LABEL_SYSTEM, user, purpose=f"label:{cluster_id}", max_tokens=60))
        topic = str(data.get("topic", "")).strip().strip('"')
        return topic if 0 < len(topic.split()) <= 10 else None
    except Exception as exc:
        log.warning("LLM label failed for cluster %d: %s", cluster_id, exc)
        return None


def run_label(
    cfg: dict[str, Any],
    sections: pd.DataFrame,
    clusters: pd.DataFrame,
    embeddings: np.ndarray,
    llm_client=None,
) -> dict[int, dict[str, Any]]:
    """Label every non-noise cluster; write cluster_labels.json and return the mapping."""
    from gaplens.embed import load_model

    lc = cfg["labeling"]
    labels = clusters["cluster_id"].to_numpy()
    texts = np.array([embedding_text(r) for _, r in sections.iterrows()], dtype=object)
    cluster_ids = sorted(int(c) for c in set(labels) if c >= 0)
    docs = {cid: " ".join(texts[labels == cid]) for cid in cluster_ids}

    model, _ = load_model(cfg["embedding"]["model"], cfg["embedding"].get("fallback_model"))
    # Site names are not topics: keep them out of keywords.
    brand_words = {w.lower() for s in cfg["sites"] for w in s["name"].split()} | {"technologies", "technology"}
    kws = keywords_for_clusters(docs, model, lc["top_keywords"], brand_words)

    result: dict[int, dict[str, Any]] = {}
    for cid in cluster_ids:
        idx = np.where(labels == cid)[0]
        rep = representative_indices(embeddings, idx, lc["representative_sections"])
        keyword_label = ", ".join(kws[cid][:3]) if kws[cid] else f"cluster {cid}"
        name = llm_topic_name(llm_client, [texts[i] for i in rep], kws[cid], cid) if llm_client else None
        result[cid] = {
            "keywords": kws[cid],
            "label": name or keyword_label,
            "label_source": "llm" if name else "keywords",
            "representative_section_ids": sections["section_id"].iloc[rep].tolist(),
        }
    cfg["paths"]["cluster_labels"].write_text(json.dumps({str(k): v for k, v in result.items()}, indent=2))
    return result


def load_labels(path) -> dict[int, dict[str, Any]]:
    """Read cluster_labels.json with integer keys."""
    with open(path, encoding="utf-8") as f:
        return {int(k): v for k, v in json.load(f).items()}
