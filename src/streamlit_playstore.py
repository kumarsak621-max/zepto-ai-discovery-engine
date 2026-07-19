"""Shared Streamlit helpers for timestamps, progress bars, and sidebar status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import streamlit as st

from src.data_pipeline import get_live_meta


def format_last_updated(ts: Any = None) -> str:
    """
    Format a last-updated timestamp for UI captions.

    Accepts datetime, ISO strings, Unix timestamps (int/float), or None.
    Returns "Unknown" when missing/invalid. Never raises.
    Example: 19 Jul 2026, 02:48 PM
    """
    try:
        value = ts
        # No argument / None → fall back to latest live-meta timestamp
        if value is None or value == "":
            try:
                value = (get_live_meta() or {}).get("last_updated")
            except Exception:
                value = None

        if value is None or value == "":
            return "Unknown"

        dt: datetime | None = None

        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            try:
                # Heuristic: ms vs seconds
                epoch = float(value)
                if epoch > 1e12:
                    epoch /= 1000.0
                dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                return "Unknown"
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return "Unknown"
            # Numeric string → treat as unix
            try:
                if text.replace(".", "", 1).isdigit():
                    epoch = float(text)
                    if epoch > 1e12:
                        epoch /= 1000.0
                    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                dt = None
            if dt is None:
                raw = text.replace("Z", "+00:00")
                try:
                    dt = datetime.fromisoformat(raw)
                except ValueError:
                    for fmt in (
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M",
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%d",
                    ):
                        try:
                            dt = datetime.strptime(text[:19].replace("T", " "), fmt)
                            break
                        except ValueError:
                            continue
        else:
            return "Unknown"

        if dt is None:
            return "Unknown"

        # Display in local-naive wall time if timezone-aware
        if dt.tzinfo is not None:
            try:
                dt = dt.astimezone()
            except Exception:
                dt = dt.replace(tzinfo=None)

        return dt.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return "Unknown"


def render_last_updated_caption(*, sidebar: bool = False) -> None:
    meta = get_live_meta()
    stamp = format_last_updated(meta.get("last_updated"))
    merged = meta.get("merged_count")
    text = (
        f"Last Updated: **{stamp}** · Merged reviews: {int(merged):,}"
        if merged
        else f"Last Updated: **{stamp}**"
    )
    (st.sidebar.caption if sidebar else st.caption)(text)


def _set_progress(progress_bar: Any, pct: float, msg: str, status: Any) -> None:
    clamped = min(max(float(pct), 0.0), 1.0)
    try:
        progress_bar.progress(clamped, text=msg)
    except TypeError:
        progress_bar.progress(clamped)
    status.caption(msg)


def render_sidebar_fetch_controls() -> None:
    """Sidebar live-data status (auto-collect runs via ensure_live_reviews_loaded)."""
    from src.auto_bootstrap import render_auto_status_sidebar

    render_auto_status_sidebar()
