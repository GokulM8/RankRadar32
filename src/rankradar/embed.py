"""Section embeddings with sentence-transformers (FR-04)."""

from __future__ import annotations

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from rankradar.sectionize import embedding_text

log = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def load_model(name: str, fallback: str | None = None):
    """Load a sentence-transformers model, falling back to a second model if the first fails."""
    from sentence_transformers import SentenceTransformer

    try:
        return SentenceTransformer(name, device="cpu"), name
    except Exception as exc:  # network or model errors
        if not fallback:
            raise
        log.warning("Could not load %s (%s); using fallback %s", name, exc, fallback)
        return SentenceTransformer(fallback, device="cpu"), fallback


def encode(texts: list[str], model_name: str, fallback: str | None = None, batch_size: int = 32) -> tuple[np.ndarray, str]:
    """Encode texts into L2-normalised float32 vectors. Returns (vectors, model actually used)."""
    model, used = load_model(model_name, fallback)
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=len(texts) > 200,
        convert_to_numpy=True,
    )
    return vecs.astype(np.float32), used


def _fingerprint(texts: list[str], model_name: str) -> str:
    h = hashlib.sha1(model_name.encode())
    for t in texts:
        h.update(t.encode("utf-8"))
    return h.hexdigest()


def run_embed(cfg: dict[str, Any], sections: pd.DataFrame | None = None) -> np.ndarray:
    """Embed all sections, reusing the cached matrix if sections and model are unchanged."""
    paths, ec = cfg["paths"], cfg["embedding"]
    if sections is None:
        sections = pd.read_parquet(paths["sections"])
    texts = [embedding_text(r) for _, r in sections.iterrows()]
    fp = _fingerprint(texts, ec["model"])

    if paths["embeddings"].exists() and paths["embeddings_meta"].exists():
        meta = json.loads(paths["embeddings_meta"].read_text())
        if meta.get("fingerprint") == fp:
            log.info("Using cached embeddings (%s)", meta["model"])
            return np.load(paths["embeddings"])

    vecs, used = encode(texts, ec["model"], ec.get("fallback_model"), ec.get("batch_size", 32))
    np.save(paths["embeddings"], vecs)
    paths["embeddings_meta"].write_text(
        json.dumps({"fingerprint": fp, "model": used, "n": len(texts), "dim": int(vecs.shape[1])}, indent=2)
    )
    return vecs
