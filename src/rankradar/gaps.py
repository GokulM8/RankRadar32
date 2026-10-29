"""Per-cluster coverage and gap status (FR-07, FR-08)."""

from __future__ import annotations

from typing import Any

import pandas as pd

GAP, WEAK, COVERED, CLIENT_ONLY = "Gap", "Weak spot", "Covered", "Client-only"


def classify(client_sections: int, competitor_sections: int, client_share: float, weak_share_threshold: float, min_competitor_sections: int) -> str:
    """Status of one cluster.

    - Gap: the client has no sections, at least one competitor does.
    - Client-only: competitors have no sections.
    - Weak spot: the client's share is below the threshold while competitors have at least
      `min_competitor_sections` sections.
    - Covered: everything else.
    """
    if competitor_sections == 0:
        return CLIENT_ONLY
    if client_sections == 0:
        return GAP
    if client_share < weak_share_threshold and competitor_sections >= min_competitor_sections:
        return WEAK
    return COVERED


def coverage(sections: pd.DataFrame, clusters: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """One row per non-noise cluster with coverage counts, status and competitor URLs."""
    g = cfg["gaps"]
    df = sections.merge(clusters[["section_id", "cluster_id"]], on="section_id")
    df = df[df["cluster_id"] >= 0]

    rows = []
    for cid, grp in df.groupby("cluster_id"):
        client = grp[grp["role"] == "client"]
        comp = grp[grp["role"] == "competitor"]
        n = len(grp)
        share = len(client) / n if n else 0.0
        rows.append(
            {
                "cluster_id": int(cid),
                "n_sections": n,
                "client_sections": len(client),
                "competitor_sections": len(comp),
                "competitors_covering": comp["site"].nunique(),
                "client_share": round(share, 4),
                "status": classify(len(client), len(comp), share, g["weak_share_threshold"], g["min_competitor_sections"]),
                "competitor_urls": "|".join(dict.fromkeys(comp["url"])),
                "client_urls": "|".join(dict.fromkeys(client["url"])),
                "sites": ", ".join(f"{s}: {c}" for s, c in grp["site"].value_counts().items()),
            }
        )
    return pd.DataFrame(rows)
