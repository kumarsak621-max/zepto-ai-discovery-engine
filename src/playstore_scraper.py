"""Google Play Store review collector for Zepto (com.zeptoconsumerapp)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.config import PLAYSTORE_APP_ID, PLAYSTORE_APP_NAME, PLAYSTORE_REVIEW_COUNT
from src.database import clean_text
from src.paths import DATA_DIR, ensure_runtime_dirs

logger = logging.getLogger(__name__)

REVIEWS_CSV_PATH = DATA_DIR / "reviews.csv"
REVIEWS_CACHE_META_PATH = DATA_DIR / "reviews_cache_meta.json"
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60  # 6 hours


ProgressCallback = Callable[[float, str], None]


def _score_to_sentiment(score: int | float | None) -> str | None:
    if score is None:
        return None
    if score >= 4:
        return "Positive"
    if score <= 2:
        return "Negative"
    return "Neutral"


def _normalize_review(item: dict[str, Any], category: str = "app_review") -> dict[str, Any] | None:
    text = clean_text(item.get("content") or "")
    if not text:
        return None

    at = item.get("at")
    if isinstance(at, datetime):
        date_str = at.astimezone(timezone.utc).isoformat()
    elif at:
        date_str = str(at)
    else:
        date_str = datetime.now(timezone.utc).isoformat()

    score = item.get("score")
    review_id = item.get("reviewId")
    return {
        "source": "playstore",
        "text": text,
        "rating": float(score) if score is not None else None,
        "date": date_str,
        "category": category,
        "sentiment": _score_to_sentiment(score),
        "theme": None,
        "user_intent": None,
        "app_version": item.get("reviewCreatedVersion") or item.get("appVersion"),
        "title": item.get("userName"),
        "upvotes": item.get("thumbsUpCount"),
        "external_id": review_id,
        # CSV-oriented aliases
        "review_id": review_id,
        "review_text": text,
        "helpful_votes": item.get("thumbsUpCount"),
    }


def fetch_app_metadata(
    app_id: str | None = None,
    lang: str = "en",
    country: str = "in",
) -> dict[str, Any]:
    """Fetch Zepto app listing metadata from Google Play."""
    app_id = app_id or PLAYSTORE_APP_ID
    try:
        from google_play_scraper import app as fetch_app
    except ImportError as exc:
        raise RuntimeError(
            "google-play-scraper is not installed. Run: pip install google-play-scraper"
        ) from exc

    info = fetch_app(app_id, lang=lang, country=country)
    return {
        "app_id": info.get("appId") or app_id,
        "title": info.get("title") or PLAYSTORE_APP_NAME,
        "score": info.get("score"),
        "ratings": info.get("ratings"),
        "reviews_count": info.get("reviews"),
        "installs": info.get("installs"),
        "version": info.get("version"),
        "updated": str(info.get("updated") or ""),
        "developer": info.get("developer"),
        "genre": info.get("genre"),
        "summary": clean_text(info.get("summary") or "")[:500],
        "url": info.get("url"),
    }


def get_reviews_cache_meta() -> dict[str, Any]:
    if not REVIEWS_CACHE_META_PATH.exists():
        return {}
    try:
        return json.loads(REVIEWS_CACHE_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_last_updated_timestamp() -> str | None:
    meta = get_reviews_cache_meta()
    return meta.get("last_updated") or None


def cache_is_fresh(ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> bool:
    meta = get_reviews_cache_meta()
    last = meta.get("last_updated")
    if not last or not REVIEWS_CSV_PATH.exists():
        return False
    try:
        ts = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age < ttl_seconds and int(meta.get("count") or 0) > 0
    except Exception:
        return False


def save_reviews_csv(reviews: list[dict[str, Any]], path: Path | None = None) -> Path:
    """Save deduped reviews to data/reviews.csv with required columns."""
    ensure_runtime_dirs()
    path = path or REVIEWS_CSV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    seen: set[str] = set()
    for r in reviews:
        rid = str(r.get("review_id") or r.get("external_id") or "")
        text = r.get("review_text") or r.get("text") or ""
        key = rid or text.strip().lower()[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "review_id": rid,
                "review_text": text,
                "rating": r.get("rating"),
                "date": r.get("date"),
                "helpful_votes": r.get("helpful_votes", r.get("upvotes")),
            }
        )

    df = pd.DataFrame(
        rows,
        columns=["review_id", "review_text", "rating", "date", "helpful_votes"],
    )
    df.to_csv(path, index=False, encoding="utf-8")

    meta = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "count": len(df),
        "app_id": PLAYSTORE_APP_ID,
        "path": str(path),
    }
    REVIEWS_CACHE_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    logger.info("Saved %s reviews to %s", len(df), path)
    return path


def load_reviews_from_csv(path: Path | None = None) -> list[dict[str, Any]]:
    """Load cached CSV into normalized review dicts for DB upsert."""
    path = path or REVIEWS_CSV_PATH
    if not path.exists():
        return []
    df = pd.read_csv(path)
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        text = clean_text(str(row.get("review_text") or ""))
        if len(text) < 15:
            continue
        rid = str(row.get("review_id") or "")
        rating = row.get("rating")
        try:
            rating_f = float(rating) if pd.notna(rating) else None
        except (TypeError, ValueError):
            rating_f = None
        helpful = row.get("helpful_votes")
        try:
            helpful_i = int(helpful) if pd.notna(helpful) else None
        except (TypeError, ValueError):
            helpful_i = None
        date_val = row.get("date")
        date_str = str(date_val) if pd.notna(date_val) else datetime.now(timezone.utc).isoformat()
        out.append(
            {
                "source": "playstore",
                "text": text,
                "rating": rating_f,
                "date": date_str,
                "category": "app_review",
                "sentiment": _score_to_sentiment(rating_f),
                "theme": None,
                "user_intent": None,
                "app_version": None,
                "title": None,
                "upvotes": helpful_i,
                "external_id": rid or None,
                "review_id": rid,
                "review_text": text,
                "helpful_votes": helpful_i,
            }
        )
    return out


def collect_playstore_reviews(
    app_id: str | None = None,
    count: int | None = None,
    lang: str = "en",
    country: str = "in",
    progress_callback: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """
    Collect newest English Google Play reviews for Zepto (com.zeptoconsumerapp).

    Fetches up to `count` reviews (default 500) with optional progress updates.
    """
    app_id = app_id or PLAYSTORE_APP_ID
    count = count or PLAYSTORE_REVIEW_COUNT

    try:
        from google_play_scraper import Sort, reviews
    except ImportError as exc:
        raise RuntimeError(
            "google-play-scraper is not installed. Run: pip install google-play-scraper"
        ) from exc

    logger.info(
        "Collecting Play Store reviews for %s (%s), count=%s lang=%s",
        PLAYSTORE_APP_NAME,
        app_id,
        count,
        lang,
    )

    if progress_callback:
        progress_callback(0.05, "Connecting to Google Play…")

    # google-play-scraper fetches in batches; pull in chunks for progress UX
    batch_size = min(200, max(50, count // 3 or 50))
    collected: dict[str, dict[str, Any]] = {}
    continuation_token = None
    fetched = 0

    try:
        while fetched < count:
            need = min(batch_size, count - fetched)
            if progress_callback:
                pct = min(0.85, 0.05 + 0.8 * (fetched / max(count, 1)))
                progress_callback(pct, f"Downloading reviews… {fetched}/{count}")

            result, continuation_token = reviews(
                app_id,
                lang=lang,
                country=country,
                sort=Sort.NEWEST,
                count=need,
                filter_score_with=None,
                continuation_token=continuation_token,
            )
            if not result:
                break

            for item in result:
                row = _normalize_review(item, category="app_review")
                if not row:
                    continue
                key = str(row.get("external_id") or row["text"][:80])
                collected[key] = row

            fetched = len(collected)
            if continuation_token is None:
                break
    except Exception as exc:
        logger.error("Play Store scrape failed: %s", exc)
        raise RuntimeError(
            f"Google Play is unavailable or blocked the request: {exc}"
        ) from exc

    if progress_callback:
        progress_callback(0.9, f"Downloaded {len(collected)} unique reviews")

    normalized = list(collected.values())
    logger.info("Collected %s Play Store reviews", len(normalized))
    return normalized


def collect_playstore_reviews_multi_sort(
    app_id: str | None = None,
    count: int | None = None,
    lang: str = "en",
    country: str = "in",
) -> list[dict[str, Any]]:
    """Fetch newest reviews (primary path used by live fetch)."""
    return collect_playstore_reviews(
        app_id=app_id, count=count, lang=lang, country=country
    )


def search_zepto_app_id() -> str:
    """Resolve Zepto consumer app id by name search; falls back to config default."""
    try:
        from google_play_scraper import search

        results = search("Zepto Groceries", lang="en", country="in", n_hits=8)
        for hit in results:
            title = (hit.get("title") or "").lower()
            app_id = hit.get("appId")
            if (
                app_id
                and "zepto" in title
                and "partner" not in title
                and "rider" not in title
                and "delivery" not in title
            ):
                return app_id
    except Exception as exc:
        logger.warning("App search failed, using configured app id: %s", exc)
    return PLAYSTORE_APP_ID


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    meta = fetch_app_metadata()
    print("App:", meta.get("title"), meta.get("score"), meta.get("reviews_count"))
    sample = collect_playstore_reviews(count=5)
    for row in sample[:3]:
        print(f"[{row['rating']}] {row['text'][:120]}...")
