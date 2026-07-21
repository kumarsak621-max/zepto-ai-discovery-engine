"""
Internal AI failure tracking for server logs only.

Not used by Streamlit UI — production never renders these details.
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
    "timestamp": "",
}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


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
    """Log failure details for operators (never rendered in Streamlit)."""
    tb = traceback.format_exc()
    msg = str(exc)
    payload: dict[str, Any] = {
        "ok": False,
        "stage": stage,
        "message": f"{stage} failed: {msg}",
        "exception_type": type(exc).__name__,
        "exception_message": msg,
        "traceback": tb,
        "attempt": int(attempt or 0),
        "timestamp": _now(),
    }
    if extra:
        payload.update(extra)

    with _LOCK:
        _LAST_EVENT.clear()
        _LAST_EVENT.update(payload)

    logger.error(
        "AI failure stage=%s type=%s attempt=%s msg=%s",
        stage,
        type(exc).__name__,
        payload.get("attempt"),
        msg,
        exc_info=True,
    )
    return dict(payload)


def get_ai_debug_snapshot() -> dict[str, Any]:
    with _LOCK:
        return dict(_LAST_EVENT)
