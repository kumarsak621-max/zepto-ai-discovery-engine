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

from src.database import init_db
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import (
    cached_collection_stats,
    cached_pm_insights,
    cached_reviews,
    clear_data_caches,
)
from src.streamlit_playstore import (
    format_last_updated,
    render_last_updated_caption,
    render_sidebar_fetch_controls,
)

st.set_page_config(page_title="Customer Insights", page_icon="💡", layout="wide")

try:
    ensure_runtime_dirs()
    init_db()
except Exception as exc:
    st.error(f"Could not initialize storage. Details: {exc}")
    st.stop()

render_sidebar_fetch_controls()

st.title("💡 Customer Insights")
st.caption(
    "Aggregated AI analysis for Zepto PMs — problems, themes, exploration barriers, "
    "segments, and product opportunities from live fetched reviews."
)
render_last_updated_caption()

try:
    stats = cached_collection_stats()
    insights = cached_pm_insights()
    reviews = cached_reviews(limit=2000)
except Exception as exc:
    st.error(f"Could not load insights. Details: {exc}")
    st.stop()

if not reviews:
    st.warning(
        "No analyzed feedback yet. Use **📥 Fetch Latest Google Play Reviews** "
        "in the sidebar to download and analyze reviews."
    )
    st.stop()

df = pd.DataFrame(reviews)
df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Reviews", f"{insights.get('total_reviews', len(reviews)):,}")
m2.metric(
    "Average Rating",
    f"{insights['avg_rating']:.2f}"
    if insights.get("avg_rating") is not None
    else (
        f"{stats['avg_rating']:.2f}" if stats.get("avg_rating") is not None else "—"
    ),
)
m3.metric("Analyzed reviews", f"{insights.get('analyzed_count', 0):,}")
m4.metric("Unique themes", len(insights.get("most_frequent_themes") or []))
m5.metric("Last Updated", format_last_updated())

st.markdown("---")
st.subheader("AI Summary")
st.info(insights.get("ai_summary") or "Run analysis to generate an AI summary.")

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

# ---- Shopping habits / product categories / root causes ----
st.markdown("---")
h1, h2, h3 = st.columns(3)
with h1:
    st.subheader("Shopping Habits")
    habits = insights.get("shopping_habits") or []
    if habits:
        hdf = pd.DataFrame(habits).rename(columns={"label": "habit"})
        st.dataframe(hdf, use_container_width=True, hide_index=True)
        fig_h = px.bar(
            hdf,
            x="count",
            y="habit",
            orientation="h",
            color="count",
            color_continuous_scale=["#95D5B2", "#1B4332"],
        )
        fig_h.update_layout(
            yaxis={"categoryorder": "total ascending"},
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            height=280,
            margin=dict(l=10, r=10, t=10, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_h, use_container_width=True)
    else:
        st.info("Habitual shopping signals appear after analysis.")
with h2:
    st.subheader("Product Categories")
    cats = insights.get("product_categories") or []
    if cats:
        cdf = pd.DataFrame(cats).rename(columns={"label": "category"})
        fig_c = px.pie(
            cdf,
            names="category",
            values="count",
            hole=0.4,
            color_discrete_sequence=px.colors.sequential.Tealgrn,
        )
        st.plotly_chart(fig_c, use_container_width=True)
    else:
        st.info("Product categories appear after Gemini tags reviews.")
with h3:
    st.subheader("Root Causes")
    roots = insights.get("root_causes") or []
    if roots:
        rdf = pd.DataFrame(roots).rename(columns={"label": "root_cause"})
        st.dataframe(rdf, use_container_width=True, hide_index=True, height=320)
    else:
        st.info("Root causes appear after advanced analysis.")

st.markdown("---")

# ---- Sentiment trends (kept for continuity) ----
st.subheader("Sentiment Distribution")
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
    try:
        with st.spinner("Running advanced Gemini/fallback analysis..."):
            from src.data_pipeline import run_analysis

            a = run_analysis(batch_size=200)
        clear_data_caches()
        st.success(f"Analyzed {a} reviews")
        st.rerun()
    except Exception as exc:
        st.error(f"Analysis failed. Details: {exc}")
