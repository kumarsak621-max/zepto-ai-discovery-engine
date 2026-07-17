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
from src.playstore_scraper import collect_playstore_reviews
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
