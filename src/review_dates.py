"""
Fixed calendar date boundaries for Historical vs Live review separation.

Historical: 01 Apr 2026 → 05 Jul 2026 (inclusive)
Live:       06 Jul 2026 → latest available (no end date)
Combined:   Historical ∪ Live (deduped at ingest / by content_hash)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.config import (
    HISTORICAL_END_DATE,
    HISTORICAL_START_DATE,
    LIVE_START_DATE,
)


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
    # Prefer full ISO first
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date()
    except ValueError:
        pass
    # YYYY-MM-DD prefix
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def is_historical_date(d: date | None) -> bool:
    if d is None:
        return False
    return HISTORICAL_START_DATE <= d <= HISTORICAL_END_DATE


def is_live_date(d: date | None) -> bool:
    """Live = 06 Jul 2026 onwards (open-ended forever)."""
    if d is None:
        return False
    return d >= LIVE_START_DATE


def is_combined_date(d: date | None) -> bool:
    return is_historical_date(d) or is_live_date(d)


def classify_review_date(d: date | None) -> str:
    if is_live_date(d):
        return "Live"
    if is_historical_date(d):
        return "Historical"
    return "Other"


def historical_range_label() -> str:
    return (
        f"{HISTORICAL_START_DATE.strftime('%d %b %Y')} to "
        f"{HISTORICAL_END_DATE.strftime('%d %b %Y')}"
    )


def live_range_label(latest: date | None = None) -> str:
    end = latest.strftime("%d %b %Y") if latest else "Latest Available Review"
    return f"{LIVE_START_DATE.strftime('%d %b %Y')} to {end}"
