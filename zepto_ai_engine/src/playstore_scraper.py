"""Google Play Store review collector for Zepto."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.config import PLAYSTORE_APP_ID, PLAYSTORE_APP_NAME, PLAYSTORE_REVIEW_COUNT
from src.database import clean_text

logger = logging.getLogger(__name__)


def _score_to_sentiment(score: int | float | None) -> str | None:
    if score is None:
        return None
    if score >= 4:
        return "Positive"
    if score <= 2:
        return "Negative"
    return "Neutral"


def collect_playstore_reviews(
    app_id: str | None = None,
    count: int | None = None,
    lang: str = "en",
    country: str = "in",
) -> list[dict[str, Any]]:
    """
    Collect reviews for Zepto: Groceries in 10 minutes via google-play-scraper.

    Returns normalized review dicts ready for database upsert.
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
        "Collecting Play Store reviews for %s (%s), count=%s",
        PLAYSTORE_APP_NAME,
        app_id,
        count,
    )

    try:
        result, _ = reviews(
            app_id,
            lang=lang,
            country=country,
            sort=Sort.NEWEST,
            count=count,
            filter_score_with=None,
        )
    except Exception as exc:
        logger.error("Play Store scrape failed: %s", exc)
        raise

    normalized: list[dict[str, Any]] = []
    for item in result:
        text = clean_text(item.get("content") or "")
        if not text:
            continue

        at = item.get("at")
        if isinstance(at, datetime):
            date_str = at.astimezone(timezone.utc).isoformat()
        elif at:
            date_str = str(at)
        else:
            date_str = datetime.now(timezone.utc).isoformat()

        score = item.get("score")
        normalized.append(
            {
                "source": "playstore",
                "text": text,
                "rating": float(score) if score is not None else None,
                "date": date_str,
                "category": "app_review",
                "sentiment": _score_to_sentiment(score),
                "theme": None,
                "user_intent": None,
                "app_version": item.get("reviewCreatedVersion")
                or item.get("appVersion"),
                "title": item.get("userName"),
                "upvotes": item.get("thumbsUpCount"),
                "external_id": item.get("reviewId"),
            }
        )

    logger.info("Collected %s Play Store reviews", len(normalized))
    return normalized


def search_zepto_app_id() -> str:
    """Resolve Zepto consumer app id by name search; falls back to config default."""
    try:
        from google_play_scraper import search

        results = search("Zepto Groceries", lang="en", country="in", n_hits=8)
        for hit in results:
            title = (hit.get("title") or "").lower()
            app_id = hit.get("appId")
            # Prefer consumer app, skip rider/partner apps
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
    sample = collect_playstore_reviews(count=5)
    for row in sample[:3]:
        print(f"[{row['rating']}] {row['text'][:120]}...")
