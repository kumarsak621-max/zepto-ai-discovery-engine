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


def clear_data_caches() -> None:
    """Invalidate dashboard caches after fetch / analysis."""
    try:
        cached_collection_stats.clear()
        cached_vector_stats.clear()
        cached_pm_insights.clear()
        cached_reviews.clear()
    except Exception:
        try:
            st.cache_data.clear()
        except Exception:
            pass
