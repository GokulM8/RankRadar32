"""Evaluation: hand-label template, precision against labels, figures (FR-13).

Hand labels are never generated here. The template is written with a blank `is_real_gap`
column for a person to fill with 1 (real, worthwhile gap) or 0 (not a real gap).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Reference categorical palette (light mode), fixed order; noise is a muted neutral.
SITE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
NOISE_COLOR = "#b9b8b2"
INK, INK_MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#e7e6e1"
STATUS_ORDER = ["Gap", "Weak spot", "Covered", "Client-only"]


def site_colors(cfg: dict[str, Any]) -> dict[str, str]:
    """Client first, then competitors, in config order, mapped to fixed palette slots."""
    names = [s["name"] for s in sorted(cfg["sites"], key=lambda s: s["role"] != "client")]
    return {n: SITE_COLORS[i % len(SITE_COLORS)] for i, n in enumerate(names)}


def baseline_rank(gaps: pd.DataFrame) -> pd.DataFrame:
    """Naive baseline: scored clusters ranked by competitor section count only."""
    return gaps.dropna(subset=["score"]).sort_values(["competitor_sections", "competitors_covering"], ascending=False)


def labels_filled(path: Path) -> bool:
    """True if a label file exists and has at least one non-empty is_real_gap value."""
    if not path.exists():
        return False
    df = pd.read_csv(path)
    return "is_real_gap" in df and df["is_real_gap"].notna().any()


def write_label_template(gaps: pd.DataFrame, path: Path, k: int) -> bool:
    """Write the hand-label template (top-k by score plus top-k by baseline, so both can be scored).

    Never overwrites a file that already contains labels. Returns True if written.
    """
    if labels_filled(path):
        log.info("Labels already present in %s; not overwriting", path)
        return False
    scored = gaps.dropna(subset=["score"])
    ids = list(dict.fromkeys(scored.head(k)["cluster_id"].tolist() + baseline_rank(gaps).head(k)["cluster_id"].tolist()))
    t = scored.set_index("cluster_id").loc[ids].reset_index()
    t = t.sort_values("score", ascending=False)
    out = pd.DataFrame(
        {
            "cluster_id": t["cluster_id"],
            "label": t["label"],
            "status": t["status"],
            "score": t["score"],
            "top_keywords": t["top_keywords"],
            "sample_excerpt": t["sample_excerpt"],
            "competitor_urls": t["competitor_urls"].str.split("|").str[:2].str.join(" | "),
            "is_real_gap": "",
            "notes": "",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return True


def precision_at(ranked_ids: list[int], labels: dict[int, int], k: int) -> dict[str, Any]:
    """Precision@k over the labelled items among the top-k of a ranking."""
    top = ranked_ids[:k]
    judged = [labels[c] for c in top if c in labels]
    return {
        "k": k,
        "precision": round(float(np.mean(judged)), 4) if judged else None,
        "labelled": len(judged),
        "relevant": int(sum(judged)),
    }


def _precision_of(df: pd.DataFrame) -> dict[str, Any]:
    return {"n": int(len(df)), "real": int(df["is_real_gap"].sum()), "precision": round(float(df["is_real_gap"].mean()), 4) if len(df) else None}


def competitor_self_mention(sections: pd.DataFrame) -> pd.Series:
    """Diagnostic only (not part of the score): share of a cluster's competitor sections that name
    their own site, e.g. a Proeffico section containing "Proeffico". High values suggest self-promotion."""
    comp = sections[sections["role"] == "competitor"]
    first_word = comp["site"].str.split().str[0].str.lower()
    mentions = [fw in f"{h} {t}".lower() for fw, h, t in zip(first_word, comp["heading"], comp["text"])]
    comp = comp.assign(self_mention=mentions)
    return comp.groupby("cluster_id")["self_mention"].mean()


def label_metrics(
    gaps: pd.DataFrame, sections: pd.DataFrame, clusters: pd.DataFrame, path: Path, weights_used: dict[str, float] | None = None
) -> dict[str, Any] | None:
    """Precision@10/@25 of the opportunity score vs the competitor-count baseline, label provenance
    and a short error analysis. Returns None if no filled label file exists."""
    if not labels_filled(path):
        return None
    lab = pd.read_csv(path).dropna(subset=["is_real_gap"])
    lab["is_real_gap"] = lab["is_real_gap"].astype(int)
    labels = {int(r.cluster_id): int(r.is_real_gap) for r in lab.itertuples()}
    scored = gaps.dropna(subset=["score"]).reset_index(drop=True)
    scored["score_rank"] = np.arange(1, len(scored) + 1)
    score_rank = scored["cluster_id"].astype(int).tolist()
    base_rank = baseline_rank(gaps)["cluster_id"].astype(int).tolist()

    sec = sections.merge(clusters[["section_id", "cluster_id"]], on="section_id")
    self_mention = competitor_self_mention(sec)
    cols = ["cluster_id", "label", "status", "score", "score_rank", "effort", "closest_client_similarity", "relevance", "competitor_strength", "intent"]
    joined = scored[cols].merge(lab[["cluster_id", "is_real_gap", "notes"] + [c for c in ("confidence", "label_source") if c in lab]], on="cluster_id")
    joined["competitor_self_mention"] = joined["cluster_id"].map(self_mention).fillna(0).round(3)

    def rows(df: pd.DataFrame) -> list[dict[str, Any]]:
        keep = ["cluster_id", "label", "score_rank", "score", "status", "effort", "closest_client_similarity", "competitor_self_mention", "notes"]
        return df[keep].to_dict("records")

    provenance: dict[str, Any] = {}
    if "label_source" in lab:
        provenance["label_source"] = lab["label_source"].value_counts().to_dict()
        provenance["human_overrides"] = int((lab["label_source"] == "human_override").sum())
    if "confidence" in lab:
        provenance["confidence"] = lab["confidence"].value_counts().to_dict()

    confident = {int(r.cluster_id): int(r.is_real_gap) for r in lab.itertuples() if getattr(r, "confidence", "high") != "low"}

    # Post-hoc ablation: drop one component at a time (other weights rescaled to sum to 1).
    # Diagnostic only; the shipped weights are not tuned on these labels.
    from rankradar.score import apply_scores

    weights = weights_used or {}
    ablation = {}
    for drop in weights:
        rest = {k: v for k, v in weights.items() if k != drop}
        w = {**{k: v / sum(rest.values()) for k, v in rest.items()}, drop: 0.0}
        rank = gaps.assign(_s=apply_scores(gaps, w)).dropna(subset=["_s"]).sort_values("_s", ascending=False)["cluster_id"].astype(int).tolist()
        ablation[f"without_{drop}"] = {f"p@{k}": precision_at(rank, labels, k) for k in (10, 25)}
    return {
        "label_file": path.name,
        "n_labelled": len(labels),
        "n_real_gaps": int(sum(labels.values())),
        "n_not_gaps": int(len(labels) - sum(labels.values())),
        "provenance": provenance,
        "opportunity_score": {f"p@{k}": precision_at(score_rank, labels, k) for k in (10, 25)},
        "baseline_competitor_count": {f"p@{k}": precision_at(base_rank, labels, k) for k in (10, 25)},
        "excluding_low_confidence": {
            "opportunity_score": {f"p@{k}": precision_at(score_rank, confident, k) for k in (10, 25)},
            "baseline_competitor_count": {f"p@{k}": precision_at(base_rank, confident, k) for k in (10, 25)},
        },
        "ablation_post_hoc": ablation,
        "error_analysis": {
            "top10_labelled_0": rows(joined[(joined["score_rank"] <= 10) & (joined["is_real_gap"] == 0)]),
            "rank_gt_15_labelled_1": rows(joined[(joined["score_rank"] > 15) & (joined["is_real_gap"] == 1)]),
            "precision_by_effort": {
                "effort_0_expand_existing": _precision_of(joined[joined["effort"] == 0]),
                "effort_1_new_page": _precision_of(joined[joined["effort"] == 1]),
            },
            "mean_closest_client_similarity": {
                "labelled_1": round(float(joined.loc[joined["is_real_gap"] == 1, "closest_client_similarity"].mean()), 4),
                "labelled_0": round(float(joined.loc[joined["is_real_gap"] == 0, "closest_client_similarity"].mean()), 4),
            },
            "competitor_self_mention": {
                "mean_labelled_1": round(float(joined.loc[joined["is_real_gap"] == 1, "competitor_self_mention"].mean()), 4),
                "mean_labelled_0": round(float(joined.loc[joined["is_real_gap"] == 0, "competitor_self_mention"].mean()), 4),
                "clusters_ge_0_3": _precision_of(joined[joined["competitor_self_mention"] >= 0.3]),
            },
        },
    }


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def make_figures(cfg: dict[str, Any], sections: pd.DataFrame, clusters: pd.DataFrame, gaps: pd.DataFrame) -> list[str]:
    """Write the UMAP scatter, coverage bar chart and score distribution as PNGs."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir: Path = cfg["paths"]["figures"]
    out_dir.mkdir(parents=True, exist_ok=True)
    colors = site_colors(cfg)
    client_name = next(s["name"] for s in cfg["sites"] if s["role"] == "client")
    written = []
    plt.rcParams.update({"font.size": 10, "text.color": INK, "axes.labelcolor": INK_MUTED, "figure.facecolor": SURFACE})

    # 1. Topic map: UMAP 2-D, coloured by site; noise drawn first, small and muted.
    df = sections[["section_id", "site"]].merge(clusters, on="section_id")
    fig, ax = plt.subplots(figsize=(8, 6))
    noise = df[df["cluster_id"] < 0]
    ax.scatter(noise["x"], noise["y"], s=10, c=NOISE_COLOR, linewidths=0, label="Noise (no topic)")
    for site, color in colors.items():
        pts = df[(df["site"] == site) & (df["cluster_id"] >= 0)]
        if len(pts):
            ax.scatter(pts["x"], pts["y"], s=22, c=color, edgecolors=SURFACE, linewidths=0.8, label=site)
    ax.set_xticks([]), ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_facecolor(SURFACE)
    ax.set_title("Topic map: sections by site (UMAP 2-D)", loc="left", fontsize=12, color=INK)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1, 1))
    fig.tight_layout()
    fig.savefig(out_dir / "topic_map.png", dpi=150)
    plt.close(fig)
    written.append("topic_map.png")

    # 2. Coverage: number of clusters per status.
    counts = gaps["status"].value_counts().reindex(STATUS_ORDER, fill_value=0)
    fig, ax = plt.subplots(figsize=(7, 3.8))
    bars = ax.bar(counts.index, counts.values, color=SITE_COLORS[0], width=0.6)
    for b, v in zip(bars, counts.values):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v}", ha="center", va="bottom", fontsize=9, color=INK)
    _style(ax)
    ax.set_ylabel("Topic clusters")
    ax.set_title(f"Topic coverage status for {client_name}", loc="left", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(out_dir / "coverage_status.png", dpi=150)
    plt.close(fig)
    written.append("coverage_status.png")

    # 3. Score distribution for scored clusters.
    scores = gaps["score"].dropna()
    fig, ax = plt.subplots(figsize=(7, 3.8))
    if len(scores):
        ax.hist(scores, bins=np.arange(0, 105, 5), color=SITE_COLORS[0], edgecolor=SURFACE, linewidth=2)
    _style(ax)
    ax.set_xlabel("Opportunity score (0–100)")
    ax.set_ylabel("Clusters")
    ax.set_title("Opportunity score distribution (Gaps and Weak spots)", loc="left", fontsize=12, color=INK)
    fig.tight_layout()
    fig.savefig(out_dir / "score_distribution.png", dpi=150)
    plt.close(fig)
    written.append("score_distribution.png")
    return written
