"""Shared Streamlit helpers for timestamps, progress bars, and sidebar status."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.data_pipeline import get_live_meta


def format_last_updated(ts: str | None = None) -> str:
    value = ts
    if not value:
        meta = get_live_meta()
        value = meta.get("last_updated")
    if not value:
        return "Never"
    return str(value).replace("T", " ")[:19] + " UTC"


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
