"""Streamlit cache helpers to avoid repeated DB reads / API work."""

from __future__ import annotations

from typing import Any

import streamlit as st


@st.cache_data(ttl=60, show_spinner=False)
def cached_collection_stats() -> dict[str, Any]:
    from src.database import get_collection_stats

    return get_collection_stats()


@st.cache_data(ttl=60, show_spinner=False)
def cached_vector_stats() -> dict[str, Any]:
    from src.rag_pipeline import collection_stats

    return collection_stats()


@st.cache_data(ttl=60, show_spinner=False)
def cached_pm_insights(limit: int = 2000) -> dict[str, Any]:
    from src.database import get_pm_insights

    return get_pm_insights(limit=limit)


@st.cache_data(ttl=60, show_spinner=False)
def cached_reviews(limit: int = 2000) -> list[dict[str, Any]]:
    from src.database import fetch_all_reviews

    return fetch_all_reviews(limit=limit)


@st.cache_data(ttl=900, show_spinner=True)
def cached_discovery_dashboard(limit: int = 2000) -> dict[str, Any]:
    from src.discovery_insights import build_discovery_dashboard

    return build_discovery_dashboard(limit=limit)


def clear_data_caches() -> None:
    """Invalidate dashboard caches after fetch / analysis."""
    try:
        from src.discovery_insights import clear_discovery_disk_cache

        clear_discovery_disk_cache()
    except Exception:
        pass
    try:
        cached_collection_stats.clear()
        cached_vector_stats.clear()
        cached_pm_insights.clear()
        cached_reviews.clear()
        cached_discovery_dashboard.clear()
    except Exception:
        try:
            st.cache_data.clear()
        except Exception:
            pass
