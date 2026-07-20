"""
Shared Review Source controls — selector, filters, visible table, export.

Additive UI helpers used by Customer Insights and Dashboard.
Does not remove or replace existing page sections.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from src.review_viewer import (
    dataframe_to_csv_bytes,
    dataframe_to_excel_bytes,
    filter_by_keyword,
    reviews_to_display_df,
)

SOURCE_OPTIONS = [
    "Historical Reviews",
    "Live Reviews",
    "Historical + Live Reviews",
]

SOURCE_MAP = {
    "Historical Reviews": "historical",
    "Live Reviews": "live",
    "Historical + Live Reviews": "combined",
    "Historical + Live": "combined",
}

DATE_OPTIONS = [
    "All Time",
    "Last 24 Hours",
    "Last 7 Days",
    "Last 30 Days",
    "Last 90 Days",
]

DATE_MAP = {
    "All Time": "all",
    "Last 24 Hours": "24h",
    "Last 7 Days": "7d",
    "Last 30 Days": "30d",
    "Last 90 Days": "90d",
}


def render_review_source_selector(*, key_prefix: str = "ci") -> str:
    """Render Review Source radio. Returns data_source: historical|live|combined."""
    st.subheader("Review Source")
    legacy_key = f"{key_prefix}_data_source"
    if st.session_state.get(legacy_key) == "Historical + Live":
        st.session_state[legacy_key] = "Historical + Live Reviews"

    label = st.radio(
        "Select which reviews to view and analyze",
        options=SOURCE_OPTIONS,
        index=2,
        horizontal=True,
        key=legacy_key,
    )
    return SOURCE_MAP.get(label, "combined")


def render_review_filters(*, key_prefix: str = "ci") -> dict[str, Any]:
    """Render date/platform/rating/sentiment/keyword filters."""
    with st.expander("Filters", expanded=True):
        st.caption(
            "Review Source date bounds always apply first "
            "(Historical: 01 Apr–05 Jul 2026 · Live: 06 Jul 2026 onward). "
            "Use Date Range = All Time to see the full source set."
        )
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            date_range_label = st.selectbox(
                "Date Range",
                DATE_OPTIONS,
                key=f"{key_prefix}_date_range",
            )
        with f2:
            platform_label = st.selectbox(
                "Platform",
                ["Both", "Google Play", "Apple Store"],
                key=f"{key_prefix}_platform",
            )
        with f3:
            rating_sel = st.multiselect(
                "Rating",
                options=[1, 2, 3, 4, 5],
                default=[],
                format_func=lambda x: f"{x}★",
                key=f"{key_prefix}_ratings",
            )
        with f4:
            sentiment_sel = st.multiselect(
                "Sentiment",
                options=["Positive", "Neutral", "Negative"],
                default=[],
                key=f"{key_prefix}_sentiments",
            )
        keyword = st.text_input(
            "Keyword Search",
            value="",
            placeholder="Search review text instantly…",
            key=f"{key_prefix}_keyword_search",
        )

    return {
        "date_range": DATE_MAP.get(date_range_label, "all"),
        "platform": {
            "Both": "both",
            "Google Play": "playstore",
            "Apple Store": "appstore",
        }.get(platform_label, "both"),
        "ratings": list(rating_sel),
        "sentiments": list(sentiment_sel),
        "keyword": keyword,
        "ratings_key": ",".join(str(r) for r in sorted(rating_sel)) if rating_sel else "",
        "sentiments_key": "|".join(sentiment_sel) if sentiment_sel else "",
    }


def ensure_source_data_loaded(data_source: str, *, key_prefix: str = "ci") -> None:
    """
    Historical → do not fetch (DB/cache only).
    Live → force-fetch newest store reviews once per switch into Live.
    Combined → use normal auto-bootstrap (caller may still sync on startup).
    """
    from src.auto_bootstrap import ensure_live_reviews_loaded
    from src.streamlit_cache import clear_data_caches

    mode_key = f"_{key_prefix}_live_fetch_mode"
    if data_source == "historical":
        st.session_state[mode_key] = "historical"
        return

    if data_source == "live":
        if st.session_state.get(mode_key) != "live":
            try:
                with st.spinner("Fetching newest Google Play and App Store reviews…"):
                    ensure_live_reviews_loaded(force=True)
                    clear_data_caches()
            except Exception as exc:
                st.warning(
                    f"Live fetch could not complete; showing last live batch if available. ({exc})"
                )
            st.session_state[mode_key] = "live"
        return

    # combined
    st.session_state[mode_key] = "combined"


def render_visible_reviews_table(
    reviews: list[dict[str, Any]],
    *,
    data_source: str,
    keyword: str = "",
    key_prefix: str = "ci",
) -> list[dict[str, Any]]:
    """Render interactive Visible Reviews table + CSV/Excel export. Returns visible rows."""
    from src.review_filter import HISTORICAL_EMPTY_MSG

    visible = filter_by_keyword(reviews, keyword)
    st.markdown("---")
    st.header("Visible Reviews")
    captions = {
        "historical": "Historical Reviews — 01 Apr 2026 to 05 Jul 2026 (inclusive)",
        "live": "Live Reviews — 06 Jul 2026 to Latest Available Review (auto-updates)",
        "combined": "Historical + Live Reviews — merged & deduplicated",
    }
    st.caption(captions.get(data_source, "Reviews"))

    if str(data_source).lower() == "historical" and not visible:
        st.warning(HISTORICAL_EMPTY_MSG)
        return visible

    display_df = reviews_to_display_df(visible, data_source=data_source)
    # Prefer "Source" column name (spec); keep backward compatibility
    if "Review Source" in display_df.columns and "Source" not in display_df.columns:
        display_df = display_df.rename(columns={"Review Source": "Source"})

    st.metric("Reviews shown", f"{len(display_df):,}")
    if display_df.empty:
        if str(data_source).lower() == "historical":
            st.warning(HISTORICAL_EMPTY_MSG)
        else:
            st.info("No reviews match the current filters or keyword search.")
        return visible

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=min(560, 80 + min(len(display_df), 18) * 35),
        column_config={
            "Review Date": st.column_config.TextColumn("Review Date", width="small"),
            "Platform": st.column_config.TextColumn("Platform", width="small"),
            "Rating": st.column_config.NumberColumn("Rating", format="%.1f", width="small"),
            "Review Text": st.column_config.TextColumn("Review Text", width="large"),
            "Sentiment": st.column_config.TextColumn("Sentiment", width="small"),
            "Source": st.column_config.TextColumn("Source", width="small"),
            "Reviewer Name": st.column_config.TextColumn("Reviewer Name", width="medium"),
        },
    )

    export_cols = st.columns([1, 1, 2])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    slug = {"historical": "historical", "live": "live", "combined": "historical_live"}.get(
        data_source, "reviews"
    )
    with export_cols[0]:
        st.download_button(
            label="Download CSV",
            data=dataframe_to_csv_bytes(display_df),
            file_name=f"zepto_reviews_{slug}_{stamp}.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"{key_prefix}_download_csv",
        )
    with export_cols[1]:
        try:
            st.download_button(
                label="Download Excel",
                data=dataframe_to_excel_bytes(display_df),
                file_name=f"zepto_reviews_{slug}_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"{key_prefix}_download_xlsx",
            )
        except Exception as exc:
            st.warning(f"Excel export unavailable: {exc}")
    return visible
