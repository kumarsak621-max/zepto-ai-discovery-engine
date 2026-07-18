"""Streamlit UI for Gemini multi-key health status."""

from __future__ import annotations

import streamlit as st


def render_gemini_api_status(*, expanded: bool = False) -> None:
    """Admin section: Gemini API Status (never shows full keys)."""
    try:
        from src.gemini_key_manager import gemini_active_label, gemini_status
    except Exception as exc:
        st.warning(f"Gemini key manager unavailable: {exc}")
        return

    status = gemini_status()
    label = gemini_active_label()

    with st.expander("Gemini API Status", expanded=expanded):
        st.caption(label)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Keys", status.get("total_keys", 0))
        c2.metric("Active Key", status.get("active_key_display", "—"))
        c3.metric("Failovers", f"{int(status.get('failovers') or 0):,}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Successful Requests", f"{int(status.get('successful_requests') or 0):,}")
        c5.metric("Failed Requests", f"{int(status.get('failed_requests') or 0):,}")
        c6.metric("Last Success", str(status.get("last_success_at") or "—"))

        st.markdown("**Last Error**")
        err = str(status.get("last_error") or "—")
        if err and err != "—":
            st.code(err[:500], language=None)
        else:
            st.caption("No recent Gemini errors.")

        st.caption(
            "Keys are loaded from `GEMINI_API_KEY` and `GEMINI_API_KEY_1`…`GEMINI_API_KEY_10`. "
            "Full key values are never displayed."
        )


def render_gemini_key_caption() -> None:
    """Compact caption for sidebars / headers."""
    try:
        from src.config import has_gemini
        from src.gemini_key_manager import gemini_active_label

        if has_gemini():
            st.caption(gemini_active_label())
    except Exception:
        pass
