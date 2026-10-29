"""Topic clustering: UMAP reduction followed by HDBSCAN (FR-05)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_score

log = logging.getLogger(__name__)


def reduce(embeddings: np.ndarray, n_components: int, n_neighbors: int, min_dist: float, metric: str, seed: int) -> np.ndarray:
    """UMAP projection with a fixed seed (single-threaded, so results are reproducible)."""
    import umap

    n_neighbors = min(n_neighbors, len(embeddings) - 1)
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=seed,
    )
    return reducer.fit_transform(embeddings)


def cluster(reduced: np.ndarray, min_cluster_size: int, min_samples: int, method: str) -> tuple[np.ndarray, np.ndarray]:
    """HDBSCAN over the reduced space. Returns (labels with -1 = noise, membership probabilities)."""
    import hdbscan

    model = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method=method,
        metric="euclidean",
    )
    labels = model.fit_predict(reduced)
    return labels, model.probabilities_


def cluster_metrics(embeddings: np.ndarray, reduced: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    """Silhouette (non-noise points only), noise ratio, cluster count and size distribution."""
    mask = labels >= 0
    n_clusters = int(len(set(labels[mask])))
    sizes = pd.Series(labels[mask]).value_counts()
    out: dict[str, Any] = {
        "n_sections": int(len(labels)),
        "n_clusters": n_clusters,
        "noise_sections": int((~mask).sum()),
        "noise_ratio": round(float((~mask).mean()), 4),
        "cluster_size": {
            "min": int(sizes.min()) if n_clusters else 0,
            "median": float(sizes.median()) if n_clusters else 0,
            "max": int(sizes.max()) if n_clusters else 0,
            "mean": round(float(sizes.mean()), 2) if n_clusters else 0,
        },
        "silhouette_embedding_cosine": None,
        "silhouette_umap_euclidean": None,
    }
    if n_clusters >= 2:
        out["silhouette_embedding_cosine"] = round(float(silhouette_score(embeddings[mask], labels[mask], metric="cosine")), 4)
        out["silhouette_umap_euclidean"] = round(float(silhouette_score(reduced[mask], labels[mask])), 4)
    return out


def run_cluster(cfg: dict[str, Any], sections: pd.DataFrame, embeddings: np.ndarray) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reduce, cluster, write clusters.parquet; return (clusters table, metrics)."""
    seed = cfg["project"]["random_seed"]
    u, h = cfg["umap"], cfg["hdbscan"]
    reduced = reduce(embeddings, u["n_components"], u["n_neighbors"], u["min_dist"], u["metric"], seed)
    labels, probs = cluster(reduced, h["min_cluster_size"], h["min_samples"], h["cluster_selection_method"])
    viz = reduce(embeddings, 2, u["n_neighbors"], u["viz_min_dist"], u["metric"], seed)

    df = pd.DataFrame(
        {
            "section_id": sections["section_id"].values,
            "cluster_id": labels.astype(int),
            "probability": probs.astype(float),
            "x": viz[:, 0],
            "y": viz[:, 1],
        }
    )
    df.to_parquet(cfg["paths"]["clusters"], index=False)
    metrics = cluster_metrics(embeddings, reduced, labels)
    log.info("Clusters: %d, noise ratio %.2f", metrics["n_clusters"], metrics["noise_ratio"])
    return df, metrics
