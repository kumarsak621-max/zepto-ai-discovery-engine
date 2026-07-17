"""
Lightweight review retrieval for the PM chatbot.

Reads directly from feedback.db (SQLite) via Pandas — no vector DB, no embeddings.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

from src.database import fetch_all_reviews, get_connection

logger = logging.getLogger(__name__)

# Stopwords kept tiny on purpose — reviews are short product feedback
_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "shall",
    "can",
    "need",
    "dare",
    "ought",
    "used",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "i",
    "me",
    "my",
    "we",
    "our",
    "you",
    "your",
    "they",
    "them",
    "their",
    "what",
    "which",
    "who",
    "whom",
    "how",
    "why",
    "when",
    "where",
    "with",
    "from",
    "about",
    "into",
    "over",
    "after",
    "before",
    "between",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "all",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "also",
    "zepto",  # brand always present — low signal alone
    "app",
    "users",
    "user",
    "customer",
    "customers",
    "please",
    "really",
}

# Expand common PM research phrases into retrieval keywords
_QUERY_SYNONYMS: dict[str, list[str]] = {
    "personal care": [
        "personal care",
        "beauty",
        "shampoo",
        "skincare",
        "face wash",
        "cosmetics",
    ],
    "delivery": ["delivery", "rider", "eta", "late", "minutes", "arrived"],
    "pricing": ["price", "pricing", "expensive", "costly", "mrp", "discount", "fee"],
    "trust": ["trust", "quality", "expired", "fake", "hygiene", "dirty", "seal"],
    "discovery": ["discover", "discovery", "find", "search", "browse", "explore"],
    "awareness": ["noticed", "aware", "awareness", "didn't know", "never noticed"],
    "pet": ["pet", "dog", "cat", "litter", "pet food"],
    "baby": ["baby", "diaper", "wipes", "formula", "infant"],
    "blinkit": ["blinkit", "instamart", "swiggy", "comparison", "vs"],
    "recommendation": ["recommend", "recommendation", "suggestions", "suggested"],
    "grocery": ["grocery", "groceries", "milk", "vegetables", "reorder"],
    "habit": ["habit", "habitual", "always reorder", "same items", "regular"],
}


def _tokenize(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9']+", (text or "").lower())
        if len(t) > 2 and t not in _STOPWORDS
    ]


def _expand_query_terms(question: str) -> list[str]:
    q = (question or "").lower()
    terms: list[str] = []
    for phrase, syns in _QUERY_SYNONYMS.items():
        if phrase in q or any(s in q for s in syns[:2]):
            terms.extend(syns)
    terms.extend(_tokenize(question))
    # Preserve order, drop dupes
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load_reviews_dataframe(limit: int = 5000) -> pd.DataFrame:
    """Load reviews from feedback.db into a Pandas DataFrame."""
    rows = fetch_all_reviews(limit=limit)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _score_row(blob: str, terms: list[str]) -> float:
    if not blob or not terms:
        return 0.0
    score = 0.0
    for term in terms:
        if " " in term:
            if term in blob:
                score += 3.0
        elif term in blob:
            score += 1.0
            # slight boost for word-boundary-ish hits
            if re.search(rf"\b{re.escape(term)}\b", blob):
                score += 0.5
    return score


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def retrieve_relevant(
    query: str,
    n_results: int = 8,
    where: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Keyword + SQL-friendly retrieval over feedback.db.

    1. Optional SQL filters (sentiment / theme / source / category)
    2. Pandas keyword scoring across review text + AI analysis fields
    3. Return top-N rows for Gemini PM synthesis
    """
    query = (query or "").strip()
    if not query:
        return []

    terms = _expand_query_terms(query)
    df = load_reviews_dataframe()
    if df.empty:
        logger.info("No reviews in feedback.db for retrieval")
        return []

    # Optional structured filters from caller
    if where:
        for key, value in where.items():
            if key in df.columns and value is not None:
                df = df[df[key].astype(str).str.lower() == str(value).lower()]

    # Fast SQL prefilter when we have strong theme keywords
    theme_hints = []
    q_lower = query.lower()
    theme_map = {
        "delivery": "Delivery experience",
        "price": "Pricing concern",
        "pricing": "Pricing concern",
        "trust": "Trust issue",
        "discover": "Product discovery issue",
        "awareness": "Category awareness",
        "personal care": "Personal Care Category",
        "search": "Product Search Experience",
        "recommend": "Recommendations Quality",
        "pet": "Pet Supplies",
        "baby": "Baby Products",
    }
    for needle, theme in theme_map.items():
        if needle in q_lower:
            theme_hints.append(theme)

    if theme_hints and "theme" in df.columns:
        themed = df[df["theme"].isin(theme_hints)]
        # Prefer themed rows but keep others if themed set is tiny
        if len(themed) >= max(3, n_results // 2):
            df = pd.concat([themed, df]).drop_duplicates(subset=["id"], keep="first")

    text_cols = [
        c
        for c in (
            "text",
            "review_summary",
            "pain_point",
            "root_cause",
            "theme",
            "category",
            "customer_segment",
            "product_opportunity",
            "user_intent",
            "title",
        )
        if c in df.columns
    ]

    blobs = (
        df[text_cols]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )
    scores = blobs.map(lambda b: _score_row(b, terms))
    df = df.assign(_score=scores)

    ranked = df[df["_score"] > 0].sort_values(
        by=["_score", "date", "id"],
        ascending=[False, False, False],
        na_position="last",
    )

    # If nothing matched keywords, return recent analyzed negatives / complaints
    if ranked.empty:
        fallback = df.copy()
        if "user_intent" in fallback.columns:
            complaints = fallback[fallback["user_intent"] == "Complaint"]
            if not complaints.empty:
                fallback = complaints
        ranked = fallback.sort_values(
            by=["date", "id"], ascending=[False, False], na_position="last"
        )

    top = ranked.head(n_results)
    results: list[dict[str, Any]] = []
    for _, row in top.iterrows():
        rid = row.get("id")
        try:
            rid_int = int(rid) if pd.notna(rid) else None
        except (TypeError, ValueError):
            rid_int = None
        results.append(
            {
                "id": rid_int,
                "db_id": str(rid_int) if rid_int is not None else None,
                "text": _safe_str(row.get("text")),
                "source": _safe_str(row.get("source")) or None,
                "sentiment": _safe_str(row.get("sentiment")) or None,
                "theme": _safe_str(row.get("theme")) or None,
                "user_intent": _safe_str(row.get("user_intent")) or None,
                "customer_segment": _safe_str(row.get("customer_segment")) or None,
                "review_summary": _safe_str(row.get("review_summary")) or None,
                "pain_point": _safe_str(row.get("pain_point")) or None,
                "root_cause": _safe_str(row.get("root_cause")) or None,
                "product_opportunity": _safe_str(row.get("product_opportunity")) or None,
                "category": _safe_str(row.get("category")) or None,
                "date": _safe_str(row.get("date")) or None,
                "rating": row.get("rating") if pd.notna(row.get("rating")) else None,
                "score": float(row.get("_score") or 0),
            }
        )
    return results


def collection_stats() -> dict[str, Any]:
    """Knowledge-base stats for the dashboard (SQLite-backed)."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()["c"]
        analyzed = conn.execute(
            """
            SELECT COUNT(*) AS c FROM reviews
            WHERE analyzed = 1
               OR (theme IS NOT NULL AND theme != '')
            """
        ).fetchone()["c"]
    return {
        "count": total,
        "analyzed": analyzed,
        "name": "feedback.db",
        "backend": "sqlite",
    }


def search_reviews_sql(
    keyword: str,
    limit: int = 50,
    sentiment: str | None = None,
    theme: str | None = None,
) -> list[dict[str, Any]]:
    """Direct SQL LIKE search — useful for dashboards and debugging."""
    clauses = ["(text LIKE ? OR review_summary LIKE ? OR pain_point LIKE ? OR theme LIKE ?)"]
    pattern = f"%{keyword}%"
    params: list[Any] = [pattern, pattern, pattern, pattern]
    if sentiment:
        clauses.append("sentiment = ?")
        params.append(sentiment)
    if theme:
        clauses.append("theme = ?")
        params.append(theme)
    where = " AND ".join(clauses)
    params.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM reviews
            WHERE {where}
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]
