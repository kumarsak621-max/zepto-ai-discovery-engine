"""
Single source of truth for Live / All review filtering.

ALWAYS filters on review_date (DB column `date`), never fetched_at / created_at.

- live → review_date >= LIVE_START_DATE (06 Jul 2026 onward, open-ended)
- all  → every review with a parseable review_date (full warehouse)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.config import LIVE_START_DATE


def _to_review_timestamp(series: pd.Series) -> pd.Series:
    """Convert review_date values to UTC timestamps (NaT if unparseable)."""
    try:
        return pd.to_datetime(series, utc=True, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        try:
            return pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601")
        except (TypeError, ValueError):
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
    if "date" in df.columns:
        raw = df["date"]
    else:
        raw = pd.Series([None] * len(df))
    df["review_date"] = _to_review_timestamp(raw)
    return df


def normalize_data_source(data_source: str | None) -> str:
    """Map legacy source names to live|all."""
    mode = str(data_source or "all").lower().strip()
    if mode in {"live"}:
        return "live"
    if mode in {"all", "combined", "historical", "merged"}:
        # historical removed — treat as full warehouse
        return "all"
    return "all"


def apply_source_date_filter(
    reviews: list[dict[str, Any]] | pd.DataFrame,
    data_source: str = "all",
) -> pd.DataFrame:
    """
    Filter reviews by Review Source using review_date only.

    Live: review_date.date >= 06 Jul 2026 (open-ended)
    All:  every row with a valid review_date
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

    cal = df["review_date"].dt.tz_convert("UTC").dt.date
    live_mask = cal >= LIVE_START_DATE
    mode = normalize_data_source(data_source)

    if mode == "live":
        mask = live_mask & df["review_date"].notna()
    else:
        # All Reviews — keep every parseable review_date (full merged warehouse)
        mask = df["review_date"].notna()

    out = df.loc[mask].copy()
    out_cal = out["review_date"].dt.tz_convert("UTC").dt.date
    out["is_live"] = out_cal >= LIVE_START_DATE
    out["is_historical"] = False  # feature removed
    return out


def apply_ui_date_range_filter(
    df: pd.DataFrame,
    date_range: str = "all",
) -> pd.DataFrame:
    """Optional UI rolling window — uses review_date only."""
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
        cleaned: dict[str, Any] = {}
        for k, v in row.items():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                cleaned[k] = None
            elif isinstance(v, pd.Timestamp):
                cleaned[k] = None if pd.isna(v) else v.isoformat()
            else:
                try:
                    cleaned[k] = None if pd.isna(v) else v
                except (TypeError, ValueError):
                    cleaned[k] = v
        if cleaned.get("date") and not cleaned.get("review_date"):
            cleaned["review_date"] = cleaned["date"]
        out.append(cleaned)
    return out


def filter_reviews(
    reviews: list[dict[str, Any]],
    *,
    data_source: str = "all",
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
            df = df[
                df["sentiment"].astype(str).str.strip().str.title().isin(sentiment_set)
            ]

    if "review_date" in df.columns and not df.empty:
        df = df.sort_values("review_date", ascending=False, na_position="last")

    if limit is not None:
        df = df.head(int(limit))

    return dataframe_to_review_dicts(df)
