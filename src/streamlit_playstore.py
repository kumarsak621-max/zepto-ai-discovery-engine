"""Shared Streamlit UI helpers for Google Play review fetch."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.config import PLAYSTORE_APP_ID, PLAYSTORE_REVIEW_COUNT
from src.playstore_scraper import get_last_updated_timestamp, get_reviews_cache_meta
from src.streamlit_cache import clear_data_caches


def format_last_updated(ts: str | None = None) -> str:
    value = ts or get_last_updated_timestamp()
    if not value:
        return "Never"
    return value.replace("T", " ")[:19] + " UTC"


def render_last_updated_caption(*, sidebar: bool = False) -> None:
    meta = get_reviews_cache_meta()
    count = meta.get("count")
    stamp = format_last_updated(meta.get("last_updated"))
    text = (
        f"Last Updated: **{stamp}** · Cached Play Store reviews: {count:,}"
        if count
        else f"Last Updated: **{stamp}**"
    )
    (st.sidebar.caption if sidebar else st.caption)(text)


def _set_progress(progress_bar: Any, pct: float, msg: str, status: Any) -> None:
    clamped = min(max(float(pct), 0.0), 1.0)
    try:
        progress_bar.progress(clamped, text=msg)
    except TypeError:
        # Older Streamlit without text= support
        progress_bar.progress(clamped)
    status.caption(msg)


def run_fetch_with_progress(
    *,
    force_refresh: bool = False,
    count: int | None = None,
    analyze_limit: int | None = None,
) -> dict[str, Any]:
    """
    Run Play Store fetch with a visible progress bar, then return pipeline result.
    Automatically triggers Gemini analysis via run_playstore_fetch.
    """
    from src.data_pipeline import run_playstore_fetch

    target = count or PLAYSTORE_REVIEW_COUNT
    try:
        progress = st.progress(0.0, text="Starting Google Play download…")
    except TypeError:
        progress = st.progress(0.0)
    status = st.empty()

    def _on_progress(pct: float, msg: str) -> None:
        _set_progress(progress, pct, msg, status)

    try:
        result = run_playstore_fetch(
            count=target,
            analyze_limit=analyze_limit or max(500, target),
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
            "error": (
                "Google Play is unavailable or the request was blocked. "
                f"{exc}"
            ),
            "playstore_count": 0,
            "new_reviews": 0,
            "analyzed_count": 0,
        }


def show_fetch_result(result: dict[str, Any]) -> None:
    """Display success / error messaging for a Play Store fetch run."""
    if result.get("status") == "success":
        meta = result.get("app_metadata") or {}
        title = meta.get("title") or "Zepto"
        score = meta.get("score")
        cache_note = " (from cache)" if result.get("used_cache") else ""
        stamp = format_last_updated(result.get("download_timestamp"))
        st.success(
            f"Downloaded **{result.get('playstore_count', 0)}** English reviews for "
            f"**{title}**{cache_note}"
            + (f" (⭐ {score:.2f})" if isinstance(score, (int, float)) else "")
            + f". Saved to `data/reviews.csv`. "
            f"New in DB: {result.get('new_reviews', 0)} · "
            f"Analyzed: {result.get('analyzed_count', 0)} · "
            f"Timestamp: {stamp}"
        )
        st.info(
            "Dashboards and the AI Review Chatbot now use the latest reviews — "
            "no manual CSV upload required."
        )
    else:
        st.error(
            "Google Play reviews could not be fetched. "
            f"{result.get('error') or 'The service may be temporarily unavailable. Try again later.'}"
        )


def render_sidebar_fetch_controls() -> None:
    """Sidebar: Fetch Latest Google Play Reviews button + cache options."""
    st.sidebar.markdown("---")
    st.sidebar.subheader("Google Play Reviews")
    st.sidebar.caption(f"App ID: `{PLAYSTORE_APP_ID}`")
    render_last_updated_caption(sidebar=True)

    force = st.sidebar.checkbox(
        "Force refresh (ignore cache)",
        value=False,
        help="By default, cached reviews in data/reviews.csv are reused while fresh.",
        key="sidebar_force_playstore_refresh",
    )

    if st.sidebar.button(
        "📥 Fetch Latest Google Play Reviews",
        type="primary",
        use_container_width=True,
        key="sidebar_fetch_playstore",
    ):
        result = run_fetch_with_progress(force_refresh=force)
        show_fetch_result(result)
        if result.get("status") == "success":
            st.rerun()
