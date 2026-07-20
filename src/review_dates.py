"""
Live review date helpers.

Live Reviews: 06 Jul 2026 → latest available (open-ended).
All Reviews: full warehouse (no historical-only slice).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.config import LIVE_START_DATE


def parse_review_date(value: Any) -> date | None:
    """Extract a calendar date (UTC) from a review timestamp/string."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    except ValueError:
        pass
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def is_live_date(d: date | None) -> bool:
    """Live = 06 Jul 2026 onwards (open-ended forever)."""
    if d is None:
        return False
    return d >= LIVE_START_DATE


def classify_review_date(d: date | None) -> str:
    if is_live_date(d):
        return "Live"
    if d is not None:
        return "Stored"
    return "Other"


def live_range_label(latest: date | None = None) -> str:
    end = latest.strftime("%d %b %Y") if latest else "Latest Available Review"
    return f"{LIVE_START_DATE.strftime('%d %b %Y')} to {end}"


# Backward-compatible aliases (historical feature removed)
def is_historical_date(d: date | None) -> bool:
    return False


def is_combined_date(d: date | None) -> bool:
    return d is not None


def historical_range_label() -> str:
    return "Removed — use All Reviews"
