"""Streamlit helpers for live review status (auto-collected on startup)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from src.data_pipeline import get_live_meta
from src.streamlit_playstore import format_last_updated


def show_source_metrics(meta_or_result: dict[str, Any] | None = None) -> None:
    """Display per-source counts + Last Updated (Play Store + App Store)."""
    data = meta_or_result or get_live_meta()
    playstore = int(data.get("playstore_count") or 0)
    appstore = int(data.get("appstore_count") or 0)
    merged = int(data.get("merged_count") or 0)

    c1, c2, c3 = st.columns(3)
    c1.metric("Google Play Reviews", f"{playstore:,}")
    c2.metric("Apple App Store Reviews", f"{appstore:,}")
    c3.metric("Merged Reviews", f"{merged:,}")

    stamp = format_last_updated(data.get("download_timestamp") or data.get("last_updated"))
    st.caption(f"Last Updated: **{stamp}**")


def render_sidebar_source_controls() -> None:
    """Sidebar: auto-collection status only (no upload / no manual run buttons)."""
    from src.auto_bootstrap import render_auto_status_sidebar

    render_auto_status_sidebar()
