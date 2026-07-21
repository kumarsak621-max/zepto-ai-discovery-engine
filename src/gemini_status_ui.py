"""Streamlit UI for user-facing Gemini / AI availability messages only."""

from __future__ import annotations

import streamlit as st

_AI_UNAVAILABLE_MSG = (
    "AI insights are temporarily unavailable. "
    "The dashboard is displaying the most recent successfully analyzed insights. "
    "Please try again later."
)


def render_gemini_api_status(*, expanded: bool = False) -> None:
    """No-op — developer Gemini status UI removed from production."""
    _ = expanded


def render_gemini_key_caption() -> None:
    """No-op — active key / model captions removed from production UI."""
    return


def render_ai_debug_expander(
    exc: BaseException | None = None,
    *,
    discovery: dict | None = None,
    expanded: bool = False,
) -> None:
    """No-op — Debug Information expander removed from production UI."""
    _ = (exc, discovery, expanded)


def render_gemini_all_keys_failed_warning(
    exc: BaseException | None = None,
    *,
    discovery: dict | None = None,
) -> None:
    """User-facing warning only — no internal diagnostics."""
    _ = (exc, discovery)
    st.warning(_AI_UNAVAILABLE_MSG)
