"""AI Product Manager chatbot — SQLite/Pandas retrieval + Gemini synthesis."""

from __future__ import annotations

import logging
from typing import Any

from src.gemini_analysis import generate_pm_answer
from src.rag_pipeline import collection_stats, retrieve_relevant

logger = logging.getLogger(__name__)

SYSTEM_INTRO = (
    "I'm your Zepto AI Product Manager research assistant. "
    "I read the latest feedback from feedback.db, filter relevant reviews, "
    "and use Gemini to surface customer problems, root causes, and product opportunities."
)

EXAMPLE_QUESTIONS = [
    "Why are Zepto users not trying personal care products?",
    "What are the top delivery experience complaints this month?",
    "Where do customers compare Zepto vs Blinkit?",
    "What pricing concerns appear most often?",
    "Which themes show trust or quality issues?",
]


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

    evidence = retrieve_relevant(question, n_results=n_evidence)
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
