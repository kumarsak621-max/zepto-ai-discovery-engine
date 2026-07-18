"""Streamlit UI for live review collection, manual upload, and analysis."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.config import PLAYSTORE_APP_ID, has_appstore
from src.data_pipeline import get_live_meta
from src.manual_reviews import (
    clear_manual_reviews,
    get_manual_meta,
    parse_uploaded_file,
    save_manual_reviews,
)
from src.streamlit_cache import clear_data_caches
from src.streamlit_playstore import _set_progress, format_last_updated


def show_source_metrics(meta_or_result: dict[str, Any] | None = None) -> None:
    """Display per-source counts + Last Updated."""
    data = meta_or_result or get_live_meta()
    manual_meta = get_manual_meta()
    playstore = int(data.get("playstore_count") or 0)
    appstore = int(data.get("appstore_count") or 0)
    manual = int(data.get("manual_count") or manual_meta.get("count") or 0)
    merged = int(data.get("merged_count") or 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Google Play Reviews", f"{playstore:,}")
    c2.metric("Apple App Store Reviews", f"{appstore:,}")
    c3.metric("Manual Uploaded Reviews", f"{manual:,}")
    c4.metric("Merged Reviews", f"{merged:,}")

    stamp = format_last_updated(data.get("download_timestamp") or data.get("last_updated"))
    st.caption(f"Last Updated: **{stamp}**")


def show_live_result(result: dict[str, Any]) -> None:
    """Display Last Updated, reviews fetched, and per-source counts."""
    show_source_metrics(result)

    if result.get("status") == "success":
        cache_note = " (Play Store cache reused where fresh)" if result.get("used_cache") else ""
        st.success(
            f"Reviews ready{cache_note}. "
            f"Merged **{result.get('merged_count', 0)}** unique reviews · "
            f"New in DB: {result.get('new_reviews', 0)} · "
            f"Analyzed: {result.get('analyzed_count', 0)}"
        )
        st.info(
            "Dashboard, charts, KPIs, pain points, shopping habits, categories, "
            "segments, opportunities, executive summary, and chatbot context "
            "now use this merged dataset."
        )
        for msg in result.get("source_messages") or []:
            if "unavailable" in msg.lower() or "not configured" in msg.lower():
                st.warning(msg)
            else:
                st.caption(msg)
    else:
        st.error(
            result.get("error")
            or "Could not complete review analysis. Try again."
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
            "manual_count": 0,
            "merged_count": 0,
            "new_reviews": 0,
            "analyzed_count": 0,
        }


def render_manual_upload_controls(*, key_prefix: str = "sidebar") -> None:
    """Sidebar / page control: Upload Manual Reviews (CSV / Excel)."""
    st.markdown("📂 **Upload Manual Reviews**")
    st.caption("Accepts `.csv` or `.xlsx`. Columns auto-detected.")

    uploaded = st.file_uploader(
        "Choose a CSV or Excel file",
        type=["csv", "xlsx"],
        key=f"{key_prefix}_manual_upload",
        help="Detects columns like review_text, text, content, review, rating, date, source.",
    )

    manual_meta = get_manual_meta()
    if manual_meta.get("count"):
        st.caption(
            f"Loaded: **{manual_meta.get('count', 0)}** reviews"
            + (
                f" from `{manual_meta.get('filename')}`"
                if manual_meta.get("filename")
                else ""
            )
        )

    if uploaded is not None:
        try:
            records, info = parse_uploaded_file(uploaded)
            if info.get("error"):
                st.error(info["error"])
                if info.get("columns"):
                    st.caption(f"Columns found: {', '.join(map(str, info['columns']))}")
            elif not records:
                st.warning("No usable reviews found in the file (need text ≥ 15 chars).")
            else:
                save_manual_reviews(records, filename=info.get("filename") or uploaded.name)
                detected = info.get("detected") or {}
                st.success(
                    f"Uploaded **{len(records)}** reviews "
                    f"(from {info.get('rows_in_file', 0)} rows)."
                )
                st.caption(
                    "Detected columns — "
                    f"text: `{detected.get('text')}` · "
                    f"rating: `{detected.get('rating')}` · "
                    f"date: `{detected.get('date')}` · "
                    f"source: `{detected.get('source')}` · "
                    f"id: `{detected.get('review_id')}`"
                )
                st.info(
                    "These reviews will be merged with Google Play + App Store "
                    "when you click **▶ Run Review Analysis**."
                )
        except Exception as exc:
            st.error(f"Could not read upload. Details: {exc}")

    if manual_meta.get("count") and st.button(
        "Clear manual upload",
        use_container_width=True,
        key=f"{key_prefix}_clear_manual",
    ):
        clear_manual_reviews()
        st.rerun()


def render_live_review_controls(*, key_prefix: str = "home") -> None:
    """
    Collection UI:

    • Run Review Analysis — Play + App Store + Manual (cache when fresh)
    • Refresh Live Reviews — force newest download + re-analyze
    """
    st.subheader("Review Analysis")
    st.caption(
        f"Merges Google Play (`{PLAYSTORE_APP_ID}`)"
        + (", Apple App Store" if has_appstore() else "")
        + ", and any manually uploaded CSV/Excel reviews before Gemini analysis."
    )

    meta = get_live_meta()
    show_source_metrics(meta)
    if not meta.get("last_updated"):
        st.caption("Last Updated: **Never** — run analysis to collect reviews.")

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
    """Sidebar: manual upload + live review controls."""
    st.sidebar.markdown("---")
    with st.sidebar:
        render_manual_upload_controls(key_prefix="sidebar")

    st.sidebar.markdown("---")
    st.sidebar.subheader("Live Reviews")
    meta = get_live_meta()
    manual_meta = get_manual_meta()
    st.sidebar.caption(
        f"Last Updated: **{format_last_updated(meta.get('last_updated'))}**"
    )
    st.sidebar.caption(
        f"Play: {meta.get('playstore_count', 0)} · "
        f"App Store: {meta.get('appstore_count', 0)} · "
        f"Manual: {meta.get('manual_count', manual_meta.get('count', 0))} · "
        f"Merged: {meta.get('merged_count', 0)}"
    )

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
