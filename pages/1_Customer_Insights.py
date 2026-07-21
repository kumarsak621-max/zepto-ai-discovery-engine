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

from src.auto_bootstrap import (
    ensure_live_reviews_loaded,
    render_auto_collect_warning,
    render_auto_status_sidebar,
)
from src.database import init_db
from src.gemini_status_ui import (
    render_gemini_all_keys_failed_warning,
)
from src.insights_ui import render_root_cause_analysis
from src.paths import ensure_runtime_dirs
from src.review_source_ui import (
    ensure_source_data_loaded,
    render_review_filters,
    render_review_source_selector,
    render_visible_reviews_table,
)
from src.review_sync import get_refresh_status
from src.streamlit_cache import cached_filtered_dashboard, clear_data_caches
from src.streamlit_playstore import format_last_updated, render_last_updated_caption

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
                    or item.get("label")
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
        st.plotly_chart(fig, width="stretch")
    except Exception as exc:
        st.warning(f"Chart could not be rendered: {exc}")


try:
    ensure_runtime_dirs()
    init_db()
except Exception as exc:
    st.error(f"Could not initialize storage. Details: {exc}")
    st.stop()

st.title("💡 Customer Insights")
st.caption(
    "AI Discovery Engine for Zepto PMs — live store reviews + full warehouse, "
    "sentiment, habits, segments, discovery barriers, and growth recommendations."
)

st.markdown("---")
data_source = render_review_source_selector(key_prefix="ci")
# Live = force fetch newest. All = use warehouse (+ normal sync via sidebar).
ensure_source_data_loaded(data_source, key_prefix="ci")
try:
    if data_source == "all":
        ensure_live_reviews_loaded()
    render_auto_status_sidebar()
except Exception as exc:
    st.sidebar.warning(f"Live data status unavailable: {exc}")

render_auto_collect_warning()

_refresh = get_refresh_status()
_badge_cols = st.columns([1, 1, 2])
_badge_cols[0].markdown("🟢 **LIVE**")
_badge_cols[1].markdown(f"⏱ **{_refresh.get('relative') or 'Updated —'}**")
try:
    render_last_updated_caption()
except Exception:
    st.caption(f"Last Updated: {format_last_updated(_refresh.get('last_sync_at'))}")
st.caption(
    f"Next Refresh: **{format_last_updated(_refresh.get('next_refresh_at'))}** "
    f"(auto every {_refresh.get('auto_refresh_minutes', 30)} min)"
)

_filters = render_review_filters(key_prefix="ci")
date_range = _filters["date_range"]
platform = _filters["platform"]
ratings_key = _filters["ratings_key"]
sentiments_key = _filters["sentiments_key"]
keyword_query = _filters["keyword"]

dash: dict[str, Any] = {}
try:
    with st.spinner("Loading Customer Insights…"):
        dash = (
            cached_filtered_dashboard(
                data_source=data_source,
                date_range=date_range,
                platform=platform,
                ratings_key=ratings_key,
                sentiments_key=sentiments_key,
                limit=10000,
            )
            or {}
        )
except Exception as exc:
    st.error(f"Could not load insights. Details: {exc}")
    st.warning(
        "Unable to fetch latest reviews. Displaying the most recently analyzed dataset "
        "when available. If Gemini is unavailable, evidence-based fallback insights are shown."
    )
    st.stop()

reviews = dash.get("reviews") or []
insights = dash.get("insights") or {}
sentiment = dash.get("sentiment") or {}
discovery = dash.get("discovery") or {}
validation = dash.get("validation") or {}
review_sources = dash.get("review_sources") or {}
review_kpis = dash.get("review_kpis") or {}
warehouse = dash.get("warehouse_stats") or {}
trend_insights = dash.get("trend_insights") or {}
chart_series = dash.get("chart_series") or {}
extended = dash.get("extended_analysis") or {}

_play_c = int(warehouse.get("playstore_count") or 0)
_apple_c = int(warehouse.get("appstore_count") or 0)
_tc = _play_c + _apple_c
_lc = int(warehouse.get("total_live") or 0)
_source_label = {
    "live": "Live Reviews",
    "all": "All Reviews",
    "combined": "All Reviews",
}.get(data_source, "All Reviews")
st.caption(
    f"Store reviews · Total: **{_tc:,}** "
    f"(Google Play: **{_play_c:,}** · Apple App Store: **{_apple_c:,}**) · "
    f"Live (06 Jul 2026→latest): **{_lc:,}** · "
    f"Loaded for analysis: **{len(reviews):,}** "
    f"({_source_label})"
)

if not isinstance(reviews, list) or not reviews:
    st.warning(
        "No reviews match the current search (or the warehouse is empty). "
        "Try **All Reviews** or switch to **Live Reviews** to fetch from Google Play "
        "and the App Store."
    )
    st.stop()

_discovery_source = str((dash.get("discovery") or {}).get("source") or "")
_discovery = dash.get("discovery") or {}
if (
    _discovery_source.startswith("fallback-all-keys")
    or _discovery_source.startswith("fallback-auth")
    or _discovery_source.startswith("fallback-error")
    or _discovery_source.startswith("fallback-timeout")
    or _discovery_source.startswith("fallback-no-keys")
    or _discovery.get("error_message")
):
    render_gemini_all_keys_failed_warning(discovery=_discovery)

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
        "or reload the app to retry automatic collection and analysis."
    )


# =============================================================================
# Visible Reviews (interactive table + search + export) — ADDITIVE
# =============================================================================
def _section_visible_reviews() -> None:
    render_visible_reviews_table(
        reviews,
        data_source=data_source,
        keyword=keyword_query,
        key_prefix="ci",
    )


_safe_section("Visible Reviews", _section_visible_reviews)


# =============================================================================
# Live warehouse dashboard
# =============================================================================
def _section_warehouse() -> None:
    st.markdown("---")
    st.header("Live Dashboard")
    _play_n = int(warehouse.get("playstore_count") or 0)
    _apple_n = int(warehouse.get("appstore_count") or 0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Reviews", f"{_play_n + _apple_n:,}")
    c2.metric("Live Reviews", f"{int(warehouse.get('total_live') or 0):,}")
    c3.metric("Google Play Store Reviews", f"{_play_n:,}")
    c4.metric("Apple App Store Reviews", f"{_apple_n:,}")
    c5, c6, c7 = st.columns(3)
    c5.metric("New Reviews Today", f"{int(warehouse.get('new_reviews_today') or 0):,}")
    c6.metric(
        "Last Updated",
        format_last_updated(warehouse.get("last_sync_time") or _refresh.get("last_sync_at")),
    )
    c7.metric(
        "Latest Review Date",
        format_last_updated(warehouse.get("latest_review_date")),
    )
    st.caption(
        f"Live Date Range: **{warehouse.get('live_date_range') or '06 Jul 2026 → Latest'}** · "
        f"Next Refresh: **{format_last_updated(warehouse.get('next_refresh_time') or _refresh.get('next_refresh_at'))}**"
    )


_safe_section("Live Dashboard", _section_warehouse)


# =============================================================================
# AI Analysis (mode-aware)
# =============================================================================
def _section_ai_analysis() -> None:
    st.markdown("---")
    analysis_title = {
        "live": "Live AI Analysis",
        "all": "All Reviews AI Analysis",
        "combined": "All Reviews AI Analysis",
    }.get(data_source, "AI Analysis")
    st.header(analysis_title)
    mode_label = {
        "live": "Live Reviews only (06 Jul 2026 → Latest Available Review)",
        "all": "All Reviews (full merged warehouse)",
        "combined": "All Reviews (full merged warehouse)",
    }.get(data_source, "All Reviews")
    st.caption(f"Gemini / evidence analysis for: **{mode_label}**")
    conf = discovery.get("ai_confidence_score") or extended.get("confidence_score") or 0
    st.metric("Confidence Score", f"{conf}%")
    st.subheader("Executive Summary")
    st.write(
        extended.get("executive_summary")
        or insights.get("ai_summary")
        or "Summary appears after analysis."
    )
    a1, a2 = st.columns(2)
    with a1:
        st.markdown("**Top Pain Points**")
        for item in _as_records(extended.get("top_pain_points") or insights.get("top_customer_problems"))[:6]:
            st.write(f"- {item.get('label') or item.get('pain_point')} ({item.get('count', 0)})")
        st.markdown("**Emerging Problems**")
        for item in _as_records(extended.get("emerging_problems"))[:5]:
            st.write(f"- {item.get('label')} ({item.get('count', 0)})")
        st.markdown("**Feature Requests**")
        for item in _as_records(extended.get("feature_requests"))[:5]:
            st.write(f"- {item.get('label')} ({item.get('count', 0)})")
    with a2:
        st.markdown("**Top Appreciated Features**")
        for item in _as_records(extended.get("top_appreciated_features"))[:6]:
            st.write(f"- {item.get('label')} ({item.get('count', 0)})")
        st.markdown("**New Trends**")
        for item in _as_records(extended.get("new_trends"))[:5]:
            st.write(f"- {item.get('label')} ({item.get('count', 0)})")
        st.markdown("**Customer Segments**")
        for item in _as_records(extended.get("customer_segments") or insights.get("all_segments"))[:5]:
            st.write(f"- {item.get('label')} ({item.get('count', 0)})")
    st.markdown("**Product Opportunities**")
    for item in _as_records(extended.get("product_opportunities"))[:5]:
        st.write(f"- {item.get('label')} ({item.get('count', 0)})")
    st.markdown("**Growth Recommendations**")
    for line in _as_str_list(
        extended.get("growth_recommendations") or discovery.get("growth_recommendations")
    )[:8]:
        st.write(f"- {line}")
    st.markdown("**PM Recommendations**")
    for line in _as_str_list(extended.get("pm_recommendations") or discovery.get("pm_recommendations"))[:8]:
        st.write(f"- {line}")


_safe_section("AI Analysis", _section_ai_analysis)


# =============================================================================
# New Insights (week-over-week)
# =============================================================================
def _section_new_insights() -> None:
    st.markdown("---")
    st.header("New Insights")
    n1, n2 = st.columns(2)
    with n1:
        st.markdown("**NEW issues appearing this week**")
        items = _as_records(trend_insights.get("new_issues_this_week"))
        if items:
            for item in items:
                st.write(f"- {item.get('label')} ({item.get('count', 0)})")
        else:
            st.caption("No brand-new issues detected this week.")
        st.markdown("**Trending complaints**")
        for item in _as_records(trend_insights.get("trending_complaints"))[:6]:
            st.write(
                f"- {item.get('label')} · this week {item.get('count', 0)} "
                f"(last week {item.get('last_week', 0)})"
            )
        st.markdown("**Problems increasing over time**")
        for item in _as_records(trend_insights.get("problems_increasing"))[:5]:
            st.write(
                f"- {item.get('label')} · Δ +{item.get('delta', 0)} "
                f"({item.get('last_week', 0)} → {item.get('this_week', 0)})"
            )
    with n2:
        st.markdown("**Trending feature requests**")
        for item in _as_records(trend_insights.get("trending_feature_requests"))[:6]:
            st.write(
                f"- {item.get('label')} · this week {item.get('count', 0)} "
                f"(last week {item.get('last_week', 0)})"
            )
        st.markdown("**Problems decreasing over time**")
        for item in _as_records(trend_insights.get("problems_decreasing"))[:5]:
            st.write(
                f"- {item.get('label')} · Δ {item.get('delta', 0)} "
                f"({item.get('last_week', 0)} → {item.get('this_week', 0)})"
            )
        st.markdown("**Sentiment change vs last week**")
        delta = trend_insights.get("sentiment_change_vs_last_week") or {}
        if isinstance(delta, dict) and delta:
            d1, d2, d3 = st.columns(3)
            d1.metric("Positive", f"{float(delta.get('Positive', 0)):+.1f} pp")
            d2.metric("Neutral", f"{float(delta.get('Neutral', 0)):+.1f} pp")
            d3.metric("Negative", f"{float(delta.get('Negative', 0)):+.1f} pp")
        else:
            st.caption("Not enough week-over-week data yet.")


_safe_section("New Insights", _section_new_insights)


# =============================================================================
# Visualizations
# =============================================================================
def _section_visualizations() -> None:
    st.markdown("---")
    st.header("Visualizations")
    timeline = _as_records(chart_series.get("review_timeline"))
    if timeline:
        fig = px.line(pd.DataFrame(timeline), x="date", y="count", title="Review Timeline")
        _plot(fig)
    sent_tr = _as_records(chart_series.get("sentiment_trend"))
    if sent_tr:
        sdf = pd.DataFrame(sent_tr)
        melt = sdf.melt(id_vars=["date"], var_name="sentiment", value_name="count")
        fig = px.line(melt, x="date", y="count", color="sentiment", title="Sentiment Trend")
        _plot(fig)
    rat = _as_records(chart_series.get("rating_trend"))
    if rat:
        fig = px.line(pd.DataFrame(rat), x="date", y="avg_rating", title="Rating Trend")
        _plot(fig)
    r1, r2, r3 = st.columns(3)
    with r1:
        daily = _as_records(chart_series.get("daily_reviews"))
        if daily:
            fig = px.bar(pd.DataFrame(daily).tail(30), x="date", y="count", title="Daily Reviews")
            _plot(fig, height=280)
    with r2:
        weekly = _as_records(chart_series.get("weekly_reviews"))
        if weekly:
            fig = px.bar(pd.DataFrame(weekly).tail(12), x="week", y="count", title="Weekly Reviews")
            _plot(fig, height=280)
    with r3:
        monthly = _as_records(chart_series.get("monthly_reviews"))
        if monthly:
            fig = px.bar(pd.DataFrame(monthly).tail(12), x="month", y="count", title="Monthly Reviews")
            _plot(fig, height=280)
    kw = _as_records(chart_series.get("top_keywords"))
    if kw:
        fig = px.bar(
            pd.DataFrame(kw).head(15),
            x="count",
            y="keyword",
            orientation="h",
            title="Top Keywords",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        _plot(fig, height=360)
    for title, key in [
        ("Category Trend", "category_trend"),
        ("Pain Point Trend", "pain_point_trend"),
        ("Feature Request Trend", "feature_request_trend"),
    ]:
        rows = _as_records(chart_series.get(key))
        if not rows:
            continue
        rdf = pd.DataFrame(rows)
        if not _has_cols(rdf, ["period", "label", "count"]):
            continue
        fig = px.bar(
            rdf.tail(40),
            x="period",
            y="count",
            color="label",
            title=title,
            barmode="stack",
        )
        _plot(fig, height=320)


_safe_section("Visualizations", _section_visualizations)


# =============================================================================
# 1. Review Sources
# =============================================================================
def _section_sources() -> None:
    st.markdown("---")
    st.header("Review Sources")
    src_keys = [
        "Google Play Reviews",
        "Apple App Store Reviews",
        "Merged Reviews",
    ]
    cols = st.columns(3)
    labels = {
        "Google Play Reviews": "Google Play Store Reviews",
        "Apple App Store Reviews": "Apple App Store Reviews",
        "Merged Reviews": "Total Reviews",
    }
    for i, key in enumerate(src_keys):
        try:
            cols[i].metric(labels.get(key, key), f"{int(review_sources.get(key, 0) or 0):,}")
        except Exception:
            cols[i].metric(labels.get(key, key), "0")
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
    k5.metric("Last Updated", format_last_updated(_refresh.get("last_sync_at")))


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
        st.dataframe(pdf, width="stretch", hide_index=True, height=380)


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
        st.dataframe(tdf, width="stretch", hide_index=True)


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
        st.dataframe(seg_df[display_cols], width="stretch", hide_index=True)
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
    st.dataframe(bdf[show_cols], width="stretch", hide_index=True)
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
    st.dataframe(odf, width="stretch", hide_index=True)
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
# 12. Product Manager Insights
# =============================================================================
def _pm_insight_cards(discovery_payload: dict[str, Any]) -> list[dict[str, str]]:
    """
    Reshape existing Gemini discovery fields into PM-facing cards.
    UI-only — does not call Gemini or change analysis logic.
    """
    cards: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(insight: str, impact: str, action: str) -> None:
        insight = (insight or "").strip()
        impact = (impact or "").strip()
        action = (action or "").strip()
        if not insight or not action:
            return
        if not impact:
            impact = (
                "This matters for product experience and growth — unresolved friction "
                "keeps shoppers in familiar categories and limits basket expansion."
            )
        key = f"{insight[:90].lower()}|{action[:60].lower()}"
        if key in seen:
            return
        seen.add(key)
        cards.append({"insight": insight, "impact": impact, "action": action})

    rca = discovery_payload.get("root_cause_analysis") or {}
    if not isinstance(rca, dict):
        rca = {}

    for cause in _as_records(rca.get("causes")):
        title = str(cause.get("root_cause") or "").strip()
        detail = str(cause.get("description") or "").strip()
        if title and detail:
            insight = detail if title.lower() in detail.lower() else f"{title}. {detail}"
        else:
            insight = detail or title
        biz = str(cause.get("business_impact") or "").strip().title()
        if biz in {"High", "Medium", "Low"}:
            impact = (
                f"{biz} business impact — this root cause influences whether customers "
                "stay in repeat-purchase loops or explore new categories."
            )
        else:
            impact = str(cause.get("business_impact") or "").strip()
        action = str(
            cause.get("suggested_solution")
            or cause.get("suggested_product_opportunity")
            or ""
        ).strip()
        _add(insight, impact, action)
        if len(cards) >= 6:
            return cards[:6]

    opps = _as_records(discovery_payload.get("category_exploration_opportunities"))
    habits = _as_str_list(discovery_payload.get("shopping_habit_insights"))
    barriers = _as_records(discovery_payload.get("discovery_barriers"))
    recs = _as_str_list(discovery_payload.get("growth_recommendations"))
    pm_lines = _as_str_list(rca.get("pm_insights"))

    for i, rec in enumerate(recs):
        if len(cards) >= 6:
            break
        if i < len(opps):
            o = opps[i]
            insight = (
                f"Shoppers in {o.get('current_category', 'core categories')} show "
                f"room to explore {o.get('suggested_new_category', 'adjacent categories')}. "
                f"{o.get('reason') or ''}"
            ).strip()
        elif i < len(habits):
            insight = habits[i]
        elif i < len(pm_lines):
            insight = pm_lines[i]
        elif i < len(barriers):
            b = barriers[i]
            insight = (
                f"{b.get('barrier') or 'Discovery barrier'}: "
                f"{b.get('representative_review') or 'Observed repeatedly in customer feedback.'}"
            )
        else:
            insight = f"Customer feedback highlights a product opportunity: {rec}"

        if i < len(barriers):
            sev = str(barriers[i].get("severity") or "").strip().title()
            impact = (
                f"{sev + ' severity — ' if sev else ''}"
                "Discovery friction and habit-driven shopping reduce cross-category "
                "adoption and customer lifetime value."
            )
        else:
            impact = (
                "Low cross-category adoption and weak discovery reduce basket expansion "
                "and long-term customer value."
            )
        _add(insight, impact, rec)

    for line in pm_lines:
        if len(cards) >= 6:
            break
        # Use remaining recommendations as actions when available
        action = recs[len(cards) % len(recs)] if recs else (
            "Validate with a focused discovery experiment and measure category attach rate."
        )
        _add(line, "", action)

    return cards[:6]


def _section_recs() -> None:
    st.markdown("---")
    st.header("📊 Product Manager Insights")
    st.caption(
        "Actionable Product Manager insights derived from the existing Gemini-analyzed "
        "review set (root causes, discovery barriers, and growth recommendations)."
    )
    cards = _pm_insight_cards(discovery if isinstance(discovery, dict) else {})
    if len(cards) < 4:
        # Still show whatever we have; empty → info
        if not cards:
            st.info("Product Manager insights appear after discovery analysis completes.")
            return
    for card in cards:
        try:
            with st.container(border=True):
                st.markdown("📌 **Insight**")
                st.write(card["insight"])
                st.markdown("🎯 **Impact**")
                st.write(card["impact"])
                st.markdown("💡 **Recommended PM Action**")
                st.write(card["action"])
        except TypeError:
            st.markdown(
                f"📌 **Insight**  \n{card['insight']}  \n\n"
                f"🎯 **Impact**  \n{card['impact']}  \n\n"
                f"💡 **Recommended PM Action**  \n{card['action']}"
            )


_safe_section("Product Manager Insights", _section_recs)


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
            st.dataframe(sample[cols].head(25), width="stretch", hide_index=True)
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
