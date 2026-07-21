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
    "Why do users keep buying the same categories?",
    "What are the top category discovery barriers?",
    "Which growth opportunities should we prioritize?",
    "What pricing concerns appear most often?",
]

_INSIGHT_PATTERNS = [
    r"\broot cause",
    r"\bwhy (do|are) users?\b",
    r"\bsame categor",
    r"\bdiscovery barrier",
    r"\bgrowth (kpi|opportunit|recommend)",
    r"\buser segment",
    r"\bshopping habit",
    r"\bcategory exploration",
    r"\bcross[- ]?sell",
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


def _is_insight_question(question: str) -> bool:
    q = (question or "").lower()
    return any(re.search(pat, q) for pat in _INSIGHT_PATTERNS)


def _discovery_context_block() -> str:
    """Compact dashboard insights for chatbot grounding (uses disk/Streamlit cache)."""
    try:
        from src.streamlit_cache import cached_discovery_dashboard

        dash = cached_discovery_dashboard(limit=2000)
    except Exception:
        try:
            from src.discovery_insights import build_discovery_dashboard

            dash = build_discovery_dashboard(limit=800)
        except Exception:
            return ""

    discovery = dash.get("discovery") or {}
    rca = discovery.get("root_cause_analysis") or {}
    causes = [
        f"{c.get('root_cause')} (sev {c.get('severity_score')}/10, freq {c.get('frequency')})"
        for c in (rca.get("causes") or [])[:5]
    ]
    barriers = [
        f"{b.get('barrier')} [{b.get('severity')}]"
        for b in (discovery.get("discovery_barriers") or [])[:5]
    ]
    opps = [
        f"{o.get('current_category')} → {o.get('suggested_new_category')} "
        f"({o.get('confidence_score')}%)"
        for o in (discovery.get("category_exploration_opportunities") or [])[:4]
    ]
    recs = (discovery.get("growth_recommendations") or [])[:5]
    habits = (discovery.get("shopping_habit_insights") or [])[:4]
    segments = [
        f"{s.get('segment')} ({s.get('percentage')}%)"
        for s in (discovery.get("ai_user_segments") or [])[:5]
    ]
    kpis = discovery.get("growth_kpis") or {}
    lines = [
        "DASHBOARD INSIGHTS (use these; do not invent conflicting stats):",
        f"- Root causes: {'; '.join(causes) or 'n/a'}",
        f"- Barriers: {'; '.join(barriers) or 'n/a'}",
        f"- Category opportunities: {'; '.join(opps) or 'n/a'}",
        f"- Segments: {'; '.join(segments) or 'n/a'}",
        f"- Habits: {'; '.join(habits) or 'n/a'}",
        f"- Growth KPIs: {json_dumps_safe(kpis)}",
        f"- Growth recommendations: {'; '.join(recs) or 'n/a'}",
        f"- RCA summary: {(rca.get('summary') or '')[:600]}",
    ]
    return "\n".join(lines)


def json_dumps_safe(obj: Any) -> str:
    try:
        import json

        return json.dumps(obj, ensure_ascii=False)[:400]
    except Exception:
        return str(obj)[:400]


def _source_display(source: Any) -> str:
    key = str(source or "").strip().lower()
    if key in {"playstore", "google play", "google_play", "google play store", "play"}:
        return "Google Play Store"
    if key in {"appstore", "apple app store", "app_store", "ios", "apple", "apple store"}:
        return "Apple App Store"
    return str(source or "Unknown").replace("_", " ").title()


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
                "Reload the app to automatically collect the latest Google Play and "
                "App Store reviews, then ask again."
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
                "Reload the app to automatically collect reviews from Google Play "
                "and the App Store."
            ),
            "evidence": [],
            "retrieved": 0,
            "knowledge_base": collection_stats(),
        }

    meta = get_live_meta()
    evidence = [
        {
            "text": e.get("text") or "",
            "source": _source_display(e.get("source")),
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
                "Reload the app to automatically collect reviews from Google Play "
                "and the App Store."
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
            "source": _source_display(e.get("source")),
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
                "Reload the app to refresh automatic collection, or try a different question."
            ),
            "evidence": [],
            "retrieved": 0,
            "knowledge_base": collection_stats(),
        }

    dashboard_ctx = _discovery_context_block() if _is_insight_question(question) else ""
    answer = generate_pm_answer(
        question,
        normalized,
        dashboard_context=dashboard_ctx,
    )
    return {
        "answer": answer,
        "evidence": normalized[:5],
        "retrieved": len(normalized),
        "knowledge_base": collection_stats(),
    }


def chat(question: str) -> str:
    """Convenience wrapper returning markdown answer only."""
    return ask_product_manager(question)["answer"]
