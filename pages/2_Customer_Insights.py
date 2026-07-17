"""Page 2 — Customer Insights (Advanced PM Research Dashboard)"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import (
    fetch_all_reviews,
    get_collection_stats,
    get_pm_insights,
    init_db,
)

st.set_page_config(page_title="Customer Insights", page_icon="💡", layout="wide")
init_db()

st.title("💡 Customer Insights")
st.caption(
    "Aggregated AI analysis for Zepto PMs — problems, themes, exploration barriers, "
    "segments, and product opportunities."
)

stats = get_collection_stats()
insights = get_pm_insights()
reviews = fetch_all_reviews(limit=2000)

if not reviews:
    st.warning("No analyzed feedback yet. Run the data pipeline first.")
    st.stop()

df = pd.DataFrame(reviews)
df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Analyzed reviews", f"{insights.get('analyzed_count', 0):,}")
m2.metric("Unique themes", len(insights.get("most_frequent_themes") or []))
m3.metric(
    "Exploration barriers",
    sum(b["count"] for b in insights.get("category_exploration_barriers") or []),
)
m4.metric(
    "Product opportunities",
    len(insights.get("recommended_product_opportunities") or []),
)

st.markdown("---")

# ---- 1. Top customer problems ----
st.subheader("Top customer problems")
problems = insights.get("top_customer_problems") or []
if problems:
    pdf = pd.DataFrame(problems).rename(columns={"label": "pain_point"})
    c1, c2 = st.columns([1.2, 1])
    with c1:
        fig_p = px.bar(
            pdf.head(8),
            x="count",
            y="pain_point",
            orientation="h",
            color="count",
            color_continuous_scale=["#F4A261", "#9B2226"],
            title="Most mentioned pain points",
        )
        fig_p.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=380,
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_p, use_container_width=True)
    with c2:
        st.dataframe(pdf, use_container_width=True, hide_index=True, height=380)
else:
    st.info("Pain points appear after advanced analysis runs.")

# ---- 2. Most frequent themes ----
st.subheader("Most frequent themes")
themes = insights.get("most_frequent_themes") or []
if themes:
    tdf = pd.DataFrame(themes).rename(columns={"label": "theme"})
    fig_th = px.bar(
        tdf,
        x="theme",
        y="count",
        title="Theme distribution",
        color="count",
        color_continuous_scale=["#D8F3DC", "#081C15"],
    )
    fig_th.update_layout(
        xaxis_tickangle=-25,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_th, use_container_width=True)
else:
    st.info("Themes appear after analysis.")

# ---- 3. Category exploration barriers ----
st.subheader("Category exploration barriers")
st.caption(
    "Signals that block users from exploring beyond staple grocery "
    "(discovery, awareness, trust, pricing)."
)
barriers = insights.get("category_exploration_barriers") or []
if barriers:
    bdf = pd.DataFrame(
        [{"barrier": b["barrier"], "count": b["count"]} for b in barriers]
    )
    bc1, bc2 = st.columns([1, 1.2])
    with bc1:
        fig_b = px.pie(
            bdf,
            names="barrier",
            values="count",
            hole=0.4,
            title="Barrier mix",
            color_discrete_sequence=px.colors.sequential.Tealgrn,
        )
        st.plotly_chart(fig_b, use_container_width=True)
    with bc2:
        for b in barriers:
            with st.expander(f"{b['barrier']}  ·  {b['count']} mentions"):
                examples = b.get("examples") or []
                if examples:
                    for ex in examples:
                        st.markdown(f"> {ex}")
                else:
                    st.write("No example snippets stored yet.")
else:
    st.info("No exploration-barrier themes detected yet.")

# ---- 4. Segments with exploration potential ----
st.subheader("User segments with highest exploration potential")
segments = insights.get("exploration_potential_segments") or []
all_segments = insights.get("all_segments") or []
sc1, sc2 = st.columns(2)
with sc1:
    if segments:
        sdf = pd.DataFrame(segments).rename(columns={"label": "segment"})
        fig_s = px.bar(
            sdf,
            x="count",
            y="segment",
            orientation="h",
            color="count",
            color_continuous_scale=["#95D5B2", "#1B4332"],
            title="Highest exploration potential",
        )
        fig_s.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=320,
        )
        st.plotly_chart(fig_s, use_container_width=True)
    else:
        st.info("Segment signals appear after advanced analysis.")
with sc2:
    if all_segments:
        adf = pd.DataFrame(all_segments).rename(columns={"label": "segment"})
        st.markdown("**All customer segments**")
        st.dataframe(adf, use_container_width=True, hide_index=True, height=320)
    else:
        st.info("No segment data yet.")

# ---- 5. Recommended product opportunities ----
st.subheader("Recommended product opportunities")
opps = insights.get("recommended_product_opportunities") or []
if opps:
    for i, opp in enumerate(opps, 1):
        with st.container(border=True):
            st.markdown(f"**{i}. {opp.get('opportunity')}**")
            meta = " · ".join(
                filter(
                    None,
                    [
                        f"Theme: {opp.get('theme')}" if opp.get("theme") else "",
                        f"Segment: {opp.get('segment')}" if opp.get("segment") else "",
                        f"Evidence: {opp.get('count')} reviews",
                    ],
                )
            )
            st.caption(meta)
            if opp.get("example"):
                st.markdown(f"> {opp['example']}")
else:
    st.info("Product opportunities are generated during advanced review analysis.")

st.markdown("---")

# ---- Sentiment trends (kept for continuity) ----
st.subheader("Sentiment trends")
col1, col2 = st.columns([1, 1])
with col1:
    sent = stats.get("by_sentiment") or {}
    if sent:
        sdf = pd.DataFrame({"sentiment": list(sent.keys()), "count": list(sent.values())})
        fig_sent = px.pie(
            sdf,
            names="sentiment",
            values="count",
            color="sentiment",
            color_discrete_map={
                "Positive": "#2D6A4F",
                "Negative": "#9B2226",
                "Neutral": "#ADB5BD",
                "Unanalyzed": "#CED4DA",
            },
            hole=0.45,
            title="Sentiment mix",
        )
        st.plotly_chart(fig_sent, use_container_width=True)
with col2:
    if df["date_parsed"].notna().any() and "sentiment" in df.columns:
        trend = (
            df.dropna(subset=["date_parsed"])
            .assign(day=lambda x: x["date_parsed"].dt.floor("D"))
            .groupby(["day", "sentiment"])
            .size()
            .reset_index(name="count")
        )
        fig_t = px.line(
            trend,
            x="day",
            y="count",
            color="sentiment",
            title="Sentiment over time",
            color_discrete_map={
                "Positive": "#2D6A4F",
                "Negative": "#9B2226",
                "Neutral": "#6C757D",
            },
        )
        fig_t.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_t, use_container_width=True)
    else:
        st.info("Not enough dated reviews for a trend chart.")

# ---- Structured analysis table ----
st.subheader("Structured AI analysis (per review)")
filter_theme = st.selectbox(
    "Filter by theme",
    options=["All"]
    + sorted({t for t in df.get("theme", pd.Series()).dropna().unique() if t}),
)
sample = df.copy()
if filter_theme != "All":
    sample = sample[sample["theme"] == filter_theme]
cols = [
    c
    for c in [
        "source",
        "sentiment",
        "theme",
        "user_intent",
        "customer_segment",
        "review_summary",
        "pain_point",
        "root_cause",
        "product_opportunity",
        "rating",
        "date",
    ]
    if c in sample.columns
]
st.dataframe(sample[cols].head(25), use_container_width=True, hide_index=True)

st.markdown("---")
if st.button("↻ Re-run advanced analysis on pending reviews", type="primary"):
    with st.spinner("Running advanced Gemini/fallback analysis..."):
        from src.data_pipeline import run_analysis

        a = run_analysis(batch_size=200)
    st.success(f"Analyzed {a} reviews")
    st.rerun()
