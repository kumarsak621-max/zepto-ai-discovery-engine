"""
Single source of truth for Historical / Live / Combined review filtering.

ALWAYS filters on review_date (DB column `date`), never fetched_at / created_at.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from src.config import (
    HISTORICAL_END_DATE,
    HISTORICAL_START_DATE,
    LIVE_START_DATE,
)

HISTORICAL_EMPTY_MSG = (
    "No historical reviews are currently stored for this date range."
)


def _to_review_timestamp(series: pd.Series) -> pd.Series:
    """Convert review_date values to UTC timestamps (NaT if unparseable)."""
    # format='mixed' / ISO8601 required: warehouse has both 'YYYY-MM-DD' and full ISO tz strings.
    # A single inferred format drops date-only rows as NaT (which incorrectly emptied Historical).
    try:
        return pd.to_datetime(series, utc=True, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        try:
            return pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601")
        except (TypeError, ValueError):
            # Last resort: parse row-by-row via calendar helper
            from src.review_dates import parse_review_date

            dates = [parse_review_date(v) for v in series.tolist()]
            return pd.to_datetime(dates, utc=True, errors="coerce")


def reviews_list_to_frame(reviews: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize a list of review dicts into a dataframe with review_date."""
    if not reviews:
        return pd.DataFrame(
            columns=["date", "review_date", "source", "rating", "text", "sentiment"]
        )
    df = pd.DataFrame(reviews).copy()
    # Canonical review_date from store review timestamp ONLY (never fetched_at)
    if "date" in df.columns:
        raw = df["date"]
    else:
        raw = pd.Series([None] * len(df))
    # Do not prefer a separate review_date column when it is empty/NaN-heavy —
    # always anchor on DB `date` first.
    df["review_date"] = _to_review_timestamp(raw)
    return df


def apply_source_date_filter(
    reviews: list[dict[str, Any]] | pd.DataFrame,
    data_source: str = "combined",
) -> pd.DataFrame:
    """
    Filter reviews by Review Source using review_date only.

    Historical: 2026-04-01 <= review_date.date <= 2026-07-05
    Live:       review_date.date >= 2026-07-06  (open-ended)
    Combined:   Historical ∪ Live
    """
    if isinstance(reviews, pd.DataFrame):
        df = reviews.copy()
        if "review_date" not in df.columns:
            raw = df["date"] if "date" in df.columns else pd.Series([pd.NaT] * len(df))
            df["review_date"] = _to_review_timestamp(raw)
        else:
            df["review_date"] = _to_review_timestamp(df["review_date"])
    else:
        df = reviews_list_to_frame(list(reviews or []))

    if df.empty:
        return df

    # Calendar-date comparison (inclusive bounds) — avoids midnight Timestamp pitfalls
    cal = df["review_date"].dt.tz_convert("UTC").dt.date

    hist_mask = (cal >= HISTORICAL_START_DATE) & (cal <= HISTORICAL_END_DATE)
    live_mask = cal >= LIVE_START_DATE

    mode = str(data_source or "combined").lower()
    if mode == "historical":
        mask = hist_mask
    elif mode == "live":
        mask = live_mask
    else:
        mask = hist_mask | live_mask

    # Drop rows with unparseable review_date (do NOT fall back to fetched_at)
    mask = mask & df["review_date"].notna()
    out = df.loc[mask].copy()

    # Flags for UI / Source column
    out_cal = out["review_date"].dt.tz_convert("UTC").dt.date
    out["is_historical"] = (out_cal >= HISTORICAL_START_DATE) & (
        out_cal <= HISTORICAL_END_DATE
    )
    out["is_live"] = out_cal >= LIVE_START_DATE
    return out


def apply_ui_date_range_filter(
    df: pd.DataFrame,
    date_range: str = "all",
) -> pd.DataFrame:
    """
    Optional UI rolling window — still uses review_date only (never fetched_at).
    Applied AFTER source split.
    """
    if df.empty or not date_range or str(date_range).lower() in {"all", "all time"}:
        return df
    days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(str(date_range).lower())
    if days is None:
        return df
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    return df.loc[df["review_date"].notna() & (df["review_date"] >= cutoff)].copy()


def dataframe_to_review_dicts(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert filtered dataframe back to list[dict] for existing pipelines."""
    if df is None or df.empty:
        return []
    records = df.to_dict(orient="records")
    out: list[dict[str, Any]] = []
    for row in records:
        # Normalize NaT / NaN for downstream JSON / SQLite-friendly code
        cleaned: dict[str, Any] = {}
        for k, v in row.items():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                cleaned[k] = None
            elif isinstance(v, pd.Timestamp):
                if pd.isna(v):
                    cleaned[k] = None
                else:
                    cleaned[k] = v.isoformat()
            else:
                try:
                    if pd.isna(v):
                        cleaned[k] = None
                    else:
                        cleaned[k] = v
                except (TypeError, ValueError):
                    cleaned[k] = v
        # Keep canonical aliases
        if cleaned.get("date") and not cleaned.get("review_date"):
            cleaned["review_date"] = cleaned["date"]
        elif cleaned.get("review_date") and isinstance(cleaned["review_date"], str):
            pass
        out.append(cleaned)
    return out


def filter_reviews(
    reviews: list[dict[str, Any]],
    *,
    data_source: str = "combined",
    date_range: str = "all",
    platforms: list[str] | None = None,
    ratings: list[int] | None = None,
    sentiments: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Full filter pipeline used by Dashboard, Insights, charts, and AI."""
    df = apply_source_date_filter(reviews, data_source=data_source)
    df = apply_ui_date_range_filter(df, date_range=date_range)

    if platforms:
        platform_set = {str(p).lower() for p in platforms if p}
        if platform_set and "source" in df.columns:
            df = df[df["source"].astype(str).str.lower().isin(platform_set)]

    if ratings and "rating" in df.columns:
        rating_set = set()
        for r in ratings:
            try:
                rating_set.add(int(float(r)))
            except (TypeError, ValueError):
                continue
        if rating_set:
            stars = pd.to_numeric(df["rating"], errors="coerce").round().astype("Int64")
            df = df[stars.isin(list(rating_set))]

    if sentiments and "sentiment" in df.columns:
        sentiment_set = {str(s).strip().title() for s in sentiments if s}
        if sentiment_set:
            df = df[df["sentiment"].astype(str).str.strip().str.title().isin(sentiment_set)]

    # Newest first
    if "review_date" in df.columns and not df.empty:
        df = df.sort_values("review_date", ascending=False, na_position="last")

    if limit is not None:
        df = df.head(int(limit))

    return dataframe_to_review_dicts(df)


def historical_count(reviews: list[dict[str, Any]]) -> int:
    return len(apply_source_date_filter(reviews, data_source="historical"))
