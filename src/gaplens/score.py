"""Transparent opportunity scoring for Gap and Weak-spot clusters (FR-09).

    score = 100 * ( w_rel  * relevance
                  + w_comp * competitor_strength
                  + w_int  * intent
                  + w_eff  * (1 - effort) )

All components are in [0, 1]. The score is a prioritisation aid, not a ranking prediction.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from gaplens.gaps import GAP, WEAK

COMPONENTS = ("relevance", "competitor_strength", "intent", "effort")


def opportunity_score(relevance: float, competitor_strength: float, intent: float, effort: float, weights: dict[str, float]) -> float:
    """Weighted score in [0, 100]. Lower effort scores higher."""
    s = (
        weights["relevance"] * relevance
        + weights["competitor_strength"] * competitor_strength
        + weights["intent"] * intent
        + weights["effort"] * (1.0 - effort)
    )
    return round(100.0 * float(np.clip(s, 0.0, 1.0)), 2)


def classify_intent(text: str, rules: dict[str, list[str]]) -> str:
    """Keyword-rule intent: transactional > commercial > informational, by number of rule hits."""
    text = text.lower()
    hits = {
        intent: sum(len(re.findall(rf"\b{re.escape(term.lower())}\b", text)) for term in terms)
        for intent, terms in rules.items()
    }
    # Require transactional cues to outnumber commercial ones; otherwise prefer commercial.
    if hits.get("transactional", 0) >= 2 and hits["transactional"] >= hits.get("commercial", 0):
        return "transactional"
    if hits.get("commercial", 0) >= 2 or hits.get("transactional", 0) >= 1:
        return "commercial"
    return "informational"


def load_service_texts(path) -> list[str]:
    """Service description sentences from the client's services file (one embedding each)."""
    text = open(path, encoding="utf-8").read()
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.lower().startswith("cynbit technologies services")]
    sentences: list[str] = []
    for line in lines:
        sentences.extend(s.strip() for s in re.split(r"(?<=\.)\s+", line) if len(s.split()) >= 4)
    return sentences


def effort_threshold(embeddings: np.ndarray, cluster_ids: np.ndarray, cfg: dict[str, Any]) -> float:
    """Similarity above which a client section counts as already covering a topic.

    With `effort_similarity_threshold: auto`, this is a low quantile of member-to-centroid similarity
    over all clustered sections: the client is "close" if its nearest section is as close to the topic
    as a typical cluster member. A number in the config is used as-is.
    """
    sc = cfg["scoring"]
    if sc["effort_similarity_threshold"] != "auto":
        return float(sc["effort_similarity_threshold"])
    sims = []
    for cid in set(cluster_ids.tolist()) - {-1}:
        vecs = embeddings[cluster_ids == cid]
        centroid = vecs.mean(axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-12
        sims.extend((vecs @ centroid).tolist())
    return round(float(np.quantile(sims, sc.get("effort_member_quantile", 0.25))), 4)


def n_competitors_crawled(sections: pd.DataFrame) -> int:
    """Competitors that actually contributed sections (skipped sites do not count)."""
    return int(sections.loc[sections["role"] == "competitor", "site"].nunique())


def _minmax(x: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(x)), float(np.max(x))
    return np.zeros_like(x) if hi - lo < 1e-9 else (x - lo) / (hi - lo)


def compute_components(
    cov: pd.DataFrame,
    sections: pd.DataFrame,
    clusters: pd.DataFrame,
    embeddings: np.ndarray,
    service_vecs: np.ndarray,
    service_texts: list[str],
    labels: dict[int, dict[str, Any]],
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """Add relevance, competitor_strength, intent, effort and closest-client-page columns."""
    sc = cfg["scoring"]
    n_competitors = n_competitors_crawled(sections)
    cid_arr = clusters["cluster_id"].to_numpy()
    threshold = effort_threshold(embeddings, cid_arr, cfg)
    client_mask = (sections["role"] == "client").to_numpy()
    client_idx = np.where(client_mask)[0]

    raw_rel, best_service, eff, close_url, close_sim, intents, excerpts = [], [], [], [], [], [], []
    for cid in cov["cluster_id"]:
        idx = np.where(cid_arr == cid)[0]
        centroid = embeddings[idx].mean(axis=0)
        centroid /= np.linalg.norm(centroid) + 1e-12

        sims = service_vecs @ centroid
        raw_rel.append(float(sims.max()))
        best_service.append(service_texts[int(sims.argmax())])

        if len(client_idx):
            csims = embeddings[client_idx] @ centroid
            j = int(csims.argmax())
            close_sim.append(round(float(csims[j]), 4))
            close_url.append(sections["url"].iloc[client_idx[j]])
        else:
            close_sim.append(0.0)
            close_url.append("")
        eff.append(0.0 if close_sim[-1] >= threshold else 1.0)

        lab = labels.get(int(cid), {})
        intent_text = " ".join(
            [lab.get("label", ""), " ".join(lab.get("keywords", []))]
            + sections["heading"].iloc[idx].tolist()
            + sections["page_title"].iloc[idx].drop_duplicates().tolist()
        )
        intents.append(classify_intent(intent_text, sc["intent_rules"]))

        rep = lab.get("representative_section_ids", [])
        rep_text = sections.set_index("section_id").loc[rep[0], "text"] if rep else sections["text"].iloc[idx[0]]
        excerpts.append(" ".join(rep_text.split()[:60]))

    out = cov.copy()
    out["relevance_raw"] = np.round(raw_rel, 4)
    out["relevance"] = np.round(_minmax(np.array(raw_rel)), 4)
    out["closest_service"] = best_service
    comp_sections_norm = np.log1p(out["competitor_sections"]) / np.log1p(max(out["competitor_sections"].max(), 1))
    out["competitor_strength"] = np.round(
        0.5 * out["competitors_covering"] / max(n_competitors, 1) + 0.5 * comp_sections_norm, 4
    )
    out["intent"] = intents
    out["intent_score"] = [sc["intent_scores"][i] for i in intents]
    out["effort"] = eff
    out["closest_client_url"] = close_url
    out["closest_client_similarity"] = close_sim
    out["sample_excerpt"] = excerpts
    out.attrs.update({"effort_threshold": threshold, "n_competitors": n_competitors})
    out["label"] = [labels.get(int(c), {}).get("label", f"cluster {c}") for c in out["cluster_id"]]
    out["top_keywords"] = [", ".join(labels.get(int(c), {}).get("keywords", [])) for c in out["cluster_id"]]
    return out


def apply_scores(df: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Score Gap and Weak-spot rows; other rows get NaN."""
    scorable = df["status"].isin([GAP, WEAK])
    scores = [
        opportunity_score(r.relevance, r.competitor_strength, r.intent_score, r.effort, weights) if ok else np.nan
        for r, ok in zip(df.itertuples(), scorable)
    ]
    return pd.Series(scores, index=df.index)


def _level(x: float) -> str:
    return "high" if x >= 0.67 else "medium" if x >= 0.33 else "low"


def reason(row: pd.Series, client_name: str, n_competitors: int) -> str:
    """Plain-language explanation of one row's score."""
    if row["status"] not in (GAP, WEAK):
        return f"{row['status']}: no score ({row['client_sections']} {client_name} vs {row['competitor_sections']} competitor sections)."
    cover = (
        f"none on {client_name}"
        if row["status"] == GAP
        else f"only {row['client_sections']} on {client_name} ({row['client_share']:.0%} share)"
    )
    effort = (
        f"expand the existing page {row['closest_client_url']} (similarity {row['closest_client_similarity']:.2f})"
        if row["effort"] == 0
        else f"needs a new page (closest {client_name} page similarity {row['closest_client_similarity']:.2f})"
    )
    return (
        f"{row['status']}: {row['competitor_sections']} competitor sections from "
        f"{row['competitors_covering']} of {n_competitors} competitors, {cover}. "
        f"{_level(row['relevance']).capitalize()} relevance to {client_name}'s services "
        f"(closest: \"{row['closest_service'][:80]}\"). "
        f"{row['intent'].capitalize()} intent. Effort: {effort}."
    )


def perturbed_weights(weights: dict[str, float], key: str, delta: float) -> dict[str, float] | None:
    """Shift one weight by delta and rescale the others so the total stays 1. None if invalid."""
    new_val = weights[key] + delta
    if not 0.0 <= new_val <= 1.0:
        return None
    rest = {k: v for k, v in weights.items() if k != key}
    rest_total = sum(rest.values())
    scale = (1.0 - new_val) / rest_total if rest_total else 0.0
    return {key: new_val, **{k: v * scale for k, v in rest.items()}}


def sensitivity(df: pd.DataFrame, weights: dict[str, float], delta: float, top_k: int = 10) -> dict[str, Any]:
    """Overlap of the top-k under each ±delta weight shift with the baseline top-k."""
    base = df.assign(_s=apply_scores(df, weights)).dropna(subset=["_s"]).nlargest(top_k, "_s")["cluster_id"]
    base_set = set(base)
    k = len(base_set)
    results = []
    for key in weights:
        for d in (-delta, delta):
            w = perturbed_weights(weights, key, d)
            if w is None:
                continue
            top = set(df.assign(_s=apply_scores(df, w)).dropna(subset=["_s"]).nlargest(top_k, "_s")["cluster_id"])
            results.append({"weight": key, "delta": round(d, 2), "top_k_overlap": len(top & base_set), "of": k})
    overlaps = [r["top_k_overlap"] for r in results]
    return {
        "top_k": top_k,
        "delta": delta,
        "perturbations": results,
        "mean_overlap": round(float(np.mean(overlaps)), 2) if overlaps else None,
        "min_overlap": int(min(overlaps)) if overlaps else None,
    }


def run_score(cfg: dict[str, Any], scored: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Compute scores and reasons, sort, write gaps.csv; return (table, sensitivity results)."""
    from gaplens.config import client_site

    weights = cfg["scoring"]["weights"]
    n_comp = scored.attrs.get("n_competitors") or sum(1 for s in cfg["sites"] if s["role"] == "competitor")
    df = scored.copy()
    df["score"] = apply_scores(df, weights)
    df["reason"] = [reason(r, client_site(cfg), n_comp) for _, r in df.iterrows()]
    df = df.sort_values(["score", "competitor_sections"], ascending=[False, False], na_position="last").reset_index(drop=True)

    columns = [
        "cluster_id", "label", "top_keywords", "status", "n_sections", "client_sections", "competitor_sections",
        "competitors_covering", "client_share", "relevance", "relevance_raw", "competitor_strength", "intent",
        "intent_score", "effort", "score", "reason", "closest_client_url", "closest_client_similarity",
        "closest_service", "competitor_urls", "sites", "sample_excerpt",
    ]
    df = df[columns]
    df.to_csv(cfg["paths"]["gaps"], index=False)
    sens = sensitivity(df, weights, cfg["scoring"]["sensitivity_delta"])
    return df, sens
