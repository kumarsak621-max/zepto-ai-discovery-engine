"""
Review viewing helpers — display table, keyword search, and CSV/Excel export.

Display-only: at most MAX_DISPLAY_REVIEWS_PER_DAY rows per calendar date.
Storage / AI / dashboard always keep the full review set.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pandas as pd

# Visible table only — never applied to DB storage or AI/dashboard payloads
MAX_DISPLAY_REVIEWS_PER_DAY = 5


def _platform_label(source: Any) -> str:
    key = str(source or "").strip().lower()
    if key in {"playstore", "google play", "google_play", "play"}:
        return "Google Play"
    if key in {"appstore", "apple app store", "app_store", "ios", "apple"}:
        return "Apple App Store"
    return str(source or "Unknown").replace("_", " ").title()


def _format_date(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    raw = str(value).strip()
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d %b %Y")
    except ValueError:
        return raw[:16]


def _review_sort_key(row: dict[str, Any]) -> tuple:
    """Newest first within a day (ISO timestamp descending)."""
    raw = str(row.get("date") or row.get("review_date") or "")
    return (raw,)


def limit_reviews_for_display(
    reviews: list[dict[str, Any]],
    *,
    max_per_day: int = MAX_DISPLAY_REVIEWS_PER_DAY,
) -> list[dict[str, Any]]:
    """
    Cap visible rows at `max_per_day` per calendar date.

    Does not mutate or delete the input list — returns a new list for UI only.
    """
    if not reviews or max_per_day <= 0:
        return list(reviews or [])

    from src.review_dates import parse_review_date

    # Newest dates first overall; within a day keep first N after newest-first sort
    ordered = sorted(reviews, key=_review_sort_key, reverse=True)
    per_day: dict[Any, int] = {}
    out: list[dict[str, Any]] = []
    for row in ordered:
        cal = parse_review_date(row.get("date") or row.get("review_date"))
        key = cal.isoformat() if cal is not None else "__unknown__"
        used = per_day.get(key, 0)
        if used >= max_per_day:
            continue
        per_day[key] = used + 1
        out.append(row)
    return out


def reviews_to_display_df(
    reviews: list[dict[str, Any]],
    *,
    data_source: str = "all",
    max_per_day: int | None = MAX_DISPLAY_REVIEWS_PER_DAY,
) -> pd.DataFrame:
    """Build the interactive Visible Reviews table (display-capped per day)."""
    _ = data_source  # kept for call-site compatibility
    cols = [
        "Review Date",
        "Platform",
        "Rating",
        "Review Text",
        "Sentiment",
        "Reviewer Name",
    ]
    if not reviews:
        return pd.DataFrame(columns=cols)

    display_rows = (
        limit_reviews_for_display(reviews, max_per_day=max_per_day)
        if max_per_day is not None
        else list(reviews)
    )

    rows = []
    for r in display_rows:
        text = r.get("text") or r.get("review_text") or ""
        name = (
            r.get("reviewer_name")
            or r.get("userName")
            or r.get("user_name")
            or ""
        )
        rows.append(
            {
                "Review Date": _format_date(r.get("date") or r.get("review_date")),
                "Platform": _platform_label(r.get("source")),
                "Rating": r.get("rating"),
                "Review Text": str(text),
                "Sentiment": (r.get("sentiment") or "—"),
                "Reviewer Name": str(name).strip() or "—",
            }
        )
    return pd.DataFrame(rows)


def filter_by_keyword(
    reviews: list[dict[str, Any]],
    keyword: str | None,
) -> list[dict[str, Any]]:
    """Instant case-insensitive search over review text."""
    q = (keyword or "").strip().lower()
    if not q:
        return reviews
    out: list[dict[str, Any]] = []
    for r in reviews:
        text = str(r.get("text") or r.get("review_text") or "").lower()
        name = str(r.get("reviewer_name") or r.get("title") or "").lower()
        if q in text or q in name:
            out.append(r)
    return out


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reviews")
    return buffer.getvalue()
