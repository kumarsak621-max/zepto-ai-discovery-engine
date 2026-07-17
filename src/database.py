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
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    playstore_count INTEGER DEFAULT 0,
    reddit_count INTEGER DEFAULT 0,
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


def init_db(db_path: Path | None = None) -> Path:
    path = Path(db_path or DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_schema(conn)
    return path


def upsert_review(review: dict[str, Any], db_path: Path | None = None) -> bool:
    """Insert a review if it is not a duplicate. Returns True if inserted."""
    text = (review.get("text") or "").strip()
    if not text:
        return False

    source = review.get("source", "unknown")
    external_id = review.get("external_id")
    chash = review.get("content_hash") or content_hash(text, source, external_id)

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
        "date": review.get("date"),
        "category": review.get("category"),
        "sentiment": review.get("sentiment"),
        "theme": review.get("theme"),
        "user_intent": review.get("user_intent"),
        "review_summary": review.get("review_summary"),
        "customer_segment": review.get("customer_segment"),
        "pain_point": review.get("pain_point"),
        "root_cause": review.get("root_cause"),
        "product_opportunity": review.get("product_opportunity"),
        "app_version": review.get("app_version"),
        "title": review.get("title"),
        "upvotes": review.get("upvotes"),
        "external_id": external_id,
        "content_hash": chash,
        "analyzed": 1 if fully_analyzed else 0,
        "embedded": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    with get_connection(db_path) as conn:
        try:
            conn.execute(
                """
                INSERT INTO reviews (
                    source, text, rating, date, category, sentiment, theme,
                    user_intent, review_summary, customer_segment, pain_point,
                    root_cause, product_opportunity, app_version, title, upvotes,
                    external_id, content_hash, analyzed, embedded, updated_at
                ) VALUES (
                    :source, :text, :rating, :date, :category, :sentiment, :theme,
                    :user_intent, :review_summary, :customer_segment, :pain_point,
                    :root_cause, :product_opportunity, :app_version, :title, :upvotes,
                    :external_id, :content_hash, :analyzed, :embedded, :updated_at
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


def get_pm_insights(db_path: Path | None = None, limit: int = 2000) -> dict[str, Any]:
    """
    Aggregated Product Manager insights from advanced analysis fields:

    - Top customer problems (pain points)
    - Most frequent themes
    - Category exploration barriers
    - User segments with highest exploration potential
    - Recommended product opportunities
    """
    reviews = fetch_all_reviews(limit=limit, db_path=db_path)
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
        if theme == "Habitual buying" or segment == "Habitual grocery buyer":
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
        conn.execute(
            """
            UPDATE pipeline_runs
            SET finished_at = ?, status = ?,
                playstore_count = ?, reddit_count = ?, twitter_count = ?,
                new_reviews = ?, analyzed_count = ?, embedded_count = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                status,
                counts.get("playstore_count", 0),
                counts.get("reddit_count", 0),
                counts.get("twitter_count", 0),
                counts.get("new_reviews", 0),
                counts.get("analyzed_count", 0),
                counts.get("embedded_count", 0),
                error_message,
                run_id,
            ),
        )


def clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.replace("\u0000", " ").split())
    return cleaned.strip()
