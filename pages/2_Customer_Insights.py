"""Page 2 — Customer Insights (AI Discovery Engine / PM Assignment Dashboard)"""

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
from src.insights_ui import render_root_cause_analysis
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import cached_discovery_dashboard, clear_data_caches
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
    "AI Discovery Engine for Zepto PMs — sentiment, habits, segments, discovery barriers, "
    "category opportunities, and growth recommendations from live + uploaded reviews."
)
render_last_updated_caption()

try:
    dash = cached_discovery_dashboard(limit=2000)
except Exception as exc:
    st.error(f"Could not load insights. Details: {exc}")
    st.stop()

reviews = dash.get("reviews") or []
insights = dash.get("insights") or {}
sentiment = dash.get("sentiment") or {}
discovery = dash.get("discovery") or {}
validation = dash.get("validation") or {}
review_sources = dash.get("review_sources") or {}
review_kpis = dash.get("review_kpis") or {}

if not reviews:
    st.warning(
        "No analyzed feedback yet. Use **▶ Run Review Analysis** or "
        "**🔄 Refresh Live Reviews** in the sidebar to download and analyze reviews."
    )
    st.stop()

df = pd.DataFrame(reviews)
if "date" in df.columns:
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

# Shared chart styling
_CHART_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=10, r=10, t=40, b=10),
)

# =============================================================================
# 1. Review Sources
# =============================================================================
st.markdown("---")
st.header("Review Sources")
src_keys = [
    "Google Play Reviews",
    "Apple App Store Reviews",
    "Manual Uploaded Reviews",
    "Merged Reviews",
]
cols = st.columns(4)
for i, key in enumerate(src_keys):
    cols[i].metric(key, f"{int(review_sources.get(key, 0)):,}")
# Extra DB source breakdown if present
extra = {
    k: v
    for k, v in review_sources.items()
    if k not in src_keys and isinstance(v, (int, float))
}
if extra:
    with st.expander("Database source breakdown"):
        st.bar_chart(extra)

# =============================================================================
# 2. Review KPIs
# =============================================================================
st.markdown("---")
st.header("Review KPIs")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Reviews", f"{int(review_kpis.get('Total Reviews') or 0):,}")
avg = review_kpis.get("Average Rating")
k2.metric("Average Rating", f"{avg:.2f}" if isinstance(avg, (int, float)) else "—")
k3.metric("Analyzed Reviews", f"{int(review_kpis.get('Analyzed Reviews') or 0):,}")
k4.metric("Unique Themes", f"{int(review_kpis.get('Unique Themes') or 0):,}")
k5.metric("Last Updated", format_last_updated())

# =============================================================================
# 3. Sentiment Analysis
# =============================================================================
st.markdown("---")
st.header("Sentiment Analysis")
st.caption("Every review is classified as Positive, Neutral, or Negative and stored in feedback.db.")

score = sentiment.get("overall_score") or {}
s1, s2, s3, s4 = st.columns(4)
s1.metric("Positive Reviews", f"{int(sentiment.get('positive', 0)):,}")
s2.metric("Neutral Reviews", f"{int(sentiment.get('neutral', 0)):,}")
s3.metric("Negative Reviews", f"{int(sentiment.get('negative', 0)):,}")
s4.metric(
    "Overall Sentiment Score",
    f"P {score.get('Positive', 0)}% · N {score.get('Neutral', 0)}% · Neg {score.get('Negative', 0)}%",
)

sent_df = pd.DataFrame(
    {
        "sentiment": ["Positive", "Neutral", "Negative"],
        "count": [
            sentiment.get("positive", 0),
            sentiment.get("neutral", 0),
            sentiment.get("negative", 0),
        ],
    }
)
c_pie, c_bar = st.columns(2)
with c_pie:
    fig_pie = px.pie(
        sent_df,
        names="sentiment",
        values="count",
        hole=0.45,
        title="Sentiment mix",
        color="sentiment",
        color_discrete_map={
            "Positive": "#2D6A4F",
            "Neutral": "#ADB5BD",
            "Negative": "#9B2226",
        },
    )
    fig_pie.update_layout(**_CHART_LAYOUT)
    st.plotly_chart(fig_pie, use_container_width=True)
with c_bar:
    fig_bar = px.bar(
        sent_df,
        x="sentiment",
        y="count",
        title="Sentiment counts",
        color="sentiment",
        color_discrete_map={
            "Positive": "#2D6A4F",
            "Neutral": "#ADB5BD",
            "Negative": "#9B2226",
        },
    )
    fig_bar.update_layout(**_CHART_LAYOUT, showlegend=False)
    st.plotly_chart(fig_bar, use_container_width=True)

# =============================================================================
# 4. Pain Points
# =============================================================================
st.markdown("---")
st.header("Pain Points")
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
            **_CHART_LAYOUT,
            height=380,
        )
        st.plotly_chart(fig_p, use_container_width=True)
    with c2:
        st.dataframe(pdf, use_container_width=True, hide_index=True, height=380)
else:
    st.info("Pain points appear after advanced analysis runs.")

# =============================================================================
# 5. Themes
# =============================================================================
st.markdown("---")
st.header("Themes")
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
    fig_th.update_layout(xaxis_tickangle=-25, **_CHART_LAYOUT)
    st.plotly_chart(fig_th, use_container_width=True)
    with st.expander("Theme table"):
        st.dataframe(tdf, use_container_width=True, hide_index=True)
else:
    st.info("Themes appear after analysis.")

# =============================================================================
# 6. Shopping Habit Insights
# =============================================================================
st.markdown("---")
st.header("Shopping Habit Insights")
st.caption("Gemini-generated recurring shopping behaviour from the latest review dataset.")
habit_cards = discovery.get("shopping_habit_insights") or []
if habit_cards:
    cols = st.columns(2)
    for i, insight in enumerate(habit_cards):
        with cols[i % 2].container(border=True):
            st.markdown(f"**Insight {i + 1}**")
            st.write(insight)
else:
    st.info("Shopping habit insights appear after Gemini discovery analysis.")

# =============================================================================
# 7. AI User Segments
# =============================================================================
st.markdown("---")
st.header("AI User Segments")
st.caption("Gemini-inferred segments from reviewed feedback.")
segments = discovery.get("ai_user_segments") or []
if segments:
    seg_df = pd.DataFrame(segments)
    display_cols = [
        c
        for c in [
            "segment",
            "percentage",
            "key_characteristics",
            "typical_shopping_behaviour",
        ]
        if c in seg_df.columns
    ]
    st.dataframe(seg_df[display_cols], use_container_width=True, hide_index=True)
    fig_seg = px.bar(
        seg_df,
        x="percentage",
        y="segment",
        orientation="h",
        color="percentage",
        color_continuous_scale=["#95D5B2", "#1B4332"],
        title="Segment mix (%)",
    )
    fig_seg.update_layout(
        yaxis={"categoryorder": "total ascending"},
        **_CHART_LAYOUT,
        height=360,
    )
    st.plotly_chart(fig_seg, use_container_width=True)
else:
    st.info("User segments appear after Gemini discovery analysis.")

# =============================================================================
# 8. Category Discovery Barriers
# =============================================================================
st.markdown("---")
st.header("Category Discovery Barriers")
st.caption("Barriers preventing users from exploring new product categories.")
barriers = discovery.get("discovery_barriers") or []
if barriers:
    bdf = pd.DataFrame(barriers)
    show_cols = [
        c
        for c in ["barrier", "frequency", "severity", "representative_review"]
        if c in bdf.columns
    ]
    st.dataframe(bdf[show_cols], use_container_width=True, hide_index=True)
    fig_b = px.bar(
        bdf,
        x="barrier",
        y="frequency",
        color="severity",
        title="Barrier frequency",
        color_discrete_map={"High": "#9B2226", "Medium": "#E9C46A", "Low": "#2A9D8F"},
    )
    fig_b.update_layout(xaxis_tickangle=-20, **_CHART_LAYOUT)
    st.plotly_chart(fig_b, use_container_width=True)
    for b in barriers:
        with st.expander(f"{b.get('barrier')} · {b.get('severity')} severity"):
            st.write(b.get("representative_review") or "No example available.")
else:
    st.info("Discovery barriers appear after Gemini discovery analysis.")

# =============================================================================
# 9. AI Root Cause Analysis  (after barriers, before category opportunities)
# =============================================================================
render_root_cause_analysis(discovery, chart_layout=_CHART_LAYOUT)

# =============================================================================
# 10. AI Category Exploration Opportunities
# =============================================================================
st.markdown("---")
st.header("AI Category Exploration Opportunities")
st.caption(
    "Gemini identifies where users could be encouraged to purchase new categories."
)
opps = discovery.get("category_exploration_opportunities") or []
if opps:
    odf = pd.DataFrame(opps)
    # Friendly column names
    rename = {
        "current_category": "Current Category",
        "suggested_new_category": "Suggested New Category",
        "reason": "Reason",
        "confidence_score": "Confidence Score",
    }
    odf = odf.rename(columns=rename)
    if "Confidence Score" in odf.columns:
        odf["Confidence Score"] = odf["Confidence Score"].apply(
            lambda x: f"{int(x)}%" if pd.notna(x) else "—"
        )
    st.dataframe(odf, use_container_width=True, hide_index=True)
    for row in opps:
        with st.container(border=True):
            st.markdown(
                f"**{row.get('current_category', '—')} → "
                f"{row.get('suggested_new_category', '—')}**"
            )
            st.write(row.get("reason") or "")
            st.caption(f"Confidence: {int(row.get('confidence_score') or 0)}%")
else:
    st.info("Category opportunities appear after Gemini discovery analysis.")

# =============================================================================
# 11. Growth Opportunity KPIs
# =============================================================================
st.markdown("---")
st.header("Growth Opportunity KPIs")
st.caption("AI-derived growth scores from the latest analyzed review set.")
kpis = discovery.get("growth_kpis") or {}
kpi_labels = [
    ("users_mentioning_repetitive_purchases", "Users mentioning repetitive purchases"),
    ("users_expressing_interest_in_new_categories", "Users expressing interest in new categories"),
    ("users_mentioning_discovery_problems", "Users mentioning discovery problems"),
    ("category_exploration_opportunity_score", "Category Exploration Opportunity Score"),
    ("cross_sell_opportunity_score", "Cross-Sell Opportunity Score"),
    ("average_experimentation_intent", "Average Experimentation Intent"),
    ("discovery_friction_score", "Discovery Friction Score"),
    ("recommendation_relevance_score", "Recommendation Relevance Score"),
]
rows = [kpi_labels[i : i + 4] for i in range(0, len(kpi_labels), 4)]
for row in rows:
    cols = st.columns(len(row))
    for col, (key, label) in zip(cols, row):
        val = kpis.get(key)
        col.metric(label, f"{float(val):.0f}" if val is not None else "—")

# =============================================================================
# 11. AI Recommendations for Growth Team
# =============================================================================
st.markdown("---")
st.header("AI Recommendations for Growth Team")
st.caption("Actionable recommendations generated dynamically from review insights.")
recs = discovery.get("growth_recommendations") or []
if recs:
    for i, rec in enumerate(recs, 1):
        with st.container(border=True):
            st.markdown(f"**{i}.** {rec}")
else:
    st.info("Growth recommendations appear after Gemini discovery analysis.")

# =============================================================================
# 12. Insight Validation
# =============================================================================
st.markdown("---")
st.header("Insight Validation")
v1, v2, v3 = st.columns(3)
v1.metric(
    "Duplicate reviews removed",
    f"{int(validation.get('duplicates_removed') or 0):,}",
)
v2.metric(
    "Total reviews analysed",
    f"{int(validation.get('total_reviews_analysed') or 0):,}",
)
v3.metric(
    "AI confidence score",
    f"{validation.get('ai_confidence_score', 0)}%",
)
v4, v5, v6 = st.columns(3)
v4.metric(
    "Theme confidence score",
    f"{validation.get('theme_confidence_score', 0)}%",
)
v5.metric(
    "Last analysis timestamp",
    format_last_updated(validation.get("last_analysis_timestamp")),
)
sources = validation.get("sources_analysed") or []
v6.metric("Sources analysed", ", ".join(sources) if sources else "—")
st.info(
    validation.get("note")
    or (
        "AI-generated insights were validated through duplicate removal, "
        "confidence scoring, and review consistency checks."
    )
)
if discovery.get("source"):
    st.caption(
        f"Discovery synthesis source: **{discovery.get('source')}** "
        "(gemini = live model; fallback = evidence-based heuristics when Gemini is unavailable)."
    )

# =============================================================================
# Continuity: structured table + executive summary
# =============================================================================
with st.expander("AI Summary & structured per-review analysis"):
    st.subheader("AI Summary")
    st.write(insights.get("ai_summary") or "Run analysis to generate an AI summary.")
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

# =============================================================================
# 13. AI Chatbot pointer
# =============================================================================
st.markdown("---")
st.header("AI Chatbot")
st.info(
    "Continue research in the **AI Product Manager Chatbot** page — ask questions "
    "grounded in the same merged, deduplicated, Gemini-analyzed review dataset."
)
try:
    st.page_link(
        "pages/3_AI_Product_Manager_Chatbot.py",
        label="Open AI Product Manager Chatbot",
        icon="🤖",
    )
except Exception:
    st.markdown("➡️ Open the **AI Product Manager Chatbot** page from the sidebar.")
