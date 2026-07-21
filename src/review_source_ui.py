"""
Shared Review Source controls — selector, keyword search, visible table, export.

Review Source options: Live Reviews | All Reviews.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from src.review_viewer import (
    MAX_DISPLAY_REVIEWS_PER_DAY,
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
    """
    Store filter + keyword search.

    Platform options: All Reviews | Google Play Store only | Apple App Store only.
    Live/All Review Source selector remains separate.
    """
    st.caption(
        "Reviews are collected from Google Play Store and Apple App Store, "
        "merged and deduplicated before AI analysis. "
        "Live Reviews = 06 Jul 2026 onward · All Reviews = full warehouse."
    )
    f1, f2 = st.columns([1, 2])
    with f1:
        platform_label = st.selectbox(
            "Store",
            options=[
                "All Reviews",
                "Google Play Store only",
                "Apple App Store only",
            ],
            index=0,
            key=f"{key_prefix}_platform",
            help="Filter which store’s reviews are shown and analyzed on this page.",
        )
    with f2:
        keyword = st.text_input(
            "Search reviews",
            value="",
            placeholder="Search review text or reviewer name…",
            key=f"{key_prefix}_keyword_search",
        )

    platform = {
        "All Reviews": "both",
        "Google Play Store only": "playstore",
        "Apple App Store only": "appstore",
    }.get(platform_label, "both")

    return {
        "date_range": "all",
        "platform": platform,
        "ratings": [],
        "sentiments": [],
        "keyword": keyword,
        "ratings_key": "",
        "sentiments_key": "",
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
                with st.spinner("Fetching newest Zepto Google Play and App Store reviews…"):
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
    """
    Render interactive Visible Reviews table + CSV/Excel export.

    `reviews` is the full selected-source dataset (AI/dashboard use this elsewhere).
    Only the table/export apply a display cap of 5 reviews per calendar date.
    """
    matched = filter_by_keyword(reviews, keyword)

    st.markdown("---")
    st.header("Visible Reviews")
    captions = {
        "live": "Zepto Live Reviews — 06 Jul 2026 to Latest Available Review (auto-updates)",
        "all": "All Zepto Reviews — full merged warehouse (deduplicated)",
        "combined": "All Zepto Reviews — full merged warehouse (deduplicated)",
    }
    st.caption(captions.get(str(data_source).lower(), "Zepto product reviews"))
    st.info(
        "Showing up to 5 reviews per day. AI analysis and dashboard metrics are based "
        "on the complete review dataset."
    )

    display_df = reviews_to_display_df(
        matched,
        data_source=data_source,
        max_per_day=MAX_DISPLAY_REVIEWS_PER_DAY,
    )
    m1, m2 = st.columns(2)
    m1.metric("Reviews in dataset (selected source)", f"{len(reviews):,}")
    m2.metric("Reviews shown in table", f"{len(display_df):,}")
    if display_df.empty:
        st.info("No reviews match the current keyword search.")
        return matched

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        height=min(560, 80 + min(len(display_df), 18) * 35),
        column_config={
            "Review Date": st.column_config.TextColumn("Review Date", width="small"),
            "Source": st.column_config.TextColumn("Source", width="medium"),
            "Rating": st.column_config.NumberColumn("Rating", format="%.1f", width="small"),
            "Review Text": st.column_config.TextColumn("Review Text", width="large"),
            "Sentiment": st.column_config.TextColumn("Sentiment", width="small"),
            "Reviewer Name": st.column_config.TextColumn("Reviewer Name", width="medium"),
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
            width="stretch",
            key=f"{key_prefix}_download_csv",
        )
    with export_cols[1]:
        try:
            st.download_button(
                label="Download Excel",
                data=dataframe_to_excel_bytes(display_df),
                file_name=f"zepto_reviews_{slug}_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key=f"{key_prefix}_download_xlsx",
            )
        except Exception as exc:
            st.warning(f"Excel export unavailable: {exc}")
    # Return full keyword-matched set (not display-capped)
    return matched
