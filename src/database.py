"""SQLite storage for customer feedback reviews + advanced AI analysis."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.config import DATABASE_PATH, EXPLORATION_BARRIER_THEMES


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    rating REAL,
    date TEXT,
    category TEXT,
    sentiment TEXT,
    theme TEXT,
    user_intent TEXT,
    review_summary TEXT,
    customer_segment TEXT,
    pain_point TEXT,
    root_cause TEXT,
    product_opportunity TEXT,
    app_version TEXT,
    title TEXT,
    upvotes INTEGER,
    external_id TEXT,
    content_hash TEXT UNIQUE,
    analyzed INTEGER DEFAULT 0,
    embedded INTEGER DEFAULT 0,
    app_name TEXT,
    reviewer_name TEXT,
    country TEXT,
    fetched_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    playstore_count INTEGER DEFAULT 0,
    appstore_count INTEGER DEFAULT 0,
    manual_count INTEGER DEFAULT 0,
    twitter_count INTEGER DEFAULT 0,
    new_reviews INTEGER DEFAULT 0,
    analyzed_count INTEGER DEFAULT 0,
    embedded_count INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_reviews_source ON reviews(source);
CREATE INDEX IF NOT EXISTS idx_reviews_sentiment ON reviews(sentiment);
CREATE INDEX IF NOT EXISTS idx_reviews_theme ON reviews(theme);
CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(date);
CREATE INDEX IF NOT EXISTS idx_reviews_analyzed ON reviews(analyzed);
"""

# Columns added after v1 — applied via ALTER TABLE for existing DBs
ADVANCED_COLUMNS = {
    "review_summary": "TEXT",
    "customer_segment": "TEXT",
    "pain_point": "TEXT",
    "root_cause": "TEXT",
    "product_opportunity": "TEXT",
    "app_name": "TEXT",
    "reviewer_name": "TEXT",
    "country": "TEXT",
    "fetched_at": "TEXT",
}


def content_hash(text: str, source: str, external_id: str | None = None) -> str:
    raw = f"{source}|{external_id or ''}|{text.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(reviews)").fetchall()
    }
    for col, col_type in ADVANCED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE reviews ADD COLUMN {col} {col_type}")
    # Indexes that depend on migrated columns
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_segment ON reviews(customer_segment)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_fetched_at ON reviews(fetched_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews(created_at)"
    )
    # Backfill fetched_at from created_at for older rows (never delete historical data)
    conn.execute(
        """
        UPDATE reviews
        SET fetched_at = COALESCE(fetched_at, created_at, updated_at)
        WHERE fetched_at IS NULL OR fetched_at = ''
        """
    )

    # pipeline_runs: replace legacy reddit_count with appstore/manual counts
    run_cols = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()
    }
    if run_cols:
        if "appstore_count" not in run_cols:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN appstore_count INTEGER DEFAULT 0"
            )
        if "manual_count" not in run_cols:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN manual_count INTEGER DEFAULT 0"
            )


def init_db(db_path: Path | None = None) -> Path:
    path = Path(db_path or DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_schema(conn)
    return path


def upsert_review(review: dict[str, Any], db_path: Path | None = None) -> bool:
    """Insert a review if it is not a duplicate. Returns True if inserted. Never updates/deletes."""
    text = (review.get("text") or review.get("review_text") or "").strip()
    if not text:
        return False

    source = review.get("source", "unknown")
    external_id = review.get("external_id") or review.get("review_id")
    chash = review.get("content_hash") or content_hash(text, source, external_id)
    now = datetime.now(timezone.utc).isoformat()

    fully_analyzed = bool(
        review.get("sentiment")
        and review.get("theme")
        and review.get("user_intent")
        and review.get("review_summary")
        and review.get("customer_segment")
    )

    payload = {
        "source": source,
        "text": text,
        "rating": review.get("rating"),
        "date": review.get("date") or review.get("review_date"),
        "category": review.get("category"),
        "sentiment": review.get("sentiment"),
        "theme": review.get("theme"),
        "user_intent": review.get("user_intent"),
        "review_summary": review.get("review_summary"),
        "customer_segment": review.get("customer_segment"),
        "pain_point": review.get("pain_point"),
        "root_cause": review.get("root_cause"),
        "product_opportunity": review.get("product_opportunity"),
        "app_version": review.get("app_version") or review.get("version"),
        "title": review.get("title"),
        "upvotes": review.get("upvotes"),
        "external_id": external_id,
        "content_hash": chash,
        "analyzed": 1 if fully_analyzed else 0,
        "embedded": 0,
        "app_name": review.get("app_name") or "Zepto",
        "reviewer_name": review.get("reviewer_name")
        or review.get("userName")
        or review.get("title"),
        "country": review.get("country"),
        "fetched_at": review.get("fetched_at") or now,
        "updated_at": now,
    }

    with get_connection(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO reviews (
                    source, text, rating, date, category, sentiment, theme,
                    user_intent, review_summary, customer_segment, pain_point,
                    root_cause, product_opportunity, app_version, title, upvotes,
                    external_id, content_hash, analyzed, embedded,
                    app_name, reviewer_name, country, fetched_at, updated_at
                ) VALUES (
                    :source, :text, :rating, :date, :category, :sentiment, :theme,
                    :user_intent, :review_summary, :customer_segment, :pain_point,
                    :root_cause, :product_opportunity, :app_version, :title, :upvotes,
                    :external_id, :content_hash, :analyzed, :embedded,
                    :app_name, :reviewer_name, :country, :fetched_at, :updated_at
                )
                """,
                payload,
            )
            return True
        except sqlite3.IntegrityError:
            return False


def bulk_upsert(reviews: list[dict[str, Any]], db_path: Path | None = None) -> int:
    inserted = 0
    for review in reviews:
        if upsert_review(review, db_path=db_path):
            inserted += 1
    return inserted


def update_analysis(
    review_id: int,
    analysis: dict[str, Any],
    db_path: Path | None = None,
) -> None:
    """Persist the full advanced Gemini analysis payload for a review."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE reviews
            SET sentiment = ?,
                theme = ?,
                user_intent = ?,
                category = COALESCE(?, category),
                review_summary = ?,
                customer_segment = ?,
                pain_point = ?,
                root_cause = ?,
                product_opportunity = ?,
                analyzed = 1,
                embedded = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                analysis.get("sentiment"),
                analysis.get("theme"),
                analysis.get("user_intent"),
                analysis.get("category"),
                analysis.get("review_summary"),
                analysis.get("customer_segment"),
                analysis.get("pain_point"),
                analysis.get("root_cause"),
                analysis.get("product_opportunity"),
                datetime.now(timezone.utc).isoformat(),
                review_id,
            ),
        )


def mark_embedded(review_ids: list[int], db_path: Path | None = None) -> None:
    if not review_ids:
        return
    placeholders = ",".join("?" * len(review_ids))
    with get_connection(db_path) as conn:
        conn.execute(
            f"""
            UPDATE reviews
            SET embedded = 1, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [datetime.now(timezone.utc).isoformat(), *review_ids],
        )


def fetch_unanalyzed(limit: int = 200, db_path: Path | None = None) -> list[dict]:
    """Reviews missing core OR advanced analysis fields."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM reviews
            WHERE analyzed = 0
               OR theme IS NULL OR theme = ''
               OR user_intent IS NULL OR user_intent = ''
               OR review_summary IS NULL OR review_summary = ''
               OR customer_segment IS NULL OR customer_segment = ''
               OR product_opportunity IS NULL OR product_opportunity = ''
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_unembedded(limit: int = 500, db_path: Path | None = None) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM reviews
            WHERE analyzed = 1 AND embedded = 0
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_all_reviews(
    source: str | None = None,
    sentiment: str | None = None,
    limit: int | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if source:
        clauses.append("source = ?")
        params.append(source)
    if sentiment:
        clauses.append("sentiment = ?")
        params.append(sentiment)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit_sql = f"LIMIT {int(limit)}" if limit else ""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM reviews {where} ORDER BY date DESC, id DESC {limit_sql}",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _top_n(counter: Counter, n: int = 10) -> list[dict[str, Any]]:
    return [{"label": k, "count": v} for k, v in counter.most_common(n) if k]


def get_collection_stats(db_path: Path | None = None) -> dict[str, Any]:
    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()["c"]
        by_source = {
            row["source"]: row["c"]
            for row in conn.execute(
                "SELECT source, COUNT(*) AS c FROM reviews GROUP BY source"
            ).fetchall()
        }
        by_sentiment = {
            row["sentiment"] or "Unanalyzed": row["c"]
            for row in conn.execute(
                "SELECT sentiment, COUNT(*) AS c FROM reviews GROUP BY sentiment"
            ).fetchall()
        }
        by_theme = {
            row["theme"] or "Unanalyzed": row["c"]
            for row in conn.execute(
                """
                SELECT theme, COUNT(*) AS c FROM reviews
                WHERE theme IS NOT NULL AND theme != ''
                GROUP BY theme
                ORDER BY c DESC
                """
            ).fetchall()
        }
        last_row = conn.execute(
            "SELECT MAX(updated_at) AS last_update FROM reviews"
        ).fetchone()
        avg_row = conn.execute(
            """
            SELECT AVG(rating) AS avg_rating, COUNT(rating) AS rated_count
            FROM reviews
            WHERE rating IS NOT NULL
            """
        ).fetchone()
        last_run = conn.execute(
            """
            SELECT * FROM pipeline_runs
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        complaints = conn.execute(
            """
            SELECT theme, COUNT(*) AS c FROM reviews
            WHERE user_intent = 'Complaint' AND theme IS NOT NULL
            GROUP BY theme
            ORDER BY c DESC
            LIMIT 10
            """
        ).fetchall()

    avg_rating = avg_row["avg_rating"] if avg_row else None
    return {
        "total": total,
        "by_source": by_source,
        "by_sentiment": by_sentiment,
        "by_theme": by_theme,
        "avg_rating": float(avg_rating) if avg_rating is not None else None,
        "rated_count": int(avg_row["rated_count"] or 0) if avg_row else 0,
        "last_update": last_row["last_update"] if last_row else None,
        "last_run": dict(last_run) if last_run else None,
        "top_complaints": [{"theme": r["theme"], "count": r["c"]} for r in complaints],
    }


def get_pm_insights(
    db_path: Path | None = None,
    limit: int = 2000,
    reviews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Aggregated Product Manager insights from advanced analysis fields.

    Pass `reviews` to aggregate a pre-filtered set (historical / live / combined).
    """
    reviews = reviews if reviews is not None else fetch_all_reviews(limit=limit, db_path=db_path)
    analyzed = [
        r
        for r in reviews
        if r.get("theme") or r.get("pain_point") or r.get("product_opportunity")
    ]

    pain_counter: Counter = Counter()
    theme_counter: Counter = Counter()
    barrier_counter: Counter = Counter()
    segment_counter: Counter = Counter()
    opportunity_counter: Counter = Counter()
    exploration_segments: Counter = Counter()
    root_cause_counter: Counter = Counter()
    category_counter: Counter = Counter()
    habit_counter: Counter = Counter()

    barrier_examples: dict[str, list[str]] = {}
    opportunity_examples: dict[str, dict[str, Any]] = {}
    ratings: list[float] = []

    for r in reviews:
        rating = r.get("rating")
        if rating is not None:
            try:
                ratings.append(float(rating))
            except (TypeError, ValueError):
                pass

    for r in analyzed:
        theme = (r.get("theme") or "").strip()
        pain = (r.get("pain_point") or "").strip()
        segment = (r.get("customer_segment") or "").strip()
        opportunity = (r.get("product_opportunity") or "").strip()
        root = (r.get("root_cause") or "").strip()
        category = (r.get("category") or "").strip()
        summary = (r.get("review_summary") or r.get("text") or "")[:140]

        if theme:
            theme_counter[theme] += 1
        if pain:
            # Normalize short pains for aggregation
            pain_key = pain[:90]
            pain_counter[pain_key] += 1
        if segment:
            segment_counter[segment] += 1
        if root:
            root_cause_counter[root[:100]] += 1
        if category and category.lower() not in {"app_review", "general", ""}:
            category_counter[category] += 1
        if theme == "Habitual buying" or segment in {
            "Habitual grocery buyer",
            "Frequent buyers",
        }:
            habit_key = segment or theme or "Habitual shopping"
            habit_counter[habit_key] += 1
        if opportunity:
            opportunity_counter[opportunity[:120]] += 1
            if opportunity[:120] not in opportunity_examples:
                opportunity_examples[opportunity[:120]] = {
                    "opportunity": opportunity,
                    "theme": theme,
                    "segment": segment,
                    "example": summary,
                    "count": 0,
                }
            opportunity_examples[opportunity[:120]]["count"] += 1

        if theme in EXPLORATION_BARRIER_THEMES:
            barrier_counter[theme] += 1
            barrier_examples.setdefault(theme, [])
            if summary and len(barrier_examples[theme]) < 3:
                barrier_examples[theme].append(summary)

        # Segments most likely to explore new categories if barriers are removed
        if segment in {
            "New category explorer",
            "Habitual grocery buyer",
            "Comparison shopper",
            "Convenience seeker",
            "Frequent buyers",
            "Impulse shoppers",
            "Occasional buyers",
            "Convenience-first users",
            "Health-conscious users",
        } or theme in EXPLORATION_BARRIER_THEMES:
            if segment:
                exploration_segments[segment] += 1

    top_opportunities = sorted(
        opportunity_examples.values(),
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    top_problems = _top_n(pain_counter, 10)
    top_themes = _top_n(theme_counter, 12)
    top_roots = _top_n(root_cause_counter, 8)
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    # Lightweight AI-style executive summary from aggregated signals
    problem_bits = ", ".join(p["label"] for p in top_problems[:3]) or "mixed feedback"
    theme_bits = ", ".join(t["label"] for t in top_themes[:3]) or "general themes"
    root_bits = ", ".join(r["label"] for r in top_roots[:2]) or "unspecified causes"
    ai_summary = (
        f"Across {len(reviews):,} reviews"
        + (f" (avg ⭐ {avg_rating})" if avg_rating is not None else "")
        + f", top pain points are {problem_bits}. "
        f"Dominant themes: {theme_bits}. "
        f"Likely root causes: {root_bits}. "
        f"{len(analyzed):,} reviews have structured AI analysis ready for the PM chatbot."
    )

    return {
        "analyzed_count": len(analyzed),
        "total_reviews": len(reviews),
        "avg_rating": avg_rating,
        "top_customer_problems": top_problems,
        "most_frequent_themes": top_themes,
        "shopping_habits": _top_n(habit_counter, 8),
        "product_categories": _top_n(category_counter, 10),
        "root_causes": top_roots,
        "ai_summary": ai_summary,
        "category_exploration_barriers": [
            {
                "barrier": item["label"],
                "count": item["count"],
                "examples": barrier_examples.get(item["label"], []),
            }
            for item in _top_n(barrier_counter, 8)
        ],
        "exploration_potential_segments": _top_n(exploration_segments, 8),
        "all_segments": _top_n(segment_counter, 10),
        "recommended_product_opportunities": top_opportunities,
    }


def start_pipeline_run(db_path: Path | None = None) -> int:
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pipeline_runs (started_at, status)
            VALUES (?, 'running')
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        return int(cur.lastrowid)


def finish_pipeline_run(
    run_id: int,
    status: str,
    counts: dict[str, int] | None = None,
    error_message: str | None = None,
    db_path: Path | None = None,
) -> None:
    counts = counts or {}
    with get_connection(db_path) as conn:
        run_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(pipeline_runs)").fetchall()
        }
        if "appstore_count" not in run_cols:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN appstore_count INTEGER DEFAULT 0"
            )
            run_cols.add("appstore_count")
        if "manual_count" not in run_cols:
            conn.execute(
                "ALTER TABLE pipeline_runs ADD COLUMN manual_count INTEGER DEFAULT 0"
            )
            run_cols.add("manual_count")

        sql = """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?,
                playstore_count = ?, appstore_count = ?, manual_count = ?,
                twitter_count = ?, new_reviews = ?, analyzed_count = ?,
                embedded_count = ?, error_message = ?
            WHERE id = ?
        """
        params: list[Any] = [
            datetime.now(timezone.utc).isoformat(),
            status,
            counts.get("playstore_count", 0),
            counts.get("appstore_count", 0),
            counts.get("manual_count", 0),
            counts.get("twitter_count", 0),
            counts.get("new_reviews", 0),
            counts.get("analyzed_count", 0),
            counts.get("embedded_count", 0),
            error_message,
            run_id,
        ]
        conn.execute(sql, tuple(params))
        # Zero legacy reddit_count on older databases
        if "reddit_count" in run_cols:
            conn.execute(
                "UPDATE pipeline_runs SET reddit_count = 0 WHERE id = ?",
                (run_id,),
            )


def clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.replace("\u0000", " ").split())
    return cleaned.strip()


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fetch_reviews_filtered(
    *,
    data_source: str = "combined",
    date_range: str = "all",
    platforms: list[str] | None = None,
    ratings: list[int] | None = None,
    sentiments: list[str] | None = None,
    live_window_days: int = 7,
    live_batch_keys: list[str] | None = None,
    limit: int | None = 5000,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Query the historical warehouse with optional live/historical split and filters.

    data_source:
      - historical → all rows already stored in SQLite
      - live → only reviews from the latest live fetch batch (content_hash)
      - combined → full warehouse (merged / deduped at ingest)
    """
    fetch_cap = None if limit is None else max(int(limit) * 20, 5000)
    rows = fetch_all_reviews(limit=fetch_cap, db_path=db_path)
    now = datetime.now(timezone.utc)

    range_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(
        str(date_range or "all").lower()
    )
    range_cutoff = None
    if range_days is not None:
        from datetime import timedelta

        range_cutoff = now - timedelta(days=range_days)

    from datetime import timedelta as _td

    live_cutoff = now - _td(days=max(1, int(live_window_days or 7)))

    batch_keys = {str(k) for k in (live_batch_keys or []) if k}
    if not batch_keys:
        try:
            from src.data_pipeline import load_live_batch_keys

            batch_keys = set(load_live_batch_keys())
        except Exception:
            batch_keys = set()

    platform_set = {str(p).lower() for p in (platforms or []) if p}
    rating_set = set()
    for r in ratings or []:
        try:
            rating_set.add(int(float(r)))
        except (TypeError, ValueError):
            continue
    sentiment_set = {str(s).strip().title() for s in (sentiments or []) if s}

    mode = str(data_source or "combined").lower()
    out: list[dict[str, Any]] = []
    for row in rows:
        event_dt = (
            _parse_iso(row.get("date"))
            or _parse_iso(row.get("fetched_at"))
            or _parse_iso(row.get("created_at"))
        )
        chash = str(row.get("content_hash") or "")
        in_live_batch = bool(chash and chash in batch_keys)
        is_live = in_live_batch or bool(event_dt and event_dt >= live_cutoff)

        if mode == "live":
            if batch_keys:
                if not in_live_batch:
                    continue
            elif not (event_dt and event_dt >= live_cutoff):
                continue
        # historical + combined → keep all stored rows (subject to other filters)

        if range_cutoff is not None:
            if not event_dt or event_dt < range_cutoff:
                continue

        src = str(row.get("source") or "").lower()
        if platform_set and src not in platform_set:
            continue

        if rating_set:
            try:
                stars = int(round(float(row.get("rating"))))
            except (TypeError, ValueError):
                continue
            if stars not in rating_set:
                continue

        if sentiment_set:
            sent = str(row.get("sentiment") or "").strip().title()
            if sent not in sentiment_set:
                continue

        enriched = dict(row)
        enriched["review_id"] = row.get("external_id") or row.get("id")
        enriched["review_text"] = row.get("text")
        enriched["review_date"] = row.get("date")
        enriched["version"] = row.get("app_version")
        enriched["is_live"] = is_live
        out.append(enriched)
    if limit is not None:
        return out[: int(limit)]
    return out


def get_review_warehouse_stats(
    db_path: Path | None = None,
    *,
    live_window_days: int = 7,
) -> dict[str, Any]:
    """KPIs for Historical / Live / Merged warehouse dashboard."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    live_cutoff = now - timedelta(days=max(1, int(live_window_days or 7)))
    today_cutoff = now - timedelta(days=1)
    week_cutoff = now - timedelta(days=7)

    rows = fetch_all_reviews(limit=None, db_path=db_path)
    live = 0
    new_today = 0
    new_week = 0
    latest_review: datetime | None = None
    last_sync: datetime | None = None

    for row in rows:
        event_dt = (
            _parse_iso(row.get("date"))
            or _parse_iso(row.get("fetched_at"))
            or _parse_iso(row.get("created_at"))
        )
        fetched = (
            _parse_iso(row.get("fetched_at"))
            or _parse_iso(row.get("created_at"))
            or _parse_iso(row.get("updated_at"))
        )
        if event_dt and event_dt >= live_cutoff:
            live += 1
        if fetched and fetched >= today_cutoff:
            new_today += 1
        if fetched and fetched >= week_cutoff:
            new_week += 1
        if event_dt and (latest_review is None or event_dt > latest_review):
            latest_review = event_dt
        if fetched and (last_sync is None or fetched > last_sync):
            last_sync = fetched

    # Prefer pipeline / live meta timestamp when available
    try:
        from src.data_pipeline import get_live_meta

        meta_ts = _parse_iso((get_live_meta() or {}).get("last_updated"))
        if meta_ts:
            last_sync = meta_ts
    except Exception:
        pass

    total = len(rows)
    older = max(0, total - live)
    return {
        "total_historical": total,  # full warehouse (never deleted)
        "total_live": live,
        "older_reviews": older,
        "merged_reviews": total,
        "new_reviews_today": new_today,
        "new_reviews_this_week": new_week,
        "last_sync_time": last_sync.isoformat() if last_sync else None,
        "latest_review_date": latest_review.isoformat() if latest_review else None,
        "live_window_days": live_window_days,
    }
