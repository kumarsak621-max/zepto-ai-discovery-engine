"""
Automatic review collection on Streamlit app startup.

Collects Google Play + App Store reviews via the existing pipeline,
merges/dedupes, stores in SQLite, and runs Gemini analysis — once per session.
"""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from src.streamlit_cache import clear_data_caches

logger = logging.getLogger(__name__)

_SESSION_DONE = "_auto_collect_done"
_SESSION_RESULT = "_auto_collect_result"
_SESSION_WARNING = "_auto_collect_warning"

FALLBACK_WARNING = (
    "Unable to fetch latest reviews. Displaying the most recently analyzed dataset."
)


def ensure_live_reviews_loaded(*, force: bool = False) -> dict[str, Any]:
    """
    Ensure live reviews are collected and analyzed for this browser session.

    - Runs at most once per session (unless force=True).
    - Uses existing Play Store / App Store collectors + Gemini pipeline.
    - On failure: leaves prior SQLite data in place and sets a friendly warning.
    """
    if not force and st.session_state.get(_SESSION_DONE):
        return st.session_state.get(_SESSION_RESULT) or {}

    result: dict[str, Any] = {"status": "skipped"}
    warning = ""

    try:
        from src.data_pipeline import run_live_review_analysis
        from src.database import get_collection_stats

        with st.spinner(
            "Automatically collecting reviews from Google Play and App Store…"
        ):
            result = run_live_review_analysis(force_refresh=force)

        if result.get("status") == "success":
            clear_data_caches()
            warning = ""
        else:
            # Keep prior analyzed data; surface a non-fatal warning
            stats = get_collection_stats()
            if int(stats.get("total") or 0) > 0:
                warning = FALLBACK_WARNING
            else:
                warning = (
                    FALLBACK_WARNING
                    + " No prior reviews are available yet — try again shortly."
                )
            logger.warning(
                "Auto collection failed: %s", result.get("error") or "unknown"
            )
    except Exception as exc:
        logger.exception("Auto collection crashed")
        result = {"status": "failed", "error": str(exc)}
        try:
            from src.database import get_collection_stats

            if int(get_collection_stats().get("total") or 0) > 0:
                warning = FALLBACK_WARNING
            else:
                warning = FALLBACK_WARNING + f" Details: {exc}"
        except Exception:
            warning = FALLBACK_WARNING

    st.session_state[_SESSION_DONE] = True
    st.session_state[_SESSION_RESULT] = result
    st.session_state[_SESSION_WARNING] = warning
    return result


def render_auto_collect_warning() -> None:
    """Show the fallback warning if the last auto-collect failed."""
    warning = st.session_state.get(_SESSION_WARNING) or ""
    if warning:
        st.warning(warning)


def render_auto_status_sidebar() -> None:
    """Compact sidebar status (no upload / no manual run buttons)."""
    from src.config import PLAYSTORE_APP_ID, has_appstore
    from src.data_pipeline import get_live_meta
    from src.streamlit_playstore import format_last_updated

    st.sidebar.markdown("---")
    st.sidebar.caption("**Live data** · auto-collected on startup")
    meta = get_live_meta()
    st.sidebar.caption(
        f"Last Updated: **{format_last_updated(meta.get('last_updated'))}**"
    )
    st.sidebar.caption(
        f"Play: {meta.get('playstore_count', 0)} · "
        f"App Store: {meta.get('appstore_count', 0)} · "
        f"Merged: {meta.get('merged_count', 0)}"
    )
    st.sidebar.caption(
        f"Sources: Google Play (`{PLAYSTORE_APP_ID}`)"
        + (", Apple App Store" if has_appstore() else "")
    )
