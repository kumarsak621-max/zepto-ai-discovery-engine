"""AI Product Discovery Report — assignment questions answered from live review AI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
from src.paths import ensure_runtime_dirs
from src.review_sync import get_refresh_status
from src.streamlit_playstore import format_last_updated, render_last_updated_caption

st.set_page_config(
    page_title="AI Product Discovery Report",
    page_icon="🧭",
    layout="wide",
)

_CHART_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=10, r=10, t=40, b=10),
)


def _render_chart(chart: dict[str, Any] | None) -> None:
    if not chart:
        return
    labels = chart.get("labels") or []
    values = chart.get("values") or []
    if not labels or not values or len(labels) != len(values):
        st.caption("Visualization will appear when enough evidence is available.")
        return
    df = pd.DataFrame({"label": labels, "value": values})
    title = chart.get("title") or "Insight"
    ctype = str(chart.get("type") or "bar").lower()
    try:
        if ctype == "pie":
            fig = px.pie(df, names="label", values="value", title=title)
        else:
            fig = px.bar(df, x="label", y="value", title=title)
        fig.update_layout(**_CHART_LAYOUT)
        st.plotly_chart(fig, width="stretch")
    except Exception as exc:
        st.caption(f"Chart unavailable: {exc}")


def _render_quality(q: dict[str, Any] | None) -> None:
    q = q or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Confidence Score", f"{float(q.get('confidence_score') or 0):.0f}%")
    c2.metric("Evidence Count", f"{int(q.get('evidence_count') or 0):,}")
    c3.metric("Reviews Used", f"{int(q.get('reviews_used') or 0):,}")
    sources = q.get("data_sources") or []
    c4.metric("Data Sources", ", ".join(sources[:2]) if sources else "—")


def _render_question(block: dict[str, Any]) -> None:
    st.markdown("---")
    st.subheader(block.get("question") or "Question")
    st.markdown("**Answer**")
    st.write(block.get("answer") or "—")

    st.markdown("**Evidence**")
    for line in block.get("evidence") or []:
        st.write(f"- {line}")

    quotes = [q for q in (block.get("quotes") or []) if q]
    if quotes:
        st.markdown("**Key Quotes**")
        for quote in quotes:
            st.markdown(f"> {quote}")

    # Extra structured lists when present
    if block.get("top_reasons"):
        st.markdown("**Top Reasons**")
        for reason in block["top_reasons"][:8]:
            st.write(f"- {reason}")
    if block.get("barriers"):
        st.markdown("**Top Barriers (ranked)**")
        for b in block["barriers"][:10]:
            st.write(
                f"- **{b.get('label')}** · {b.get('count')} · "
                f"severity {b.get('severity', '—')}"
            )
    if block.get("channels"):
        st.markdown("**Discovery Channels**")
        for c in block["channels"][:8]:
            st.write(
                f"- **{c.get('label')}** · {c.get('share', c.get('percentage', 0))}% "
                f"({c.get('count', 0)} mentions)"
            )
    if block.get("dimensions"):
        st.markdown("**Habit Dimensions**")
        for k, v in (block.get("dimensions") or {}).items():
            st.write(f"- **{k}**: {v}%")
    if block.get("needs"):
        st.markdown("**Information Needs**")
        for n in block["needs"][:9]:
            st.write(f"- **{n.get('label')}** · {n.get('count')} ({n.get('percentage')}%)")
    if block.get("frustrations"):
        st.markdown("**Top Recurring Complaints**")
        for i, f in enumerate(block["frustrations"][:12], start=1):
            st.write(f"{i}. **{f.get('label')}** — {f.get('count')} reviews")
    if block.get("segments"):
        st.markdown("**Segments**")
        for s in block["segments"][:10]:
            st.write(
                f"- **{s.get('label')}** · {s.get('percentage', 0)}% "
                f"— {s.get('characteristics') or ''}"
            )
    if block.get("unmet_needs"):
        st.markdown("**Unmet Needs**")
        for u in block["unmet_needs"][:12]:
            st.write(
                f"- **{u.get('label')}** ({u.get('type', 'Need')}) — "
                f"{u.get('detail') or u.get('count')}"
            )

    _render_chart(block.get("chart"))
    _render_quality(block.get("quality"))


try:
    ensure_runtime_dirs()
    init_db()
except Exception as exc:
    st.error(f"Could not initialize storage. Details: {exc}")
    st.stop()

st.title("🧭 AI Product Discovery Report")
st.caption(
    "Evidence-based answers generated automatically from customer reviews, "
    "AI analysis, and product feedback."
)

ensure_live_reviews_loaded()
try:
    render_auto_status_sidebar()
except Exception:
    pass
render_auto_collect_warning()

_refresh = get_refresh_status()
try:
    render_last_updated_caption()
except Exception:
    st.caption(f"Last Updated: {format_last_updated(_refresh.get('last_sync_at'))}")
st.caption(
    f"Next Refresh: **{format_last_updated(_refresh.get('next_refresh_at'))}** "
    f"(report regenerates from the latest review dataset)"
)

from src.streamlit_cache import cached_product_discovery_report
from src.review_source_ui import (
    ensure_source_data_loaded,
    render_review_filters,
    render_review_source_selector,
)

data_source = render_review_source_selector(key_prefix="pdr")
ensure_source_data_loaded(data_source, key_prefix="pdr")
_filters = render_review_filters(key_prefix="pdr")
platform = _filters["platform"]

try:
    with st.spinner("Generating AI Product Discovery Report from the current review dataset…"):
        from src.database import get_collection_stats
        from src.review_analytics import apply_review_filters
        from src.product_discovery_report import build_product_discovery_report
        from src.discovery_insights import build_discovery_dashboard

        stats = get_collection_stats()
        # Prefer filtered merged store dataset for the report
        store_reviews = apply_review_filters(
            data_source=data_source,
            platform=platform,
            limit=5000,
        )
        if store_reviews:
            dash = build_discovery_dashboard(
                reviews=store_reviews,
                limit=5000,
                analysis_mode=data_source,
            )
            report = build_product_discovery_report(
                reviews=dash.get("reviews") or store_reviews,
                insights=dash.get("insights") or {},
                discovery=dash.get("discovery") or {},
                validation=dash.get("validation") or {},
                limit=5000,
            )
        else:
            report = cached_product_discovery_report(
                reviews_fingerprint=str(stats.get("total") or 0),
                analyzed_fingerprint=str(stats.get("analyzed_count") or 0),
                source_fingerprint=str(
                    stats.get("last_ai_analysis") or stats.get("last_update") or ""
                ),
                limit=5000,
            )
except Exception as exc:
    st.error(f"Could not generate the discovery report. Details: {exc}")
    st.info("Existing Dashboard and Customer Insights remain available.")
    st.stop()

meta = report.get("meta") or {}
m1, m2, m3 = st.columns(3)
m1.metric("Reviews Used", f"{int(meta.get('reviews_used') or 0):,}")
m2.metric("Analyzed Reviews", f"{int(meta.get('analyzed_reviews') or 0):,}")
m3.metric("AI Confidence", f"{float(meta.get('ai_confidence') or 0):.0f}%")
st.caption(
    "Data sources: "
    + ", ".join(meta.get("sources") or ["Google Play", "Apple App Store"])
)

# Executive summary first for leadership skim
st.markdown("---")
st.header("Executive Summary")
exec_sum = report.get("executive_summary") or {}
st.markdown("**Overall Findings**")
st.write(exec_sum.get("overall_findings") or "—")
e1, e2 = st.columns(2)
with e1:
    st.markdown("**Top Opportunities**")
    for item in exec_sum.get("top_opportunities") or []:
        st.write(f"- {item}")
    st.markdown("**Highest Impact Recommendation**")
    st.write(exec_sum.get("highest_impact_recommendation") or "—")
with e2:
    st.markdown("**Largest Risks**")
    for item in exec_sum.get("largest_risks") or []:
        st.write(f"- {item}")
    st.markdown("**Expected Growth Impact**")
    st.write(exec_sum.get("expected_growth_impact") or "—")

# Q1–Q8
for block in report.get("questions") or []:
    try:
        _render_question(block)
    except Exception as exc:
        st.warning(f"Question section failed: {exc}")

# PM Recommendations
st.markdown("---")
st.header("Top 10 Product Recommendations")
st.caption("Prioritized by Impact, Effort, Business Value, User Value, and Risk.")
recs = report.get("recommendations") or []
if not recs:
    st.info("Recommendations will appear after AI analysis completes.")
else:
    rdf = pd.DataFrame(recs)
    show_cols = [
        c
        for c in (
            "rank",
            "recommendation",
            "impact",
            "effort",
            "business_value",
            "user_value",
            "risk",
            "priority_score",
        )
        if c in rdf.columns
    ]
    st.dataframe(
        rdf[show_cols],
        width="stretch",
        hide_index=True,
        column_config={
            "rank": "Rank",
            "recommendation": st.column_config.TextColumn("Recommendation", width="large"),
            "impact": "Impact",
            "effort": "Effort",
            "business_value": "Business Value",
            "user_value": "User Value",
            "risk": "Risk",
            "priority_score": "Priority Score",
        },
    )
    _render_chart(report.get("recommendations_chart"))
    for rec in recs[:10]:
        with st.expander(f"#{rec.get('rank')} · {str(rec.get('recommendation') or '')[:90]}"):
            st.write(rec.get("recommendation"))
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Impact", rec.get("impact"))
            c2.metric("Effort", rec.get("effort"))
            c3.metric("Business Value", rec.get("business_value"))
            c4.metric("User Value", rec.get("user_value"))
            c5.metric("Risk", rec.get("risk"))
