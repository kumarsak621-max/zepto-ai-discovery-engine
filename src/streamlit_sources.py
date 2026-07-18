"""Streamlit UI for automatic live review collection & analysis."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.config import PLAYSTORE_APP_ID, has_appstore, has_reddit
from src.data_pipeline import get_live_meta
from src.streamlit_cache import clear_data_caches
from src.streamlit_playstore import _set_progress, format_last_updated


def show_live_result(result: dict[str, Any]) -> None:
    """Display Last Updated, reviews fetched, and per-source counts."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Google Play", f"{result.get('playstore_count', 0):,}")
    c2.metric("App Store", f"{result.get('appstore_count', 0):,}")
    c3.metric("Reddit", f"{result.get('reddit_count', 0):,}")
    c4.metric("Merged unique", f"{result.get('merged_count', 0):,}")

    stamp = format_last_updated(result.get("download_timestamp"))
    st.caption(f"Last Updated: **{stamp}**")

    if result.get("status") == "success":
        cache_note = " (Play Store cache reused where fresh)" if result.get("used_cache") else ""
        st.success(
            f"Live reviews ready{cache_note}. "
            f"Fetched **{result.get('merged_count', 0)}** unique reviews · "
            f"New in DB: {result.get('new_reviews', 0)} · "
            f"Analyzed: {result.get('analyzed_count', 0)}"
        )
        st.info(
            "Dashboards, charts, KPIs, AI Summary, and the chatbot now use this merged dataset."
        )
        for msg in result.get("source_messages") or []:
            if "not configured" in msg.lower():
                st.warning(msg)
            else:
                st.caption(msg)
    else:
        st.error(
            result.get("error")
            or "Could not complete live review analysis. Try again."
        )
        for msg in result.get("source_messages") or []:
            st.warning(msg)


def run_live_with_progress(*, force_refresh: bool = False) -> dict[str, Any]:
    from src.data_pipeline import run_live_review_analysis

    label = "Refreshing live reviews…" if force_refresh else "Running review analysis…"
    try:
        progress = st.progress(0.0, text=label)
    except TypeError:
        progress = st.progress(0.0)
    status = st.empty()

    def _on_progress(pct: float, msg: str) -> None:
        _set_progress(progress, pct, msg, status)

    try:
        result = run_live_review_analysis(
            force_refresh=force_refresh,
            progress_callback=_on_progress,
        )
        _set_progress(progress, 1.0, "Complete", status)
        if result.get("status") == "success":
            clear_data_caches()
        return result
    except Exception as exc:
        _set_progress(progress, 1.0, "Failed", status)
        return {
            "status": "failed",
            "error": str(exc),
            "playstore_count": 0,
            "appstore_count": 0,
            "reddit_count": 0,
            "merged_count": 0,
            "new_reviews": 0,
            "analyzed_count": 0,
        }


def render_live_review_controls(*, key_prefix: str = "home") -> None:
    """
    Automatic online collection UI:

    • Run Review Analysis — collect configured sources (uses cache when fresh)
    • Refresh Live Reviews — force newest download + re-analyze
    """
    st.subheader("Live Review Analysis")
    st.caption(
        f"Automatically collects Zepto reviews from Google Play (`{PLAYSTORE_APP_ID}`)"
        + (", Apple App Store" if has_appstore() else "")
        + (", and Reddit" if has_reddit() else "")
        + ". No manual file upload required."
    )

    meta = get_live_meta()
    if meta.get("last_updated"):
        st.caption(
            f"Last Updated: **{format_last_updated(meta.get('last_updated'))}** · "
            f"Play Store: {meta.get('playstore_count', 0)} · "
            f"App Store: {meta.get('appstore_count', 0)} · "
            f"Reddit: {meta.get('reddit_count', 0)} · "
            f"Merged: {meta.get('merged_count', 0)}"
        )
    else:
        st.caption("Last Updated: **Never** — run analysis to download live reviews.")

    if not has_reddit():
        st.warning("Reddit is not configured.")

    b1, b2 = st.columns(2)
    with b1:
        run_clicked = st.button(
            "▶ Run Review Analysis",
            type="primary",
            use_container_width=True,
            key=f"{key_prefix}_run_review_analysis",
        )
    with b2:
        refresh_clicked = st.button(
            "🔄 Refresh Live Reviews",
            use_container_width=True,
            key=f"{key_prefix}_refresh_live_reviews",
        )

    if run_clicked:
        result = run_live_with_progress(force_refresh=False)
        show_live_result(result)
        if result.get("status") == "success":
            st.rerun()

    if refresh_clicked:
        result = run_live_with_progress(force_refresh=True)
        show_live_result(result)
        if result.get("status") == "success":
            st.rerun()


def render_sidebar_source_controls() -> None:
    """Sidebar live review controls."""
    st.sidebar.markdown("---")
    st.sidebar.subheader("Live Reviews")
    meta = get_live_meta()
    st.sidebar.caption(
        f"Last Updated: **{format_last_updated(meta.get('last_updated'))}**"
    )
    if not has_reddit():
        st.sidebar.warning("Reddit is not configured.")

    if st.sidebar.button(
        "▶ Run Review Analysis",
        type="primary",
        use_container_width=True,
        key="sidebar_run_review_analysis",
    ):
        result = run_live_with_progress(force_refresh=False)
        show_live_result(result)
        if result.get("status") == "success":
            st.rerun()

    if st.sidebar.button(
        "🔄 Refresh Live Reviews",
        use_container_width=True,
        key="sidebar_refresh_live_reviews",
    ):
        result = run_live_with_progress(force_refresh=True)
        show_live_result(result)
        if result.get("status") == "success":
            st.rerun()
