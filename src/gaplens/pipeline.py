"""Run the full GapLens pipeline.

    python -m gaplens.pipeline --config config.yaml [--skip-crawl] [--no-llm]
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from gaplens import briefs, cluster, crawl, embed, evaluate, gaps, label, score, sectionize
from gaplens.config import load_config
from gaplens.llm import LLMClient, llm_available

log = logging.getLogger("gaplens")


@contextmanager
def timed(timings: dict[str, float], stage: str):
    """Record wall-clock seconds for a stage."""
    log.info("== %s ==", stage)
    t0 = time.perf_counter()
    yield
    timings[stage] = round(time.perf_counter() - t0, 2)
    log.info("%s done in %.1fs", stage, timings[stage])


def write_topic_map(cfg: dict[str, Any], sections: pd.DataFrame, clusters: pd.DataFrame, gaps_df: pd.DataFrame) -> None:
    """Compact per-section table for the dashboard (short excerpts only, no full competitor text)."""
    df = sections[["section_id", "site", "role", "url", "page_title", "heading", "text"]].merge(clusters, on="section_id")
    df["excerpt"] = df["text"].map(lambda t: " ".join(t.split()[:40]))
    df = df.drop(columns="text").merge(gaps_df[["cluster_id", "label", "status", "score"]], on="cluster_id", how="left")
    df["label"] = df["label"].fillna("Noise (no topic)")
    df.to_parquet(cfg["paths"]["topic_map"], index=False)


def run(config_path: str, skip_crawl: bool = False, no_llm: bool = False) -> dict[str, Any]:
    """Run every stage and write outputs/metrics.json. Returns the metrics dict."""
    cfg = load_config(config_path)
    np.random.seed(cfg["project"]["random_seed"])
    timings: dict[str, float] = {}
    for p in ("sections", "gaps", "figures"):
        cfg["paths"][p].parent.mkdir(parents=True, exist_ok=True)

    llm = None
    if llm_available(cfg, no_llm):
        llm = LLMClient(cfg)
        llm.resolve_model()
        log.info("LLM enabled: %s", llm.model)
    else:
        log.info("LLM disabled (no key or --no-llm): keyword labels and template briefs")

    if skip_crawl:
        if not cfg["paths"]["pages"].exists():
            raise SystemExit("--skip-crawl given but data/raw/pages.jsonl does not exist")
        log.info("Skipping crawl; using %s", cfg["paths"]["pages"])
    else:
        with timed(timings, "crawl"):
            crawl.run_crawl(cfg)

    pages = crawl.load_pages(cfg["paths"]["pages"])
    with timed(timings, "sectionize"):
        sections = sectionize.run_sectionize(cfg)
    with timed(timings, "embed"):
        embeddings = embed.run_embed(cfg, sections)
    with timed(timings, "cluster"):
        clusters, cluster_metrics = cluster.run_cluster(cfg, sections, embeddings)
    with timed(timings, "label"):
        labels = label.run_label(cfg, sections, clusters, embeddings, llm)
    with timed(timings, "gaps_and_score"):
        cov = gaps.coverage(sections, clusters, cfg)
        service_texts = score.load_service_texts(cfg["paths"]["services_text"])
        service_vecs, _ = embed.encode(service_texts, cfg["embedding"]["model"], cfg["embedding"].get("fallback_model"))
        components = score.compute_components(cov, sections, clusters, embeddings, service_vecs, service_texts, labels, cfg)
        gaps_df, sensitivity = score.run_score(cfg, components)
    with timed(timings, "briefs"):
        brief_list = briefs.run_briefs(cfg, gaps_df, sections, clusters, labels, llm)
    with timed(timings, "evaluate"):
        write_topic_map(cfg, sections, clusters, gaps_df)
        template_written = evaluate.write_label_template(gaps_df, cfg["paths"]["labels_template"], cfg["evaluation"]["label_top_k"])
        figures = evaluate.make_figures(cfg, sections, clusters, gaps_df)
        precision = evaluate.label_metrics(gaps_df, sections, clusters, cfg["paths"]["labels_filled"], cfg["scoring"]["weights"])

    pages_df = pd.DataFrame(pages)
    meta_path = cfg["paths"]["embeddings_meta"]
    metrics = {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system()},
        "data": {
            "pages_per_site": pages_df.groupby("site").size().to_dict() if len(pages_df) else {},
            "sections_per_site": sections.groupby("site").size().to_dict(),
            "total_pages": len(pages_df),
            "total_sections": len(sections),
            "section_words": {
                "median": float(sections["word_count"].median()),
                "mean": round(float(sections["word_count"].mean()), 1),
                "min": int(sections["word_count"].min()),
                "max": int(sections["word_count"].max()),
            },
            "extractor_counts": pages_df["extractor"].value_counts().to_dict() if "extractor" in pages_df else {},
        },
        "embedding_model": json.loads(meta_path.read_text())["model"] if meta_path.exists() else None,
        "clustering": cluster_metrics,
        "labels": {"llm": sum(v["label_source"] == "llm" for v in labels.values()), "keywords": sum(v["label_source"] == "keywords" for v in labels.values())},
        "gaps": {
            "status_counts": gaps_df["status"].value_counts().to_dict(),
            "scored_clusters": int(gaps_df["score"].notna().sum()),
            "effort_threshold": components.attrs.get("effort_threshold"),
            "competitors_crawled": components.attrs.get("n_competitors"),
            "score": {
                "max": float(gaps_df["score"].max()),
                "median": float(gaps_df["score"].median()),
                "min": float(gaps_df["score"].min()),
            } if gaps_df["score"].notna().any() else None,
            "intent_counts_scored": gaps_df.dropna(subset=["score"])["intent"].value_counts().to_dict(),
            "top10": gaps_df.dropna(subset=["score"]).head(10)[["cluster_id", "label", "status", "score"]].to_dict("records"),
        },
        "sensitivity": sensitivity,
        "briefs": {"count": len(brief_list), "llm": sum(b["source"] == "llm" for b in brief_list), "template": sum(b["source"] == "template" for b in brief_list)},
        "llm": llm.stats() if llm else {"enabled": False},
        "evaluation": {"label_template_written": template_written, "precision": precision, "figures": figures},
        "runtime_seconds": {**timings, "total": round(sum(timings.values()), 2)},
        "flags": {"skip_crawl": skip_crawl, "no_llm": no_llm},
    }
    cfg["paths"]["metrics"].write_text(json.dumps(metrics, indent=2, default=str))
    log.info("Wrote %s", cfg["paths"]["metrics"])
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GapLens pipeline.")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--skip-crawl", action="store_true", help="reuse data/raw/pages.jsonl")
    parser.add_argument("--no-llm", action="store_true", help="keyword labels and template briefs only")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "urllib3", "sentence_transformers", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    m = run(args.config, args.skip_crawl, args.no_llm)
    print(json.dumps({"pages": m["data"]["pages_per_site"], "clusters": m["clustering"]["n_clusters"],
                      "status": m["gaps"]["status_counts"], "runtime_s": m["runtime_seconds"]}, indent=2))


if __name__ == "__main__":
    main()
