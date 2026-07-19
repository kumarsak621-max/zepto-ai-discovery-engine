"""Page 2 — Customer Insights (AI Discovery Engine / PM Assignment Dashboard)"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import init_db
from src.gemini_status_ui import (
    render_gemini_all_keys_failed_warning,
    render_gemini_key_caption,
)
from src.insights_ui import render_root_cause_analysis
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import cached_discovery_dashboard, clear_data_caches
from src.streamlit_playstore import (
    format_last_updated,
    render_last_updated_caption,
    render_sidebar_fetch_controls,
)

st.set_page_config(page_title="Customer Insights", page_icon="💡", layout="wide")

_CHART_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=10, r=10, t=40, b=10),
)


def _safe_section(title: str, fn: Callable[[], None]) -> None:
    try:
        fn()
    except Exception as exc:
        st.error(f"**{title}** failed to render. Details: `{exc}`")
        st.info("Other sections may still work. Re-run analysis or refresh the page.")


def _has_cols(df: pd.DataFrame, cols: list[str]) -> bool:
    return bool(not df.empty and all(c in df.columns for c in cols))


def _as_records(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = str(
                    item.get("insight")
                    or item.get("text")
                    or item.get("summary")
                    or item.get("recommendation")
                    or ""
                ).strip()
            else:
                text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def _plot(fig: Any, *, height: int | None = None) -> None:
    try:
        if height is not None:
            fig.update_layout(**_CHART_LAYOUT, height=height)
        else:
            fig.update_layout(**_CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.warning(f"Chart could not be rendered: {exc}")


try:
    ensure_runtime_dirs()
    init_db()
except Exception as exc:
    st.error(f"Could not initialize storage. Details: {exc}")
    st.stop()

try:
    render_sidebar_fetch_controls()
except Exception as exc:
    st.sidebar.warning(f"Sidebar controls unavailable: {exc}")

st.title("💡 Customer Insights")
st.caption(
    "AI Discovery Engine for Zepto PMs — sentiment, habits, segments, discovery barriers, "
    "category opportunities, and growth recommendations from live + uploaded reviews."
)
try:
    render_last_updated_caption()
except Exception:
    st.caption("Last Updated: —")
render_gemini_key_caption()

dash: dict[str, Any] = {}
try:
    with st.spinner("Loading Customer Insights…"):
        dash = cached_discovery_dashboard(limit=2000) or {}
except Exception as exc:
    st.error(f"Could not load insights. Details: {exc}")
    st.warning(
        "Try **▶ Run Review Analysis** in the sidebar, then reload this page. "
        "If Gemini is unavailable, the app still shows evidence-based fallback insights."
    )
    st.stop()

reviews = dash.get("reviews") or []
insights = dash.get("insights") or {}
sentiment = dash.get("sentiment") or {}
discovery = dash.get("discovery") or {}
validation = dash.get("validation") or {}
review_sources = dash.get("review_sources") or {}
review_kpis = dash.get("review_kpis") or {}

if not isinstance(reviews, list) or not reviews:
    st.warning(
        "No reviews available yet. Use **▶ Run Review Analysis** or "
        "**🔄 Refresh Live Reviews** in the sidebar to collect and analyze reviews."
    )
    st.stop()

_discovery_source = str((dash.get("discovery") or {}).get("source") or "")
if _discovery_source.startswith("fallback-all-keys") or _discovery_source.startswith(
    "fallback-auth"
):
    render_gemini_all_keys_failed_warning()
elif _discovery_source.startswith("fallback"):
    st.info(
        "Showing evidence-based insights while Gemini is unavailable. "
        "Dashboards remain fully usable."
    )

try:
    df = pd.DataFrame(reviews)
except Exception as exc:
    st.error(f"Could not build reviews table. Details: {exc}")
    st.stop()

if "date" in df.columns:
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)

analyzed_count = int(review_kpis.get("Analyzed Reviews") or insights.get("analyzed_count") or 0)
if analyzed_count <= 0 and "theme" in df.columns:
    analyzed_count = int(df["theme"].notna().sum())
if analyzed_count <= 0:
    st.info(
        "Reviews are loaded, but advanced AI analysis fields are still empty. "
        "Click **↻ Re-run advanced analysis on pending reviews** at the bottom, "
        "or run **▶ Run Review Analysis** in the sidebar."
    )


# =============================================================================
# 1. Review Sources
# =============================================================================
def _section_sources() -> None:
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
        try:
            cols[i].metric(key, f"{int(review_sources.get(key, 0) or 0):,}")
        except Exception:
            cols[i].metric(key, "0")
    extra = {
        k: int(v)
        for k, v in review_sources.items()
        if k not in src_keys and isinstance(v, (int, float))
    }
    if extra:
        with st.expander("Database source breakdown"):
            st.bar_chart(extra)


_safe_section("Review Sources", _section_sources)


# =============================================================================
# 2. Review KPIs
# =============================================================================
def _section_kpis() -> None:
    st.markdown("---")
    st.header("Review KPIs")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Reviews", f"{int(review_kpis.get('Total Reviews') or len(reviews)):,}")
    avg = review_kpis.get("Average Rating")
    k2.metric("Average Rating", f"{avg:.2f}" if isinstance(avg, (int, float)) else "—")
    k3.metric("Analyzed Reviews", f"{int(review_kpis.get('Analyzed Reviews') or analyzed_count):,}")
    k4.metric("Unique Themes", f"{int(review_kpis.get('Unique Themes') or 0):,}")
    k5.metric("Last Updated", format_last_updated())


_safe_section("Review KPIs", _section_kpis)


# =============================================================================
# 3. Sentiment Analysis
# =============================================================================
def _section_sentiment() -> None:
    st.markdown("---")
    st.header("Sentiment Analysis")
    st.caption(
        "Every review is classified as Positive, Neutral, or Negative and stored in feedback.db."
    )
    score = sentiment.get("overall_score") or {}
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Positive Reviews", f"{int(sentiment.get('positive', 0) or 0):,}")
    s2.metric("Neutral Reviews", f"{int(sentiment.get('neutral', 0) or 0):,}")
    s3.metric("Negative Reviews", f"{int(sentiment.get('negative', 0) or 0):,}")
    s4.metric(
        "Overall Sentiment Score",
        f"P {score.get('Positive', 0)}% · N {score.get('Neutral', 0)}% · Neg {score.get('Negative', 0)}%",
    )

    sent_df = pd.DataFrame(
        {
            "sentiment": ["Positive", "Neutral", "Negative"],
            "count": [
                int(sentiment.get("positive", 0) or 0),
                int(sentiment.get("neutral", 0) or 0),
                int(sentiment.get("negative", 0) or 0),
            ],
        }
    )
    if sent_df["count"].sum() <= 0:
        st.info("Sentiment charts appear after reviews are classified.")
        return
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
        _plot(fig_pie)
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
        fig_bar.update_layout(showlegend=False)
        _plot(fig_bar)


_safe_section("Sentiment Analysis", _section_sentiment)


# =============================================================================
# 4. Pain Points
# =============================================================================
def _section_pain() -> None:
    st.markdown("---")
    st.header("Pain Points")
    problems = _as_records(insights.get("top_customer_problems"))
    if not problems:
        st.info("Pain points appear after advanced analysis runs.")
        return
    pdf = pd.DataFrame(problems)
    if "pain_point" not in pdf.columns and "label" in pdf.columns:
        pdf = pdf.rename(columns={"label": "pain_point"})
    if not _has_cols(pdf, ["pain_point", "count"]):
        st.info("Pain point data is incomplete. Re-run analysis to refresh.")
        return
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
        fig_p.update_layout(yaxis={"categoryorder": "total ascending"})
        _plot(fig_p, height=380)
    with c2:
        st.dataframe(pdf, use_container_width=True, hide_index=True, height=380)


_safe_section("Pain Points", _section_pain)


# =============================================================================
# 5. Themes
# =============================================================================
def _section_themes() -> None:
    st.markdown("---")
    st.header("Themes")
    themes = _as_records(insights.get("most_frequent_themes"))
    if not themes:
        st.info("Themes appear after analysis.")
        return
    tdf = pd.DataFrame(themes)
    if "theme" not in tdf.columns and "label" in tdf.columns:
        tdf = tdf.rename(columns={"label": "theme"})
    if not _has_cols(tdf, ["theme", "count"]):
        st.info("Theme data is incomplete. Re-run analysis to refresh.")
        return
    fig_th = px.bar(
        tdf,
        x="theme",
        y="count",
        title="Theme distribution",
        color="count",
        color_continuous_scale=["#D8F3DC", "#081C15"],
    )
    fig_th.update_layout(xaxis_tickangle=-25)
    _plot(fig_th)
    with st.expander("Theme table"):
        st.dataframe(tdf, use_container_width=True, hide_index=True)


_safe_section("Themes", _section_themes)


# =============================================================================
# 6. Shopping Habit Insights
# =============================================================================
def _section_habits() -> None:
    st.markdown("---")
    st.header("Shopping Habit Insights")
    st.caption("Gemini-generated recurring shopping behaviour from the latest review dataset.")
    habit_cards = _as_str_list(discovery.get("shopping_habit_insights"))
    if not habit_cards:
        st.info("Shopping habit insights appear after Gemini discovery analysis.")
        return
    cols = st.columns(2)
    for i, insight in enumerate(habit_cards):
        try:
            with cols[i % 2].container(border=True):
                st.markdown(f"**Insight {i + 1}**")
                st.write(insight)
        except TypeError:
            cols[i % 2].markdown(f"**Insight {i + 1}**  \n{insight}")


_safe_section("Shopping Habit Insights", _section_habits)


# =============================================================================
# 7. AI User Segments
# =============================================================================
def _section_segments() -> None:
    st.markdown("---")
    st.header("AI User Segments")
    st.caption("Gemini-inferred segments from reviewed feedback.")
    segments = _as_records(discovery.get("ai_user_segments"))
    if not segments:
        st.info("User segments appear after Gemini discovery analysis.")
        return
    seg_df = pd.DataFrame(segments)
    for col, default in [
        ("segment", "General"),
        ("percentage", 0),
        ("key_characteristics", ""),
        ("typical_shopping_behaviour", ""),
    ]:
        if col not in seg_df.columns:
            seg_df[col] = default
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
    if display_cols:
        st.dataframe(seg_df[display_cols], use_container_width=True, hide_index=True)
    if _has_cols(seg_df, ["percentage", "segment"]):
        fig_seg = px.bar(
            seg_df,
            x="percentage",
            y="segment",
            orientation="h",
            color="percentage",
            color_continuous_scale=["#95D5B2", "#1B4332"],
            title="Segment mix (%)",
        )
        fig_seg.update_layout(yaxis={"categoryorder": "total ascending"})
        _plot(fig_seg, height=360)


_safe_section("AI User Segments", _section_segments)


# =============================================================================
# 8. Category Discovery Barriers
# =============================================================================
def _section_barriers() -> None:
    st.markdown("---")
    st.header("Category Discovery Barriers")
    st.caption("Barriers preventing users from exploring new product categories.")
    barriers = _as_records(discovery.get("discovery_barriers"))
    if not barriers:
        st.info("Discovery barriers appear after Gemini discovery analysis.")
        return
    bdf = pd.DataFrame(barriers)
    for col, default in [
        ("barrier", "Unknown"),
        ("frequency", 0),
        ("severity", "Medium"),
        ("representative_review", ""),
    ]:
        if col not in bdf.columns:
            bdf[col] = default
    show_cols = [
        c
        for c in ["barrier", "frequency", "severity", "representative_review"]
        if c in bdf.columns
    ]
    st.dataframe(bdf[show_cols], use_container_width=True, hide_index=True)
    if _has_cols(bdf, ["barrier", "frequency"]):
        fig_b = px.bar(
            bdf,
            x="barrier",
            y="frequency",
            color="severity" if "severity" in bdf.columns else None,
            title="Barrier frequency",
            color_discrete_map={"High": "#9B2226", "Medium": "#E9C46A", "Low": "#2A9D8F"},
        )
        fig_b.update_layout(xaxis_tickangle=-20)
        _plot(fig_b)
    for b in barriers:
        with st.expander(f"{b.get('barrier', 'Barrier')} · {b.get('severity', 'Medium')} severity"):
            st.write(b.get("representative_review") or "No example available.")


_safe_section("Category Discovery Barriers", _section_barriers)


# =============================================================================
# 9. AI Root Cause Analysis
# =============================================================================
_safe_section(
    "AI Root Cause Analysis",
    lambda: render_root_cause_analysis(discovery, chart_layout=_CHART_LAYOUT),
)


# =============================================================================
# 10. AI Category Exploration Opportunities
# =============================================================================
def _section_opps() -> None:
    st.markdown("---")
    st.header("AI Category Exploration Opportunities")
    st.caption(
        "Gemini identifies where users could be encouraged to purchase new categories."
    )
    opps = _as_records(discovery.get("category_exploration_opportunities"))
    if not opps:
        st.info("Category opportunities appear after Gemini discovery analysis.")
        return
    odf = pd.DataFrame(opps)
    rename = {
        "current_category": "Current Category",
        "suggested_new_category": "Suggested New Category",
        "reason": "Reason",
        "confidence_score": "Confidence Score",
    }
    present = {k: v for k, v in rename.items() if k in odf.columns}
    odf = odf.rename(columns=present)
    if "Confidence Score" in odf.columns:
        def _fmt_conf(x: Any) -> str:
            try:
                return f"{int(float(x))}%"
            except (TypeError, ValueError):
                return "—"

        odf["Confidence Score"] = odf["Confidence Score"].apply(_fmt_conf)
    st.dataframe(odf, use_container_width=True, hide_index=True)
    for row in opps:
        try:
            with st.container(border=True):
                st.markdown(
                    f"**{row.get('current_category', '—')} → "
                    f"{row.get('suggested_new_category', '—')}**"
                )
                st.write(row.get("reason") or "")
                try:
                    conf = int(float(row.get("confidence_score") or 0))
                except (TypeError, ValueError):
                    conf = 0
                st.caption(f"Confidence: {conf}%")
        except TypeError:
            st.markdown(
                f"**{row.get('current_category', '—')} → "
                f"{row.get('suggested_new_category', '—')}**  \n"
                f"{row.get('reason') or ''}"
            )


_safe_section("AI Category Exploration Opportunities", _section_opps)


# =============================================================================
# 11. Growth Opportunity KPIs
# =============================================================================
def _section_growth_kpis() -> None:
    st.markdown("---")
    st.header("Growth Opportunity KPIs")
    st.caption("AI-derived growth scores from the latest analyzed review set.")
    kpis = discovery.get("growth_kpis") or {}
    if not isinstance(kpis, dict) or not kpis:
        st.info("Growth KPIs appear after discovery analysis.")
        return
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
            try:
                col.metric(label, f"{float(val):.0f}" if val is not None else "—")
            except (TypeError, ValueError):
                col.metric(label, "—")


_safe_section("Growth Opportunity KPIs", _section_growth_kpis)


# =============================================================================
# 12. AI Recommendations for Growth Team
# =============================================================================
def _section_recs() -> None:
    st.markdown("---")
    st.header("AI Recommendations for Growth Team")
    st.caption("Actionable recommendations generated dynamically from review insights.")
    recs = _as_str_list(discovery.get("growth_recommendations"))
    if not recs:
        st.info("Growth recommendations appear after Gemini discovery analysis.")
        return
    for i, rec in enumerate(recs, 1):
        try:
            with st.container(border=True):
                st.markdown(f"**{i}.** {rec}")
        except TypeError:
            st.markdown(f"**{i}.** {rec}")


_safe_section("AI Recommendations for Growth Team", _section_recs)


# =============================================================================
# 13. Insight Validation
# =============================================================================
def _section_validation() -> None:
    st.markdown("---")
    st.header("Insight Validation")
    v1, v2, v3 = st.columns(3)
    v1.metric(
        "Duplicate reviews removed",
        f"{int(validation.get('duplicates_removed') or 0):,}",
    )
    v2.metric(
        "Total reviews analysed",
        f"{int(validation.get('total_reviews_analysed') or analyzed_count or len(reviews)):,}",
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
    if not isinstance(sources, list):
        sources = [str(sources)]
    v6.metric("Sources analysed", ", ".join(map(str, sources)) if sources else "—")
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


_safe_section("Insight Validation", _section_validation)


# =============================================================================
# Continuity: structured table + executive summary
# =============================================================================
with st.expander("AI Summary & structured per-review analysis"):
    try:
        st.subheader("AI Summary")
        st.write(insights.get("ai_summary") or "Run analysis to generate an AI summary.")
        st.subheader("Structured AI analysis (per review)")
        theme_opts = ["All"]
        if "theme" in df.columns:
            theme_opts += sorted(
                {str(t) for t in df["theme"].dropna().unique() if str(t).strip()}
            )
        filter_theme = st.selectbox("Filter by theme", options=theme_opts)
        sample = df.copy()
        if filter_theme != "All" and "theme" in sample.columns:
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
        if cols:
            st.dataframe(sample[cols].head(25), use_container_width=True, hide_index=True)
        else:
            st.info("No structured analysis columns available yet.")
    except Exception as exc:
        st.warning(f"Could not render structured analysis table: {exc}")

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

st.markdown("---")
st.header("AI Chatbot")
st.info(
    "Continue research in the **AI Product Manager Chatbot** page — ask questions "
    "grounded in the same merged, deduplicated, Gemini-analyzed review dataset."
)
try:
    st.page_link(
        "pages/2_AI_Product_Manager_Chatbot.py",
        label="Open AI Product Manager Chatbot",
        icon="🤖",
    )
except Exception:
    st.markdown("➡️ Open the **AI Product Manager Chatbot** page from the sidebar.")
