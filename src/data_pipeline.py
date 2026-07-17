"""
End-to-end data ingestion pipeline:

Collect → Clean → Deduplicate → Gemini analysis → Store in feedback.db → Chatbot ready
"""

from __future__ import annotations

import logging
from typing import Any

from src.database import (
    bulk_upsert,
    clean_text,
    fetch_unanalyzed,
    finish_pipeline_run,
    init_db,
    start_pipeline_run,
    update_analysis,
)
from src.gemini_analysis import analyze_review
from src.playstore_scraper import (
    cache_is_fresh,
    collect_playstore_reviews,
    fetch_app_metadata,
    get_last_updated_timestamp,
    load_reviews_from_csv,
    save_reviews_csv,
)
from src.reddit_scraper import collect_reddit_or_empty
from src.twitter_placeholder import collect_twitter_mentions

logger = logging.getLogger(__name__)


def _clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for row in records:
        text = clean_text(row.get("text") or "")
        if len(text) < 15:
            continue
        row = {**row, "text": text}
        if row.get("title"):
            row["title"] = clean_text(row["title"])
        cleaned.append(row)
    return cleaned


def run_collection() -> dict[str, int]:
    """Collect from all sources. Dedup happens at DB upsert via content_hash."""
    playstore: list[dict[str, Any]] = []
    reddit: list[dict[str, Any]] = []
    twitter: list[dict[str, Any]] = []

    try:
        playstore = collect_playstore_reviews()
        save_reviews_csv(playstore)
    except Exception as exc:
        logger.error("Play Store collection failed: %s", exc)

    reddit = collect_reddit_or_empty()
    twitter = collect_twitter_mentions()

    all_rows = _clean_records(playstore + reddit + twitter)
    inserted = bulk_upsert(all_rows)

    return {
        "playstore_count": len(playstore),
        "reddit_count": len(reddit),
        "twitter_count": len(twitter),
        "new_reviews": inserted,
    }


def run_playstore_fetch(
    count: int | None = None,
    analyze_limit: int = 500,
    force_refresh: bool = False,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """
    Fetch latest Google Play reviews for Zepto (com.zeptoconsumerapp):

    1. Use cache (data/reviews.csv) when fresh unless force_refresh
    2. Otherwise download English reviews from Google Play
    3. Dedupe + save CSV
    4. Upsert into feedback.db
    5. Run Gemini analysis so dashboards + chatbot update
    """
    from src.config import PLAYSTORE_CACHE_TTL_HOURS, PLAYSTORE_REVIEW_COUNT

    init_db()
    run_id = start_pipeline_run()
    counts: dict[str, int] = {
        "playstore_count": 0,
        "reddit_count": 0,
        "twitter_count": 0,
        "new_reviews": 0,
        "analyzed_count": 0,
    }
    metadata: dict[str, Any] = {}
    used_cache = False
    download_timestamp = get_last_updated_timestamp()
    target_count = count or PLAYSTORE_REVIEW_COUNT

    def _progress(pct: float, msg: str) -> None:
        if progress_callback:
            progress_callback(pct, msg)

    try:
        _progress(0.02, "Preparing Google Play fetch…")
        try:
            metadata = fetch_app_metadata()
        except Exception as meta_exc:
            logger.warning("Play Store metadata fetch failed: %s", meta_exc)

        ttl = int(PLAYSTORE_CACHE_TTL_HOURS) * 3600
        if not force_refresh and cache_is_fresh(ttl_seconds=ttl):
            _progress(0.35, "Using cached reviews (still fresh)…")
            playstore = load_reviews_from_csv()
            used_cache = True
            download_timestamp = get_last_updated_timestamp()
        else:
            _progress(0.08, "Downloading latest English reviews from Google Play…")
            playstore = collect_playstore_reviews(
                count=target_count,
                lang="en",
                country="in",
                progress_callback=_progress,
            )
            if not playstore:
                raise RuntimeError(
                    "No reviews returned from Google Play. The service may be temporarily unavailable."
                )
            _progress(0.92, "Saving reviews to data/reviews.csv…")
            save_reviews_csv(playstore)
            download_timestamp = get_last_updated_timestamp()

        cleaned = _clean_records(playstore)
        _progress(0.94, "Updating feedback.db…")
        inserted = bulk_upsert(cleaned)
        counts["playstore_count"] = len(playstore)
        counts["new_reviews"] = inserted

        _progress(0.96, "Running Gemini review analysis…")
        analyzed = run_analysis(batch_size=max(analyze_limit, len(cleaned) or 1))
        counts["analyzed_count"] = analyzed

        _progress(1.0, "Done")
        finish_pipeline_run(run_id, status="success", counts=counts)
        return {
            "status": "success",
            "run_id": run_id,
            "app_metadata": metadata,
            "used_cache": used_cache,
            "download_timestamp": download_timestamp,
            "reviews_csv": "data/reviews.csv",
            **counts,
        }
    except Exception as exc:
        logger.exception("Play Store fetch pipeline failed")
        finish_pipeline_run(
            run_id, status="failed", counts=counts, error_message=str(exc)
        )
        return {
            "status": "failed",
            "run_id": run_id,
            "error": str(exc),
            "app_metadata": metadata,
            "used_cache": used_cache,
            "download_timestamp": download_timestamp,
            **counts,
        }


def run_analysis(batch_size: int = 100) -> int:
    """Run Gemini (or fallback) advanced analysis on unanalyzed reviews."""
    pending = fetch_unanalyzed(limit=batch_size)
    analyzed = 0
    for review in pending:
        result = analyze_review(review["text"], rating=review.get("rating"))
        update_analysis(review_id=review["id"], analysis=result)
        analyzed += 1
    logger.info("Analyzed %s reviews with advanced structured schema", analyzed)
    return analyzed


def run_full_pipeline(analyze_limit: int = 100) -> dict[str, Any]:
    """
    Full daily workflow:

    Scheduler → Collect → Clean → Dedup → Gemini → Store in SQLite → Chatbot ready
    """
    init_db()
    run_id = start_pipeline_run()
    counts: dict[str, int] = {
        "playstore_count": 0,
        "reddit_count": 0,
        "twitter_count": 0,
        "new_reviews": 0,
        "analyzed_count": 0,
    }

    try:
        logger.info("=== Zepto AI pipeline started (run_id=%s) ===", run_id)
        collection = run_collection()
        counts.update(collection)

        analyzed = run_analysis(batch_size=analyze_limit)
        counts["analyzed_count"] = analyzed

        finish_pipeline_run(run_id, status="success", counts=counts)
        logger.info("=== Pipeline complete: %s ===", counts)
        return {"status": "success", "run_id": run_id, **counts}
    except Exception as exc:
        logger.exception("Pipeline failed")
        finish_pipeline_run(
            run_id, status="failed", counts=counts, error_message=str(exc)
        )
        return {"status": "failed", "run_id": run_id, "error": str(exc), **counts}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    summary = run_full_pipeline()
    print(summary)
