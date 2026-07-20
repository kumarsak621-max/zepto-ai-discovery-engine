"""
Shared Gemini / AI analysis debug state.

Records the last failure so Streamlit can show a Debug Information expander
while still using cached / evidence fallbacks.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_LAST_EVENT: dict[str, Any] = {
    "ok": True,
    "stage": "",
    "message": "",
    "exception_type": "",
    "exception_message": "",
    "traceback": "",
    "active_key_label": "",
    "model_name": "",
    "attempt": 0,
    "failovers": 0,
    "timestamp": "",
}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _safe_key_label() -> str:
    try:
        from src.gemini_key_manager import gemini_active_label

        return gemini_active_label()
    except Exception:
        return "unknown"


def _safe_model() -> str:
    try:
        from src.config import get_gemini_model
        from src.gemini_key_manager import gemini_status

        return str(gemini_status().get("model_name") or get_gemini_model() or "")
    except Exception:
        try:
            from src.config import get_gemini_model

            return get_gemini_model()
        except Exception:
            return "unknown"


def record_ai_success(*, stage: str = "gemini") -> None:
    with _LOCK:
        _LAST_EVENT.update(
            {
                "ok": True,
                "stage": stage,
                "message": "AI request succeeded",
                "exception_type": "",
                "exception_message": "",
                "traceback": "",
                "active_key_label": _safe_key_label(),
                "model_name": _safe_model(),
                "timestamp": _now(),
            }
        )


def record_ai_failure(
    exc: BaseException,
    *,
    stage: str,
    attempt: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Log + store failure details (never includes full API keys)."""
    tb = traceback.format_exc()
    msg = str(exc)
    payload: dict[str, Any] = {
        "ok": False,
        "stage": stage,
        "message": f"{stage} failed: {msg}",
        "exception_type": type(exc).__name__,
        "exception_message": msg,
        "traceback": tb,
        "active_key_label": _safe_key_label(),
        "model_name": _safe_model(),
        "attempt": int(attempt or 0),
        "timestamp": _now(),
    }
    if extra:
        payload.update(extra)

    try:
        from src.gemini_key_manager import gemini_status

        st = gemini_status()
        payload["failovers"] = int(st.get("failovers") or 0)
        payload["failed_requests"] = int(st.get("failed_requests") or 0)
        payload["successful_requests"] = int(st.get("successful_requests") or 0)
        payload["last_error_from_manager"] = st.get("last_error") or ""
        if st.get("model_name"):
            payload["model_name"] = st.get("model_name")
        if st.get("active_key_display"):
            payload["active_key_label"] = (
                f"{payload['active_key_label']} ({st.get('active_key_display')})"
            )
    except Exception:
        logger.exception("Could not enrich AI failure debug payload")

    with _LOCK:
        _LAST_EVENT.clear()
        _LAST_EVENT.update(payload)

    # Always print + log (Streamlit often hides logger ERROR unless configured)
    print(
        f"[AI DEBUG] stage={stage} type={type(exc).__name__} "
        f"key={payload.get('active_key_label')} model={payload.get('model_name')}\n"
        f"{msg}\n{tb}",
        flush=True,
    )
    logger.error(
        "AI failure stage=%s type=%s key=%s model=%s attempt=%s msg=%s\n%s",
        stage,
        type(exc).__name__,
        payload.get("active_key_label"),
        payload.get("model_name"),
        payload.get("attempt"),
        msg,
        tb,
    )
    return dict(payload)


def get_ai_debug_snapshot() -> dict[str, Any]:
    with _LOCK:
        return dict(_LAST_EVENT)


def format_debug_text(snapshot: dict[str, Any] | None = None) -> str:
    snap = snapshot or get_ai_debug_snapshot()
    lines = [
        f"OK: {snap.get('ok')}",
        f"Stage: {snap.get('stage') or '—'}",
        f"Timestamp: {snap.get('timestamp') or '—'}",
        f"Active Gemini key: {snap.get('active_key_label') or '—'}",
        f"Model name: {snap.get('model_name') or '—'}",
        f"Attempt: {snap.get('attempt') or 0}",
        f"Failovers: {snap.get('failovers') or 0}",
        f"Exception type: {snap.get('exception_type') or '—'}",
        f"Exception message: {snap.get('exception_message') or snap.get('message') or '—'}",
    ]
    if snap.get("last_error_from_manager"):
        lines.append(f"Key manager last_error: {snap.get('last_error_from_manager')}")
    tb = snap.get("traceback") or ""
    if tb and tb.strip() and tb.strip() != "NoneType: None":
        lines.append("")
        lines.append("Traceback:")
        lines.append(tb)
    return "\n".join(lines)
