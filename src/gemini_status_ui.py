"""Streamlit UI for Gemini multi-key health status + AI debug visibility."""

from __future__ import annotations

import streamlit as st


def render_gemini_api_status(*, expanded: bool = False) -> None:
    """Admin section: Gemini API Status (never shows full keys)."""
    try:
        from src.config import get_gemini_model
        from src.gemini_key_manager import gemini_active_label, gemini_status
    except Exception as exc:
        st.warning(f"Gemini key manager unavailable: {exc}")
        print(f"[AI DEBUG] gemini status UI failed: {exc}", flush=True)
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
    except Exception as exc:
        print(f"[AI DEBUG] gemini key caption failed: {exc}", flush=True)


def render_ai_debug_expander(
    exc: BaseException | None = None,
    *,
    discovery: dict | None = None,
    expanded: bool = False,
) -> None:
    """Always-available Debug Information panel for AI failures / fallbacks."""
    from src.gemini_debug import format_debug_text, get_ai_debug_snapshot, record_ai_failure

    snap = get_ai_debug_snapshot()
    if exc is not None and (not snap.get("exception_message") or snap.get("ok")):
        snap = record_ai_failure(exc, stage="ui-warning")

    # Prefer discovery-attached error when present
    if discovery:
        if discovery.get("error_message") and (
            not snap.get("exception_message") or snap.get("ok")
        ):
            snap = {
                **snap,
                "ok": False,
                "stage": discovery.get("source") or "discovery-fallback",
                "exception_message": discovery.get("error_message"),
                "exception_type": discovery.get("error_type") or "Exception",
                "traceback": discovery.get("error_traceback") or snap.get("traceback") or "",
                "message": discovery.get("error_message"),
            }

    with st.expander("Debug Information", expanded=expanded):
        st.caption(
            "Technical details for AI analysis failures. "
            "API keys are never shown in full."
        )
        try:
            from src.config import get_gemini_model, has_gemini
            from src.gemini_key_manager import gemini_active_label, gemini_status

            st.write(f"**Has Gemini keys:** `{has_gemini()}`")
            st.write(f"**Active key:** `{gemini_active_label()}`")
            st.write(f"**Configured model:** `{get_gemini_model()}`")
            status = gemini_status()
            st.write(f"**Manager model:** `{status.get('model_name')}`")
            st.write(f"**Failovers:** `{status.get('failovers')}`")
            st.write(f"**Successful requests:** `{status.get('successful_requests')}`")
            st.write(f"**Failed requests:** `{status.get('failed_requests')}`")
            if discovery:
                st.write(f"**Discovery source:** `{discovery.get('source')}`")
        except Exception as status_exc:
            st.write(f"Could not load Gemini status: `{status_exc}`")
            print(f"[AI DEBUG] status block failed: {status_exc}", flush=True)

        st.code(format_debug_text(snap), language="text")


def render_gemini_all_keys_failed_warning(
    exc: BaseException | None = None,
    *,
    discovery: dict | None = None,
) -> None:
    """
    Professional warning after Gemini failure — keeps cached insights visible,
    and always surfaces the real cause under Debug Information.
    """
    st.warning(
        "AI analysis is temporarily unavailable. "
        "The dashboard is displaying the most recent successfully analyzed insights. "
        "Please try again later."
    )
    render_ai_debug_expander(exc, discovery=discovery, expanded=True)
