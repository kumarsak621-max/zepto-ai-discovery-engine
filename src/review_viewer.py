"""
Review viewing helpers — display table, keyword search, and CSV/Excel export.

Additive only: does not change collection, Gemini, or warehouse logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pandas as pd


def _platform_label(source: Any) -> str:
    key = str(source or "").strip().lower()
    if key in {"playstore", "google play", "google_play", "play"}:
        return "Google Play"
    if key in {"appstore", "apple app store", "app_store", "ios", "apple"}:
        return "Apple App Store"
    return str(source or "Unknown").replace("_", " ").title()


def _review_source_label(row: dict[str, Any], *, data_source: str) -> str:
    """Label each row as Historical / Live / Merged based on mode + is_live flag."""
    mode = str(data_source or "combined").lower()
    if mode == "historical":
        return "Historical"
    if mode == "live":
        return "Live"
    # combined / merged
    if row.get("is_live"):
        return "Live"
    return "Historical"


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


def reviews_to_display_df(
    reviews: list[dict[str, Any]],
    *,
    data_source: str = "combined",
) -> pd.DataFrame:
    """Build the interactive Visible Reviews table."""
    if not reviews:
        return pd.DataFrame(
            columns=[
                "Review Date",
                "Platform",
                "Rating",
                "Review Text",
                "Sentiment",
                "Source",
                "Reviewer Name",
            ]
        )

    rows = []
    for r in reviews:
        text = r.get("text") or r.get("review_text") or ""
        name = (
            r.get("reviewer_name")
            or r.get("title")
            or r.get("userName")
            or ""
        )
        rows.append(
            {
                "Review Date": _format_date(r.get("date") or r.get("review_date")),
                "Platform": _platform_label(r.get("source")),
                "Rating": r.get("rating"),
                "Review Text": str(text),
                "Sentiment": (r.get("sentiment") or "—"),
                "Source": _review_source_label(r, data_source=data_source),
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
    # openpyxl is already in requirements.txt
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Reviews")
    return buffer.getvalue()
