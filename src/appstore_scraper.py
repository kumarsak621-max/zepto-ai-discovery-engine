"""Apple App Store review collector via iTunes Customer Reviews RSS (no API key)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from src.config import APPSTORE_APP_ID, APPSTORE_COUNTRY, APPSTORE_REVIEW_COUNT, has_appstore
from src.database import clean_text

logger = logging.getLogger(__name__)


def _score_to_sentiment(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 4:
        return "Positive"
    if score <= 2:
        return "Negative"
    return "Neutral"


def collect_appstore_reviews(
    app_id: str | None = None,
    country: str | None = None,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch newest App Store reviews using Apple's public RSS feed.

    Skips gracefully when App Store is disabled or the feed is unavailable.
    """
    if not has_appstore():
        logger.info("App Store collection skipped — not configured/enabled")
        return []

    app_id = app_id or APPSTORE_APP_ID
    country = (country or APPSTORE_COUNTRY or "in").lower()
    count = count or APPSTORE_REVIEW_COUNT

    collected: dict[str, dict[str, Any]] = {}
    # Apple RSS returns up to ~50 reviews per page; fetch a few pages
    pages = max(1, min(10, (count + 49) // 50))

    for page in range(1, pages + 1):
        url = (
            f"https://itunes.apple.com/{country}/rss/customerreviews/"
            f"page={page}/id={app_id}/sortby=mostrecent/json"
        )
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "zepto-ai-discovery-engine/1.0"},
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("App Store RSS page %s failed: %s", page, exc)
            break

        entries = (payload.get("feed") or {}).get("entry") or []
        # First entry is often the app metadata, not a review
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content", {})
            text_raw = content.get("label") if isinstance(content, dict) else None
            if not text_raw:
                continue
            text = clean_text(str(text_raw))
            if len(text) < 15:
                continue

            review_id = None
            id_block = entry.get("id")
            if isinstance(id_block, dict):
                review_id = id_block.get("label")
            rating = None
            rating_block = entry.get("im:rating")
            if isinstance(rating_block, dict) and rating_block.get("label") is not None:
                try:
                    rating = float(rating_block["label"])
                except (TypeError, ValueError):
                    rating = None

            updated = entry.get("updated", {})
            if isinstance(updated, dict) and updated.get("label"):
                date_str = str(updated["label"])
            else:
                date_str = datetime.now(timezone.utc).isoformat()

            title_block = entry.get("title", {})
            title = (
                clean_text(str(title_block.get("label") or ""))[:200]
                if isinstance(title_block, dict)
                else None
            )

            author_block = entry.get("author", {})
            reviewer_name = None
            if isinstance(author_block, dict):
                name_block = author_block.get("name", {})
                if isinstance(name_block, dict):
                    reviewer_name = clean_text(str(name_block.get("label") or ""))[:120] or None

            external_id = f"ios_{review_id}" if review_id else f"ios_{hash(text) & 0xFFFFFFFF:x}"
            collected[external_id] = {
                "source": "appstore",
                "text": text,
                "rating": rating,
                "date": date_str,
                "category": "app_review",
                "sentiment": _score_to_sentiment(rating),
                "theme": None,
                "user_intent": None,
                "app_version": None,
                "title": title,
                "upvotes": None,
                "external_id": external_id,
                "review_id": review_id,
                "review_text": text,
                "review_date": date_str,
                "app_name": "Zepto: Groceries in minutes",
                "reviewer_name": reviewer_name or title,
                "country": country,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "version": None,
                "helpful_votes": None,
            }
            if len(collected) >= count:
                break
        if len(collected) >= count:
            break

    rows = list(collected.values())
    logger.info("Collected %s App Store reviews", len(rows))
    return rows


def collect_appstore_or_empty(**kwargs) -> list[dict[str, Any]]:
    try:
        return collect_appstore_reviews(**kwargs)
    except Exception as exc:
        logger.error("App Store collection error: %s", exc)
        return []
