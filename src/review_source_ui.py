"""
Shared Review Source controls — selector, filters, visible table, export.

Review Source options: Live Reviews | All Reviews (Historical removed).
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
    "Live Reviews",
    "All Reviews",
]

SOURCE_MAP = {
    "Live Reviews": "live",
    "All Reviews": "all",
    # Legacy session values → All Reviews
    "Historical Reviews": "all",
    "Historical + Live Reviews": "all",
    "Historical + Live": "all",
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

_LEGACY_LABELS = {
    "Historical Reviews",
    "Historical + Live Reviews",
    "Historical + Live",
}


def render_review_source_selector(*, key_prefix: str = "ci") -> str:
    """Render Review Source radio. Returns data_source: live|all."""
    st.subheader("Review Source")
    legacy_key = f"{key_prefix}_data_source"
    current = st.session_state.get(legacy_key)
    if current in _LEGACY_LABELS or current not in SOURCE_OPTIONS:
        st.session_state[legacy_key] = "All Reviews"

    label = st.radio(
        "Select which reviews to view and analyze",
        options=SOURCE_OPTIONS,
        index=1,  # Default: All Reviews
        horizontal=True,
        key=legacy_key,
    )
    return SOURCE_MAP.get(label, "all")


def render_review_filters(*, key_prefix: str = "ci") -> dict[str, Any]:
    """Render date/platform/rating/sentiment/keyword filters."""
    with st.expander("Filters", expanded=True):
        st.caption(
            "Live Reviews = 06 Jul 2026 onward · All Reviews = full merged warehouse. "
            "Use Date Range = All Time to see the complete selected source."
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
    Live / All → ensure store sync (force once when switching into Live).
    """
    from src.auto_bootstrap import ensure_live_reviews_loaded
    from src.streamlit_cache import clear_data_caches

    mode_key = f"_{key_prefix}_live_fetch_mode"
    mode = str(data_source or "all").lower()

    if mode == "live":
        if st.session_state.get(mode_key) != "live":
            try:
                with st.spinner("Fetching newest Google Play and App Store reviews…"):
                    ensure_live_reviews_loaded(force=True)
                    clear_data_caches()
            except Exception as exc:
                st.warning(
                    f"Live fetch could not complete; showing stored live reviews. ({exc})"
                )
            st.session_state[mode_key] = "live"
        return

    st.session_state[mode_key] = "all"


def render_visible_reviews_table(
    reviews: list[dict[str, Any]],
    *,
    data_source: str,
    keyword: str = "",
    key_prefix: str = "ci",
) -> list[dict[str, Any]]:
    """Render interactive Visible Reviews table + CSV/Excel export."""
    visible = filter_by_keyword(reviews, keyword)
    st.markdown("---")
    st.header("Visible Reviews")
    captions = {
        "live": "Live Reviews — 06 Jul 2026 to Latest Available Review (auto-updates)",
        "all": "All Reviews — full merged warehouse (deduplicated)",
        "combined": "All Reviews — full merged warehouse (deduplicated)",
    }
    st.caption(captions.get(str(data_source).lower(), "Reviews"))

    display_df = reviews_to_display_df(visible, data_source=data_source)
    st.metric("Reviews shown", f"{len(display_df):,}")
    if display_df.empty:
        st.info("No reviews match the current filters or keyword search.")
        return visible

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        height=min(560, 80 + min(len(display_df), 18) * 35),
        column_config={
            "Date": st.column_config.TextColumn("Date", width="small"),
            "Platform": st.column_config.TextColumn("Platform", width="small"),
            "Rating": st.column_config.NumberColumn("Rating", format="%.1f", width="small"),
            "Review Text": st.column_config.TextColumn("Review Text", width="large"),
            "Sentiment": st.column_config.TextColumn("Sentiment", width="small"),
            "Reviewer": st.column_config.TextColumn("Reviewer", width="medium"),
            "Source": st.column_config.TextColumn("Source", width="small"),
        },
    )

    export_cols = st.columns([1, 1, 2])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    slug = {"live": "live", "all": "all", "combined": "all"}.get(
        str(data_source).lower(), "reviews"
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
