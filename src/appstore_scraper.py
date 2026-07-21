"""Apple App Store live review collector via iTunes Customer Reviews RSS (no API key)."""

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


def _rss_urls(app_id: str, country: str, page: int) -> list[str]:
    """Known-working + legacy iTunes RSS URL shapes (Apple has changed casing over time)."""
    c = (country or "us").lower()
    return [
        (
            f"https://itunes.apple.com/{c}/rss/customerreviews/"
            f"page={page}/id={app_id}/sortBy=mostRecent/json"
        ),
        (
            f"https://itunes.apple.com/{c}/rss/customerreviews/"
            f"page={page}/id={app_id}/sortby=mostrecent/json"
        ),
        (
            f"https://itunes.apple.com/{c}/rss/customerreviews/"
            f"id={app_id}/sortBy=mostRecent/json"
        ),
    ]


def _country_candidates(primary: str | None) -> list[str]:
    primary = (primary or APPSTORE_COUNTRY or "in").lower()
    ordered = [primary]
    for c in ("us", "in", "gb", "au", "ca"):
        if c not in ordered:
            ordered.append(c)
    return ordered


def _fetch_rss_page(app_id: str, country: str, page: int) -> list[dict[str, Any]]:
    last_err: Exception | None = None
    for url in _rss_urls(app_id, country, page):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; zepto-ai-discovery-engine/1.0)",
                    "Accept": "application/json,text/javascript,*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            entries = (payload.get("feed") or {}).get("entry") or []
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                return []
            return [e for e in entries if isinstance(e, dict)]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_err = exc
            continue
    if last_err:
        logger.warning(
            "App Store RSS page %s country=%s failed: %s", page, country, last_err
        )
    return []


def _entry_to_review(
    entry: dict[str, Any],
    *,
    country: str,
) -> dict[str, Any] | None:
    content = entry.get("content", {})
    text_raw = content.get("label") if isinstance(content, dict) else None
    if not text_raw:
        return None
    text = clean_text(str(text_raw))
    if len(text) < 15:
        return None

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
    return {
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


def collect_appstore_reviews(
    app_id: str | None = None,
    country: str | None = None,
    count: int | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch newest App Store reviews using Apple's public RSS feed.

    Tries the configured country first, then common storefront fallbacks
    (Apple's IN feed is often empty even when US has reviews).
    Skips gracefully when App Store is disabled or the feed is unavailable.
    """
    if not has_appstore():
        logger.info("App Store collection skipped — not configured/enabled")
        return []

    app_id = app_id or APPSTORE_APP_ID
    count = count or APPSTORE_REVIEW_COUNT
    collected: dict[str, dict[str, Any]] = {}
    pages = max(1, min(10, (count + 49) // 50))

    for store_country in _country_candidates(country):
        page_hits = 0
        for page in range(1, pages + 1):
            entries = _fetch_rss_page(app_id, store_country, page)
            if not entries:
                break
            # First entry is often app metadata, not a review
            for entry in entries:
                row = _entry_to_review(entry, country=store_country)
                if not row:
                    continue
                collected[row["external_id"]] = row
                page_hits += 1
                if len(collected) >= count:
                    break
            if len(collected) >= count:
                break
        if collected:
            logger.info(
                "Collected %s App Store reviews (country=%s, page_hits=%s)",
                len(collected),
                store_country,
                page_hits,
            )
            break
        logger.info("App Store country=%s returned no reviews — trying next", store_country)

    rows = list(collected.values())
    if not rows:
        logger.warning("Collected 0 App Store reviews after country fallbacks")
    return rows


def collect_appstore_or_empty(**kwargs) -> list[dict[str, Any]]:
    try:
        return collect_appstore_reviews(**kwargs)
    except Exception as exc:
        logger.error("App Store collection error: %s", exc)
        return []
