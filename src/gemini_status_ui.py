"""Streamlit UI for Gemini multi-key health status."""

from __future__ import annotations

import streamlit as st


def render_gemini_api_status(*, expanded: bool = False) -> None:
    """Admin section: Gemini API Status (never shows full keys)."""
    try:
        from src.config import get_gemini_model
        from src.gemini_key_manager import gemini_active_label, gemini_status
    except Exception as exc:
        st.warning(f"Gemini key manager unavailable: {exc}")
        return

    status = gemini_status()
    label = gemini_active_label()
    model = status.get("model_name") or get_gemini_model() or "—"
    if model in {"-", ""}:
        model = get_gemini_model() or "—"

    with st.expander("Gemini API Status", expanded=expanded):
        st.caption(label)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Keys Loaded", status.get("total_keys", 0))
        c2.metric("Active Key", status.get("active_key_display", "—"))
        c3.metric("Failovers", f"{int(status.get('failovers') or 0):,}")

        c4, c5, c6 = st.columns(3)
        c4.metric("Successful Requests", f"{int(status.get('successful_requests') or 0):,}")
        c5.metric("Failed Requests", f"{int(status.get('failed_requests') or 0):,}")
        c6.metric("Current Gemini Model", str(model))

        st.markdown("**Last Error**")
        err = str(status.get("last_error") or "—")
        if err and err != "—":
            st.code(err[:500], language=None)
        else:
            st.caption("No recent Gemini errors.")

        last_ok = status.get("last_success_at") or "—"
        last_fo = status.get("last_failover_at") or "—"
        st.caption(f"Last success: {last_ok} · Last failover: {last_fo}")
        st.caption(
            "Keys are loaded from `GEMINI_API_KEY` and `GEMINI_API_KEY_1`…`GEMINI_API_KEY_10`. "
            "Full key values are never displayed."
        )


def render_gemini_key_caption() -> None:
    """Compact caption for sidebars / headers."""
    try:
        from src.config import get_gemini_model, has_gemini
        from src.gemini_key_manager import gemini_active_label

        if has_gemini():
            st.caption(f"{gemini_active_label()} · model `{get_gemini_model()}`")
    except Exception:
        pass


def render_gemini_all_keys_failed_warning(exc: BaseException | None = None) -> None:
    """Friendly, non-fatal warning when every Gemini key fails."""
    detail = ""
    if exc is not None:
        text = str(exc)
        if "All Gemini API keys failed" in text or "quota" in text.lower():
            detail = " All configured keys were tried with automatic failover."
    st.warning(
        "Gemini is temporarily unavailable. "
        "The app continues with evidence-based fallbacks so your workflow is not interrupted."
        f"{detail} "
        "Check quotas in Google AI Studio or rotate keys in Secrets / `.env`."
    )
