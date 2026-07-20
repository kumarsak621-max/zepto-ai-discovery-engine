"""
Automatic review sync: startup + periodic refresh (default every 30 minutes).

Inserts only NEW reviews into the historical SQLite warehouse (never deletes).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import AUTO_REFRESH_MINUTES, SYNC_META_PATH
from src.paths import ensure_runtime_dirs

logger = logging.getLogger(__name__)

_SESSION_LAST_SYNC = "_review_sync_last_utc"
_SESSION_NEXT_SYNC = "_review_sync_next_utc"
_SESSION_SYNC_RESULT = "_review_sync_result"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def load_sync_meta() -> dict[str, Any]:
    if not SYNC_META_PATH.exists():
        return {}
    try:
        return json.loads(SYNC_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sync_meta(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_runtime_dirs()
    meta = {**load_sync_meta(), **payload}
    SYNC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def next_refresh_at(last_sync: datetime | None = None) -> datetime:
    base = last_sync or _now()
    minutes = max(1, int(AUTO_REFRESH_MINUTES or 30))
    return base + timedelta(minutes=minutes)


def should_auto_refresh(*, force: bool = False) -> bool:
    if force:
        return True
    meta = load_sync_meta()
    last = _parse_iso(meta.get("last_sync_at"))
    if last is None:
        return True
    return _now() >= next_refresh_at(last)


def sync_reviews(*, force: bool = False) -> dict[str, Any]:
    """
    Fetch latest Play + App Store reviews and insert only new rows.

    Safe to call repeatedly — duplicates are skipped via content_hash.
    """
    from src.data_pipeline import run_live_review_analysis
    from src.streamlit_cache import clear_data_caches

    if not force and not should_auto_refresh(force=False):
        meta = load_sync_meta()
        return {
            "status": "skipped",
            "reason": "within_refresh_window",
            "last_sync_at": meta.get("last_sync_at"),
            "next_refresh_at": meta.get("next_refresh_at"),
            "new_reviews": 0,
        }

    result = run_live_review_analysis(force_refresh=force or should_auto_refresh())
    now = _now()
    nxt = next_refresh_at(now)
    meta = save_sync_meta(
        {
            "last_sync_at": now.isoformat(),
            "next_refresh_at": nxt.isoformat(),
            "last_status": result.get("status"),
            "new_reviews": int(result.get("new_reviews") or 0),
            "merged_count": int(result.get("merged_count") or 0),
            "playstore_count": int(result.get("playstore_count") or 0),
            "appstore_count": int(result.get("appstore_count") or 0),
            "error": result.get("error"),
        }
    )
    if result.get("status") == "success":
        try:
            clear_data_caches()
        except Exception:
            pass
    return {**result, "sync_meta": meta}


def ensure_reviews_synced(*, force: bool = False) -> dict[str, Any]:
    """
    Streamlit-friendly sync: once on startup, then every AUTO_REFRESH_MINUTES.

    Uses session_state when Streamlit is available; falls back to disk meta.
    """
    try:
        import streamlit as st

        has_st = True
    except Exception:
        st = None  # type: ignore
        has_st = False

    now = _now()
    if has_st:
        last = _parse_iso(st.session_state.get(_SESSION_LAST_SYNC))
        due = force or last is None or now >= next_refresh_at(last)
        if not due:
            return st.session_state.get(_SESSION_SYNC_RESULT) or {
                "status": "skipped",
                "last_sync_at": st.session_state.get(_SESSION_LAST_SYNC),
                "next_refresh_at": st.session_state.get(_SESSION_NEXT_SYNC),
            }
        result = sync_reviews(force=force)
        st.session_state[_SESSION_LAST_SYNC] = now.isoformat()
        st.session_state[_SESSION_NEXT_SYNC] = next_refresh_at(now).isoformat()
        st.session_state[_SESSION_SYNC_RESULT] = result
        return result

    return sync_reviews(force=force)


def get_refresh_status() -> dict[str, Any]:
    """UI helper: last updated + next refresh timestamps."""
    try:
        import streamlit as st

        last = st.session_state.get(_SESSION_LAST_SYNC)
        nxt = st.session_state.get(_SESSION_NEXT_SYNC)
    except Exception:
        last = nxt = None

    meta = load_sync_meta()
    last = last or meta.get("last_sync_at")
    nxt = nxt or meta.get("next_refresh_at")
    if last and not nxt:
        parsed = _parse_iso(last)
        nxt = next_refresh_at(parsed).isoformat() if parsed else None

    # Relative "Updated X min ago"
    relative = "—"
    parsed_last = _parse_iso(last)
    if parsed_last:
        mins = int((_now() - parsed_last).total_seconds() // 60)
        if mins <= 0:
            relative = "Updated just now"
        elif mins == 1:
            relative = "Updated 1 min ago"
        else:
            relative = f"Updated {mins} min ago"

    return {
        "last_sync_at": last,
        "next_refresh_at": nxt,
        "relative": relative,
        "auto_refresh_minutes": AUTO_REFRESH_MINUTES,
        "new_reviews": meta.get("new_reviews"),
        "last_status": meta.get("last_status"),
    }
