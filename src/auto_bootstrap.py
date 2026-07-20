"""
Automatic review collection on Streamlit app startup.

Collects Google Play + App Store reviews via the existing pipeline,
merges/dedupes, stores in SQLite (append-only), and runs Gemini analysis.
Also re-checks for new reviews every AUTO_REFRESH_MINUTES (default 30).
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
    Ensure live reviews are collected and analyzed.

    - Runs on startup and again every AUTO_REFRESH_MINUTES.
    - Uses existing Play Store / App Store collectors + Gemini pipeline.
    - Inserts only NEW reviews into the historical warehouse (no deletes).
    - On failure: leaves prior SQLite data in place and sets a friendly warning.
    """
    from src.review_sync import ensure_reviews_synced, get_refresh_status, should_auto_refresh

    # Periodic refresh while the session is open
    needs_refresh = force or should_auto_refresh(force=False)
    if not force and st.session_state.get(_SESSION_DONE) and not needs_refresh:
        return st.session_state.get(_SESSION_RESULT) or {}

    result: dict[str, Any] = {"status": "skipped"}
    warning = ""

    try:
        from src.database import get_collection_stats

        with st.spinner(
            "Automatically collecting reviews from Google Play and App Store…"
        ):
            result = ensure_reviews_synced(force=force or needs_refresh)

        if result.get("status") == "success":
            clear_data_caches()
            warning = ""
        elif result.get("status") == "skipped":
            warning = ""
        else:
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
    # Expose refresh clocks for UI badges
    try:
        status = get_refresh_status()
        st.session_state["_refresh_status"] = status
    except Exception:
        pass
    return result


def render_auto_collect_warning() -> None:
    """Show the fallback warning if the last auto-collect failed."""
    warning = st.session_state.get(_SESSION_WARNING) or ""
    if warning:
        st.warning(warning)


def render_auto_status_sidebar() -> None:
    """Compact sidebar status (no upload / no manual run buttons)."""
    from src.config import AUTO_REFRESH_MINUTES, PLAYSTORE_APP_ID, has_appstore
    from src.data_pipeline import get_live_meta
    from src.review_sync import get_refresh_status
    from src.streamlit_playstore import format_last_updated

    st.sidebar.markdown("---")
    st.sidebar.caption("**Live data** · auto-collected on startup")
    meta = get_live_meta()
    refresh = get_refresh_status()
    st.sidebar.caption(
        f"Last Updated: **{format_last_updated(refresh.get('last_sync_at') or meta.get('last_updated'))}**"
    )
    st.sidebar.caption(
        f"Next Refresh: **{format_last_updated(refresh.get('next_refresh_at'))}** "
        f"(every {AUTO_REFRESH_MINUTES} min)"
    )
    st.sidebar.caption(refresh.get("relative") or "")
    st.sidebar.caption(
        f"Play: {meta.get('playstore_count', 0)} · "
        f"App Store: {meta.get('appstore_count', 0)} · "
        f"Merged: {meta.get('merged_count', 0)}"
    )
    st.sidebar.caption(
        f"Sources: Google Play (`{PLAYSTORE_APP_ID}`)"
        + (", Apple App Store" if has_appstore() else "")
    )
