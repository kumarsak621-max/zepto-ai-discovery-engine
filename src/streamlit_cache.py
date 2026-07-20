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


@st.cache_data(ttl=120, show_spinner=True)
def cached_filtered_dashboard(
    data_source: str = "all",
    date_range: str = "all",
    platform: str = "both",
    ratings_key: str = "",
    sentiments_key: str = "",
    limit: int = 2000,
) -> dict[str, Any]:
    from src.review_analytics import build_filtered_dashboard

    ratings = [int(x) for x in ratings_key.split(",") if x.strip().isdigit()] if ratings_key else None
    sentiments = [s for s in sentiments_key.split("|") if s.strip()] if sentiments_key else None
    return build_filtered_dashboard(
        data_source=data_source,
        date_range=date_range,
        platform=platform,
        ratings=ratings,
        sentiments=sentiments,
        limit=limit,
    )


@st.cache_data(ttl=60, show_spinner=False)
def cached_warehouse_stats() -> dict[str, Any]:
    from src.config import LIVE_REVIEW_WINDOW_DAYS
    from src.database import get_review_warehouse_stats

    return get_review_warehouse_stats(live_window_days=LIVE_REVIEW_WINDOW_DAYS)


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
        cached_filtered_dashboard.clear()
        cached_warehouse_stats.clear()
    except Exception:
        try:
            st.cache_data.clear()
        except Exception:
            pass
