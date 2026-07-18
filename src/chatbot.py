"""AI Product Manager chatbot — SQLite/Pandas retrieval + Gemini synthesis."""

from __future__ import annotations

import logging
import re
from typing import Any

from src.gemini_analysis import generate_pm_answer
from src.rag_pipeline import collection_stats, retrieve_relevant

logger = logging.getLogger(__name__)

SYSTEM_INTRO = (
    "I'm your Zepto AI Product Manager research assistant. "
    "I read the latest fetched reviews from feedback.db, filter relevant feedback, "
    "and use Gemini to surface customer problems, root causes, and product opportunities."
)

EXAMPLE_QUESTIONS = [
    "Show me latest reviews",
    "What are users saying today?",
    "Why are Zepto users not trying personal care products?",
    "What are the top delivery experience complaints this month?",
    "What pricing concerns appear most often?",
]

_LIVE_REVIEW_PATTERNS = [
    r"\blatest reviews?\b",
    r"\blive reviews?\b",
    r"\bshow me latest\b",
    r"\bshow live reviews?\b",
    r"\busers? saying today\b",
    r"\bwhat are users saying\b",
    r"\brecent reviews?\b",
    r"\btoday'?s reviews?\b",
]


def _is_live_review_question(question: str) -> bool:
    q = (question or "").lower()
    return any(re.search(pat, q) for pat in _LIVE_REVIEW_PATTERNS)


def _summarize_latest_reviews(n: int = 10) -> dict[str, Any]:
    """Return a factual summary of newest reviews in the local DB (never invents)."""
    from src.config import LIVE_CHAT_SOURCES
    from src.data_pipeline import get_live_meta, live_data_is_fresh
    from src.database import fetch_all_reviews

    def _fmt(ts: str | None) -> str:
        if not ts:
            return "Never"
        return str(ts).replace("T", " ")[:19] + " UTC"

    if not live_data_is_fresh():
        return {
            "answer": (
                "Live review data is missing or outdated. "
                "Please click **🔄 Refresh Live Reviews** to download the latest reviews, "
                "then ask again."
            ),
            "evidence": [],
            "retrieved": 0,
            "knowledge_base": collection_stats(),
        }

    reviews = fetch_all_reviews(limit=400)
    allowed = {s.lower() for s in LIVE_CHAT_SOURCES}
    live_rows = [
        r
        for r in reviews
        if str(r.get("source") or "").lower() in allowed and (r.get("text") or "").strip()
    ]
    # Newest first
    live_rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    latest = live_rows[:n]

    if not latest:
        return {
            "answer": (
                "No fetched reviews are available in the local database yet. "
                "Please click **🔄 Refresh Live Reviews** to download the latest reviews."
            ),
            "evidence": [],
            "retrieved": 0,
            "knowledge_base": collection_stats(),
        }

    meta = get_live_meta()
    evidence = [
        {
            "text": e.get("text") or "",
            "source": e.get("source"),
            "sentiment": e.get("sentiment"),
            "theme": e.get("theme"),
            "user_intent": e.get("user_intent"),
            "customer_segment": e.get("customer_segment"),
            "review_summary": e.get("review_summary"),
            "pain_point": e.get("pain_point"),
            "root_cause": e.get("root_cause"),
            "product_opportunity": e.get("product_opportunity"),
            "date": e.get("date"),
            "rating": e.get("rating"),
        }
        for e in latest
    ]

    question = (
        "Summarize what Zepto users are saying in these latest fetched reviews. "
        "Use only the provided evidence. Do not invent reviews. "
        f"Data last updated: {_fmt(meta.get('last_updated'))}."
    )
    answer = generate_pm_answer(question, evidence)
    header = (
        f"**Latest fetched reviews** (Last Updated: {_fmt(meta.get('last_updated'))} · "
        f"showing {len(evidence)} of {len(live_rows)} available)\n\n"
    )
    return {
        "answer": header + answer,
        "evidence": evidence[:5],
        "retrieved": len(evidence),
        "knowledge_base": collection_stats(),
    }


def ask_product_manager(
    question: str,
    n_evidence: int = 8,
) -> dict[str, Any]:
    """
    PM research loop:

    question → filter reviews in feedback.db → Gemini analysis → insight brief
    """
    question = (question or "").strip()
    if not question:
        return {
            "answer": "Please ask a product research question.",
            "evidence": [],
            "retrieved": 0,
        }

    if _is_live_review_question(question):
        return _summarize_latest_reviews(n=max(n_evidence, 10))

    from src.config import LIVE_CHAT_SOURCES
    from src.data_pipeline import live_data_is_fresh

    if not live_data_is_fresh() and collection_stats().get("count", 0) == 0:
        return {
            "answer": (
                "No live review data is available yet. "
                "Please click **🔄 Refresh Live Reviews** to download the latest reviews."
            ),
            "evidence": [],
            "retrieved": 0,
            "knowledge_base": collection_stats(),
        }

    evidence = retrieve_relevant(
        question,
        n_results=n_evidence,
        sources=LIVE_CHAT_SOURCES,
    )
    normalized = [
        {
            "text": e.get("text") or "",
            "source": e.get("source"),
            "sentiment": e.get("sentiment"),
            "theme": e.get("theme"),
            "user_intent": e.get("user_intent"),
            "customer_segment": e.get("customer_segment"),
            "review_summary": e.get("review_summary"),
            "pain_point": e.get("pain_point"),
            "root_cause": e.get("root_cause"),
            "product_opportunity": e.get("product_opportunity"),
            "date": e.get("date"),
        }
        for e in evidence
    ]

    if not normalized:
        return {
            "answer": (
                "I couldn't find matching reviews in the local fetched dataset. "
                "Please click **🔄 Refresh Live Reviews** to download the latest reviews, "
                "or try a different question."
            ),
            "evidence": [],
            "retrieved": 0,
            "knowledge_base": collection_stats(),
        }

    answer = generate_pm_answer(question, normalized)
    return {
        "answer": answer,
        "evidence": normalized[:5],
        "retrieved": len(normalized),
        "knowledge_base": collection_stats(),
    }


def chat(question: str) -> str:
    """Convenience wrapper returning markdown answer only."""
    return ask_product_manager(question)["answer"]
