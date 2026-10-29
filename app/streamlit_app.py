"""RankRadar dashboard. Reads precomputed outputs only, so it loads fast and runs on Streamlit Community Cloud.

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rankradar.score import apply_scores  # noqa: E402

OUT = ROOT / "outputs"
SITE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
NOISE_COLOR = "#b9b8b2"

st.set_page_config(page_title="RankRadar", layout="wide")


@st.cache_data
def load():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    gaps = pd.read_csv(OUT / "gaps.csv")
    tmap = pd.read_parquet(OUT / "topic_map.parquet")
    briefs = json.loads((OUT / "briefs.json").read_text())
    metrics = json.loads((OUT / "metrics.json").read_text())
    return cfg, gaps, tmap, briefs, metrics


if not (OUT / "gaps.csv").exists():
    st.error("No outputs found. Run `python -m rankradar.pipeline --config config.yaml` first.")
    st.stop()

cfg, gaps, tmap, briefs, metrics = load()
client = next(s["name"] for s in cfg["sites"] if s["role"] == "client")
site_order = [s["name"] for s in sorted(cfg["sites"], key=lambda s: s["role"] != "client")]
color_map = {n: SITE_COLORS[i % len(SITE_COLORS)] for i, n in enumerate(site_order)}

st.title("RankRadar")
st.caption("RankRadar: spot the content gaps between you and your competitors. RankRadar prioritises content opportunities; it does not predict or track search rankings.")

overview, topic_map, gaps_tab, briefs_tab, method = st.tabs(["Overview", "Topic Map", "Gaps", "Briefs", "Method"])

with overview:
    d, c, g = metrics["data"], metrics["clustering"], metrics["gaps"]
    status = g["status_counts"]
    cols = st.columns(5)
    cols[0].metric("Sites crawled", len(d["pages_per_site"]))
    cols[1].metric("Pages", d["total_pages"])
    cols[2].metric("Sections", d["total_sections"])
    cols[3].metric("Topic clusters", c["n_clusters"])
    cols[4].metric(f"Gaps for {client}", status.get("Gap", 0), help=f"Weak spots: {status.get('Weak spot', 0)}")

    left, right = st.columns(2)
    with left:
        st.subheader("Pages and sections per site")
        per_site = pd.DataFrame({"pages": d["pages_per_site"], "sections": d["sections_per_site"]}).fillna(0).astype(int)
        st.dataframe(per_site, width="stretch")
        st.subheader("Cluster quality")
        st.dataframe(
            pd.DataFrame(
                {
                    "metric": ["Silhouette (cosine, embeddings, non-noise)", "Silhouette (UMAP space, non-noise)", "Noise ratio", "Median cluster size"],
                    "value": [c["silhouette_embedding_cosine"], c["silhouette_umap_euclidean"], c["noise_ratio"], c["cluster_size"]["median"]],
                }
            ),
            hide_index=True,
            width="stretch",
        )
    with right:
        st.subheader("Topic status")
        sc = pd.Series(status).reindex(["Gap", "Weak spot", "Covered", "Client-only"]).fillna(0).astype(int)
        fig = px.bar(x=sc.index, y=sc.values, labels={"x": "", "y": "Topic clusters"}, text=sc.values)
        fig.update_traces(marker_color=SITE_COLORS[0], hovertemplate="%{x}: %{y} clusters<extra></extra>")
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        prec = metrics["evaluation"].get("precision")
        if prec:
            st.subheader("Ranking precision against hand labels")
            st.dataframe(
                pd.DataFrame(
                    {
                        "ranking": ["RankRadar opportunity score", "Baseline: competitor section count"],
                        "P@10": [prec["opportunity_score"]["p@10"]["precision"], prec["baseline_competitor_count"]["p@10"]["precision"]],
                        "P@25": [prec["opportunity_score"]["p@25"]["precision"], prec["baseline_competitor_count"]["p@25"]["precision"]],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
            st.caption(f"{prec['n_labelled']} topics labelled ({prec['n_real_gaps']} real gaps). One AI-assisted labelling pass with a fixed rubric; scores were visible to the labeller. See docs/06_EVALUATION.md.")
        st.subheader(f"Top 5 opportunities for {client}")
        st.dataframe(
            gaps.dropna(subset=["score"]).head(5)[["label", "status", "score", "intent"]],
            hide_index=True,
            width="stretch",
        )

with topic_map:
    st.markdown("Each dot is one section. Sections close together discuss similar topics. Grey dots are noise (no clear topic).")
    show_noise = st.checkbox("Show noise", value=False)
    df = tmap if show_noise else tmap[tmap["cluster_id"] >= 0]
    df = df.assign(site_shown=np.where(df["cluster_id"] < 0, "Noise", df["site"]))
    fig = px.scatter(
        df,
        x="x",
        y="y",
        color="site_shown",
        color_discrete_map={**color_map, "Noise": NOISE_COLOR},
        category_orders={"site_shown": site_order + ["Noise"]},
        hover_data={"x": False, "y": False, "site_shown": False, "site": True, "label": True, "status": True, "heading": True, "excerpt": True},
        height=650,
    )
    fig.update_traces(marker=dict(size=7, line=dict(width=1, color="white")))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), legend_title_text="Site", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")

with gaps_tab:
    c1, c2 = st.columns(2)
    statuses = c1.multiselect("Status", ["Gap", "Weak spot", "Covered", "Client-only"], default=["Gap", "Weak spot"])
    intents = c2.multiselect("Intent", sorted(gaps["intent"].unique()), default=sorted(gaps["intent"].unique()))
    view = gaps[gaps["status"].isin(statuses) & gaps["intent"].isin(intents)]
    st.dataframe(
        view[["label", "status", "score", "intent", "competitor_sections", "competitors_covering", "client_sections", "relevance", "competitor_strength", "effort", "reason"]],
        hide_index=True,
        width="stretch",
        height=560,
    )
    st.download_button("Download gaps.csv", gaps.to_csv(index=False), "gaps.csv", "text/csv")

with briefs_tab:
    if not briefs:
        st.info("No briefs generated.")
    else:
        options = {f"{b['opportunity_score']:.1f} · {b['topic']}": b for b in briefs}
        b = options[st.selectbox("Gap", list(options))]
        st.subheader(b["suggested_title"])
        st.caption(f"Status: {b['status']} · Intent: {b['target_intent']} · Opportunity score: {b['opportunity_score']:.1f} · Source: {b['source']}" + (f" ({b['model']})" if b.get("model") else ""))
        st.markdown(f"**Why it matters.** {b['why_it_matters']}")
        st.markdown("**Outline**")
        st.markdown("\n".join(f"- **{o['h2']}**" + "".join(f"\n    - {h}" for h in o["h3"]) for o in b["outline"]))
        st.markdown("**Questions to answer**")
        st.markdown("\n".join(f"- {q}" for q in b["questions_to_answer"]))
        st.markdown("**Competitor references (read, do not copy)**")
        st.markdown("\n".join(f"- {u}" for u in b["competitor_reference_urls"]))
        if b.get("internal_link_from"):
            st.markdown(f"**Internal link from:** {b['internal_link_from']}")
        st.caption("Briefs are for human writers. RankRadar never generates or publishes articles (see Google's scaled content abuse policy).")

with method:
    st.markdown(
        """
**Pipeline.** Crawl public blog posts (robots.txt respected, 1.5 s delay) → extract main text → split into heading-level
sections → embed (`BAAI/bge-small-en-v1.5`) → UMAP → HDBSCAN topic clusters (noise excluded) → keyword / LLM labels →
coverage per site → status (Gap, Weak spot, Covered, Client-only) → opportunity score → briefs for the top gaps.

**Opportunity score** (0–100) = 100 × (w_rel·relevance + w_comp·competitor strength + w_int·intent + w_eff·(1 − effort))

- *Relevance*: cosine similarity between the topic centroid and the closest sentence of the client's service descriptions (min-max scaled across topics).
- *Competitor strength*: half the share of competitors covering the topic, half the log-scaled competitor section count.
- *Intent*: keyword rules; transactional 1.0, commercial 0.7, informational 0.4.
- *Effort*: 0 if a client section is already close to the topic (expand that page), 1 if a new page is needed.

Move the sliders to re-rank the gaps live. Weights are normalised to sum to 1.
"""
    )
    w0 = cfg["scoring"]["weights"]
    cols = st.columns(4)
    w = {
        k: cols[i].slider(k.replace("_", " ").capitalize(), 0.0, 1.0, float(w0[k]), 0.05)
        for i, k in enumerate(["relevance", "competitor_strength", "intent", "effort"])
    }
    total = sum(w.values()) or 1.0
    w = {k: v / total for k, v in w.items()}
    st.caption("Normalised weights: " + ", ".join(f"{k} {v:.2f}" for k, v in w.items()))
    rescored = gaps.assign(new_score=apply_scores(gaps, w)).dropna(subset=["new_score"])
    rescored = rescored.assign(default_rank=rescored["score"].rank(ascending=False, method="first").astype(int))
    rescored = rescored.sort_values("new_score", ascending=False).head(15)
    st.dataframe(rescored[["label", "status", "new_score", "score", "default_rank"]], hide_index=True, width="stretch")
