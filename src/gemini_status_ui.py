"""Streamlit UI — user-facing AI availability warning only."""

from __future__ import annotations

import streamlit as st

_AI_UNAVAILABLE_MSG = (
    "AI analysis is temporarily unavailable. "
    "The dashboard is displaying the most recent successfully analyzed insights. "
    "Please try again later."
)


def render_gemini_all_keys_failed_warning(
    exc: BaseException | None = None,
    *,
    discovery: dict | None = None,
) -> None:
    """Show the production AI-unavailable warning. No diagnostics."""
    _ = (exc, discovery)
    st.warning(_AI_UNAVAILABLE_MSG)
