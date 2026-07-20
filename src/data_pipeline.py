"""
End-to-end data ingestion pipeline:

Collect Google Play + App Store → Clean → Deduplicate → Gemini → Store
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
    APPSTORE_REVIEW_COUNT,
    LIVE_BATCH_PATH,
    LIVE_CACHE_TTL_HOURS,
    LIVE_META_PATH,
    MIN_UNIQUE_REVIEWS,
    PLAYSTORE_CACHE_TTL_HOURS,
    PLAYSTORE_REVIEW_COUNT,
    has_appstore,
)
from src.database import (
    bulk_upsert,
    clean_text,
    content_hash,
    fetch_unanalyzed,
    finish_pipeline_run,
    get_collection_stats,
    init_db,
    start_pipeline_run,
    update_analysis,
)
from src.gemini_analysis import analyze_review
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


def save_live_batch_keys(reviews: list[dict[str, Any]]) -> list[str]:
    """
    Persist content hashes for the latest live fetch batch.

    Live Reviews mode displays only these newly fetched reviews.
    """
    ensure_runtime_dirs()
    keys: list[str] = []
    seen: set[str] = set()
    for row in reviews:
        text = (row.get("text") or row.get("review_text") or "").strip()
        if not text:
            continue
        source = row.get("source") or "unknown"
        external_id = row.get("external_id") or row.get("review_id")
        chash = row.get("content_hash") or content_hash(text, source, external_id)
        if chash in seen:
            continue
        seen.add(chash)
        keys.append(chash)
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "count": len(keys),
        "keys": keys,
    }
    LIVE_BATCH_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return keys


def load_live_batch_keys() -> list[str]:
    if not LIVE_BATCH_PATH.exists():
        return []
    try:
        payload = json.loads(LIVE_BATCH_PATH.read_text(encoding="utf-8"))
        keys = payload.get("keys") or []
        return [str(k) for k in keys if k]
    except Exception:
        return []


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
    Collect Google Play + App Store reviews, merge, dedupe, run Gemini analysis,
    and refresh the local knowledge base.

    Failover: each source failure is non-fatal. Analysis proceeds with whatever
    sources succeed. Only fails when zero reviews are available from live sources.
    """
    init_db()
    run_id = start_pipeline_run()
    counts: dict[str, int] = {
        "playstore_count": 0,
        "appstore_count": 0,
        "manual_count": 0,  # retained for DB schema compatibility; always 0
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
        target = max(
            int(playstore_count or PLAYSTORE_REVIEW_COUNT),
            int(MIN_UNIQUE_REVIEWS),
        )
        # --- Step 1: Google Play ---
        _progress(0.05, "Collecting Google Play reviews…")
        try:
            try:
                metadata = fetch_app_metadata()
            except Exception as meta_exc:
                logger.warning("Play Store metadata failed: %s", meta_exc)

            ttl = int(PLAYSTORE_CACHE_TTL_HOURS) * 3600
            db_total = int(get_collection_stats().get("total") or 0)
            need_top_up = db_total < int(MIN_UNIQUE_REVIEWS)
            if (
                not force_refresh
                and not need_top_up
                and cache_is_fresh(ttl_seconds=ttl)
            ):
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
                appstore = collect_appstore_or_empty(
                    count=max(int(APPSTORE_REVIEW_COUNT), 500)
                )
                counts["appstore_count"] = len(appstore)
                collected.extend(appstore)
                if not appstore:
                    source_messages.append("App Store returned no reviews.")
            except Exception as exc:
                logger.exception("App Store collection failed")
                source_messages.append(f"App Store unavailable: {exc}")
        else:
            source_messages.append("App Store is not configured.")

        counts["manual_count"] = 0

        # --- Failover: never crash if at least one live source has data ---
        if not collected:
            raise RuntimeError(
                "No reviews available from Google Play or App Store. "
                + " ".join(source_messages)
            )

        # --- Steps 3–5: Merge + dedupe + store ---
        _progress(0.60, "Merging sources and removing duplicates…")
        merged = merge_and_dedupe_reviews(collected)
        counts["merged_count"] = len(merged)
        merged_path = save_merged_reviews_csv(merged)

        _progress(0.75, "Saving merged reviews to feedback.db…")
        inserted = bulk_upsert(merged)
        counts["new_reviews"] = inserted
        live_batch_keys = save_live_batch_keys(merged)

        # --- Top-up toward MIN_UNIQUE_REVIEWS using real store pages only ---
        warehouse_total = int(get_collection_stats().get("total") or 0)
        top_up_round = 0
        while warehouse_total < int(MIN_UNIQUE_REVIEWS) and top_up_round < 3:
            top_up_round += 1
            shortfall = int(MIN_UNIQUE_REVIEWS) - warehouse_total
            _progress(
                0.78,
                f"Topping up warehouse ({warehouse_total}/{MIN_UNIQUE_REVIEWS})…",
            )
            extra: list[dict[str, Any]] = []
            try:
                more_play = collect_playstore_reviews(
                    count=max(target, warehouse_total + shortfall + 100),
                    lang="en",
                    country="in",
                )
                extra.extend(more_play)
                counts["playstore_count"] = max(
                    counts["playstore_count"], len(more_play)
                )
            except Exception as exc:
                logger.warning("Play Store top-up failed: %s", exc)
                source_messages.append(f"Play Store top-up stopped: {exc}")
            if has_appstore():
                try:
                    more_ios = collect_appstore_or_empty(
                        count=max(int(APPSTORE_REVIEW_COUNT), 500)
                    )
                    extra.extend(more_ios)
                    counts["appstore_count"] = max(
                        counts["appstore_count"], len(more_ios)
                    )
                except Exception as exc:
                    logger.warning("App Store top-up failed: %s", exc)
            if not extra:
                break
            extra_merged = merge_and_dedupe_reviews(extra)
            added = bulk_upsert(extra_merged)
            counts["new_reviews"] += added
            new_total = int(get_collection_stats().get("total") or 0)
            if new_total <= warehouse_total:
                # APIs returned no additional unique reviews
                break
            warehouse_total = new_total
        counts["warehouse_total"] = warehouse_total
        counts["min_unique_target"] = int(MIN_UNIQUE_REVIEWS)

        # --- Step 6: Gemini ---
        _progress(0.88, "Running Gemini analysis on merged dataset…")
        analyzed = run_analysis(batch_size=max(analyze_limit, len(merged) or 1))
        counts["analyzed_count"] = analyzed

        # --- Step 7: Refresh meta for dashboards / chatbot ---
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
            "live_batch_keys": live_batch_keys,
            "live_batch_count": len(live_batch_keys),
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
