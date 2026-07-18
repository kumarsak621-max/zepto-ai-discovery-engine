"""
End-to-end data ingestion pipeline:

Collect online sources + optional manual upload → Clean → Deduplicate → Gemini → Store
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.appstore_scraper import collect_appstore_or_empty
from src.config import (
    LIVE_CACHE_TTL_HOURS,
    LIVE_META_PATH,
    PLAYSTORE_CACHE_TTL_HOURS,
    PLAYSTORE_REVIEW_COUNT,
    has_appstore,
)
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
from src.manual_reviews import load_manual_reviews
from src.paths import DATA_DIR, ensure_runtime_dirs
from src.playstore_scraper import (
    cache_is_fresh,
    collect_playstore_reviews,
    fetch_app_metadata,
    get_last_updated_timestamp,
    load_reviews_from_csv,
    save_reviews_csv,
)
from src.twitter_placeholder import collect_twitter_mentions

logger = logging.getLogger(__name__)


def _normalize_text_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _date_key(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # Prefer YYYY-MM-DD when present
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if m:
        return m.group(0)
    return s[:10]


def _rating_key(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return str(value).strip()


def _text_similar(a: str, b: str) -> bool:
    """Lightweight similarity: containment or high word overlap."""
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 40 and shorter in longer:
        return True
    wa = set(shorter.split())
    wb = set(longer.split())
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / max(len(wa), 1)
    return overlap >= 0.85 and abs(len(wa) - len(wb)) <= max(3, len(wa) // 5)


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


def merge_and_dedupe_reviews(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge multi-source reviews; dedupe by:
      • review_id / external_id
      • review text similarity
      • rating + date (+ text fingerprint)
    """
    cleaned = _clean_records(records)
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    seen_rating_date: set[str] = set()
    kept: list[tuple[str, str, str]] = []  # text_key, rating_key, date_key
    merged: list[dict[str, Any]] = []

    for row in cleaned:
        text_key = _normalize_text_key(row["text"])
        eid = str(
            row.get("external_id") or row.get("review_id") or ""
        ).strip()
        rkey = _rating_key(row.get("rating"))
        dkey = _date_key(row.get("date"))
        rating_date_key = f"{rkey}|{dkey}|{text_key[:80]}" if (rkey or dkey) else ""

        if eid and eid in seen_ids:
            continue
        if text_key in seen_text:
            continue
        if rating_date_key and rating_date_key in seen_rating_date:
            continue

        # Near-duplicate: similar text with the same rating + date
        is_near_dup = False
        for prev_text, prev_r, prev_d in kept:
            if not _text_similar(text_key, prev_text):
                continue
            if rkey and dkey and rkey == prev_r and dkey == prev_d:
                is_near_dup = True
                break
            if not rkey and not dkey and (
                text_key == prev_text
                or (len(text_key) >= 40 and text_key in prev_text)
            ):
                is_near_dup = True
                break
        if is_near_dup:
            continue

        if eid:
            seen_ids.add(eid)
        seen_text.add(text_key)
        if rating_date_key:
            seen_rating_date.add(rating_date_key)
        kept.append((text_key, rkey, dkey))
        merged.append(row)

    logger.info("Merged %s raw rows → %s unique reviews", len(cleaned), len(merged))
    return merged


def reviews_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(
            columns=["source", "text", "rating", "date", "external_id", "category"]
        )
    return pd.DataFrame(
        [
            {
                "source": r.get("source"),
                "text": r.get("text"),
                "rating": r.get("rating"),
                "date": r.get("date"),
                "external_id": r.get("external_id"),
                "category": r.get("category"),
                "upvotes": r.get("upvotes"),
                "title": r.get("title"),
            }
            for r in records
        ]
    )


def save_merged_reviews_csv(records: list[dict[str, Any]]) -> str:
    ensure_runtime_dirs()
    path = DATA_DIR / "merged_reviews.csv"
    reviews_to_dataframe(records).to_csv(path, index=False, encoding="utf-8")
    return "data/merged_reviews.csv"


def save_live_meta(counts: dict[str, Any], *, forced: bool = False) -> dict[str, Any]:
    ensure_runtime_dirs()
    meta = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "forced_refresh": forced,
        "playstore_count": int(counts.get("playstore_count") or 0),
        "appstore_count": int(counts.get("appstore_count") or 0),
        "manual_count": int(counts.get("manual_count") or 0),
        "merged_count": int(counts.get("merged_count") or 0),
        "analyzed_count": int(counts.get("analyzed_count") or 0),
        "new_reviews": int(counts.get("new_reviews") or 0),
    }
    LIVE_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def get_live_meta() -> dict[str, Any]:
    if not LIVE_META_PATH.exists():
        # Fall back to Play Store cache timestamp
        ts = get_last_updated_timestamp()
        if ts:
            return {"last_updated": ts}
        return {}
    try:
        return json.loads(LIVE_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def live_data_is_fresh(ttl_hours: int | None = None) -> bool:
    meta = get_live_meta()
    last = meta.get("last_updated")
    if not last:
        return False
    try:
        ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        ttl = (ttl_hours if ttl_hours is not None else LIVE_CACHE_TTL_HOURS) * 3600
        if age >= ttl:
            return False
        merged = int(meta.get("merged_count") or 0)
        if merged > 0:
            return True
        # Fallback: any reviews already in the local DB count as usable live data
        from src.database import get_collection_stats

        return int(get_collection_stats().get("total") or 0) > 0
    except Exception:
        return False


def run_analysis(batch_size: int = 100) -> int:
    pending = fetch_unanalyzed(limit=batch_size)
    analyzed = 0
    for review in pending:
        result = analyze_review(review["text"], rating=review.get("rating"))
        update_analysis(review_id=review["id"], analysis=result)
        analyzed += 1
    logger.info("Analyzed %s reviews", analyzed)
    return analyzed


def run_live_review_analysis(
    *,
    force_refresh: bool = False,
    playstore_count: int | None = None,
    analyze_limit: int = 500,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """
    Collect Google Play + App Store + optional manual uploads, merge, dedupe,
    run Gemini analysis, and refresh the local knowledge base.

    Failover: each source failure is non-fatal. Analysis proceeds with whatever
    sources succeed. Only fails when zero reviews are available from all sources.
    """
    init_db()
    run_id = start_pipeline_run()
    counts: dict[str, int] = {
        "playstore_count": 0,
        "appstore_count": 0,
        "manual_count": 0,
        "twitter_count": 0,
        "merged_count": 0,
        "new_reviews": 0,
        "analyzed_count": 0,
    }
    metadata: dict[str, Any] = {}
    source_messages: list[str] = []
    collected: list[dict[str, Any]] = []
    used_cache = False

    def _progress(pct: float, msg: str) -> None:
        if progress_callback:
            progress_callback(pct, msg)

    try:
        # --- Step 1: Google Play ---
        _progress(0.05, "Collecting Google Play reviews…")
        try:
            try:
                metadata = fetch_app_metadata()
            except Exception as meta_exc:
                logger.warning("Play Store metadata failed: %s", meta_exc)

            ttl = int(PLAYSTORE_CACHE_TTL_HOURS) * 3600
            target = playstore_count or PLAYSTORE_REVIEW_COUNT
            if not force_refresh and cache_is_fresh(ttl_seconds=ttl):
                playstore = load_reviews_from_csv()
                used_cache = True
                _progress(0.25, "Using cached Google Play reviews…")
            else:
                playstore = collect_playstore_reviews(
                    count=target,
                    lang="en",
                    country="in",
                    progress_callback=_progress,
                )
                if playstore:
                    save_reviews_csv(playstore)
            counts["playstore_count"] = len(playstore)
            collected.extend(playstore)
            if not playstore:
                source_messages.append("Google Play returned no reviews.")
        except Exception as exc:
            logger.exception("Google Play collection failed")
            source_messages.append(f"Google Play unavailable: {exc}")

        # --- Step 2: Apple App Store ---
        _progress(0.40, "Collecting App Store reviews…")
        if has_appstore():
            try:
                appstore = collect_appstore_or_empty()
                counts["appstore_count"] = len(appstore)
                collected.extend(appstore)
                if not appstore:
                    source_messages.append("App Store returned no reviews.")
            except Exception as exc:
                logger.exception("App Store collection failed")
                source_messages.append(f"App Store unavailable: {exc}")
        else:
            source_messages.append("App Store is not configured.")

        # --- Step 3: Manual upload (if present) ---
        _progress(0.55, "Loading manual uploaded reviews…")
        try:
            manual = load_manual_reviews()
            counts["manual_count"] = len(manual)
            if manual:
                collected.extend(manual)
                source_messages.append(f"Manual upload: {len(manual)} reviews loaded.")
            else:
                source_messages.append(
                    "No manual review file uploaded — using live sources only."
                )
        except Exception as exc:
            logger.exception("Manual review load failed")
            source_messages.append(f"Manual upload unavailable: {exc}")

        # --- Failover: never crash if at least one source has data ---
        if not collected:
            raise RuntimeError(
                "No reviews available from Google Play, App Store, or manual upload. "
                + " ".join(source_messages)
            )

        # --- Steps 4–6: Merge + dedupe ---
        _progress(0.70, "Merging sources and removing duplicates…")
        merged = merge_and_dedupe_reviews(collected)
        counts["merged_count"] = len(merged)
        merged_path = save_merged_reviews_csv(merged)

        _progress(0.82, "Saving merged reviews to feedback.db…")
        inserted = bulk_upsert(merged)
        counts["new_reviews"] = inserted

        # --- Step 7: Gemini ---
        _progress(0.90, "Running Gemini analysis on merged dataset…")
        analyzed = run_analysis(batch_size=max(analyze_limit, len(merged) or 1))
        counts["analyzed_count"] = analyzed

        # --- Step 8: Refresh meta for dashboards / chatbot ---
        live_meta = save_live_meta(counts, forced=force_refresh)
        _progress(1.0, "Done")
        finish_pipeline_run(run_id, status="success", counts=counts)
        return {
            "status": "success",
            "run_id": run_id,
            "app_metadata": metadata,
            "used_cache": used_cache,
            "download_timestamp": live_meta.get("last_updated"),
            "merged_csv": merged_path,
            "source_messages": source_messages,
            **counts,
        }
    except Exception as exc:
        logger.exception("Live review analysis failed")
        finish_pipeline_run(
            run_id, status="failed", counts=counts, error_message=str(exc)
        )
        return {
            "status": "failed",
            "run_id": run_id,
            "error": str(exc),
            "app_metadata": metadata,
            "source_messages": source_messages,
            "download_timestamp": get_live_meta().get("last_updated"),
            **counts,
        }


def run_collection() -> dict[str, int]:
    """Scheduler-friendly collection across online sources."""
    result = run_live_review_analysis(force_refresh=False, analyze_limit=200)
    return {
        "playstore_count": int(result.get("playstore_count") or 0),
        "appstore_count": int(result.get("appstore_count") or 0),
        "manual_count": int(result.get("manual_count") or 0),
        "twitter_count": int(result.get("twitter_count") or 0),
        "new_reviews": int(result.get("new_reviews") or 0),
    }


def run_playstore_fetch(
    count: int | None = None,
    analyze_limit: int = 500,
    force_refresh: bool = False,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    """Backward-compatible Play Store–focused wrapper around live analysis."""
    return run_live_review_analysis(
        force_refresh=force_refresh,
        playstore_count=count,
        analyze_limit=analyze_limit,
        progress_callback=progress_callback,
    )


def run_full_pipeline(analyze_limit: int = 100) -> dict[str, Any]:
    result = run_live_review_analysis(
        force_refresh=True, analyze_limit=analyze_limit
    )
    # Also pull twitter placeholder if ever enabled (non-blocking)
    try:
        twitter = collect_twitter_mentions()
        if twitter:
            bulk_upsert(_clean_records(twitter))
            result["twitter_count"] = len(twitter)
    except Exception:
        pass
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print(run_live_review_analysis(force_refresh=True, playstore_count=20))
