"""Gemini AI processing — advanced structured review analysis for PMs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.config import (
    CUSTOMER_SEGMENTS,
    INTENT_TAXONOMY,
    SENTIMENT_VALUES,
    THEME_TAXONOMY,
    has_gemini,
)

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a senior Product Manager research analyst for Zepto
(Indian quick commerce / 10-minute grocery delivery).

Analyze this customer feedback and return ONLY valid JSON with exactly these keys:

{{
  "review_summary": "1-2 sentence PM-ready summary of what the customer is saying",
  "sentiment": "MUST be exactly one of: Positive, Neutral, Negative",
  "theme": "one of: {themes}",
  "user_intent": "one of: {intents}",
  "customer_segment": "prefer one of: {segments}",
  "pain_point": "specific pain the customer feels (empty string if appreciation)",
  "root_cause": "likely underlying cause of the pain/behavior",
  "product_opportunity": "concrete product opportunity or experiment for Zepto",
  "category": "product/category mentioned (e.g. personal care, grocery, snacks, beverages) or general"
}}

Sentiment rules:
- Positive: praise, delight, loyalty, recommendations
- Negative: complaints, frustration, churn risk, quality/delivery failures
- Neutral: mixed, factual, mild, or unclear emotion

Focus on category exploration barriers when relevant (personal care, beauty, electronics,
non-grocery discovery, trust, recommendations, awareness).

Feedback:
\"\"\"{text}\"\"\"
"""

STRUCTURED_KEYS = (
    "review_summary",
    "sentiment",
    "theme",
    "user_intent",
    "customer_segment",
    "pain_point",
    "root_cause",
    "product_opportunity",
    "category",
)


def generate_gemini_text(prompt: str) -> str:
    """Generate text via multi-key Gemini manager (automatic failover)."""
    from src.gemini_key_manager import generate_with_failover

    return generate_with_failover(prompt)


def _extract_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _infer_segment(lower: str, theme: str, sentiment: str) -> str:
    rules = [
        ("Price-sensitive shoppers", ("price", "expensive", "costly", "discount", "mrp", "cheap")),
        ("Health-conscious users", ("organic", "healthy", "fresh", "hygiene", "quality", "expired")),
        ("Premium shoppers", ("premium", "branded", "best quality", "worth")),
        ("Convenience-first users", ("fast", "minutes", "late", "delivery", "eta", "quick", "convenient")),
        ("Frequent buyers", ("always", "regular", "everyday", "daily", "habit", "reorder")),
        ("Impulse shoppers", ("suddenly", "impulse", "craving", "tonight", "urgent")),
        ("Occasional buyers", ("sometimes", "occasionally", "first time", "rarely")),
    ]
    for segment, keywords in rules:
        if any(k in lower for k in keywords):
            return segment
    if theme == "Habitual buying":
        return "Frequent buyers"
    if theme == "Pricing concern":
        return "Price-sensitive shoppers"
    if theme in {"Trust issue", "Product quality"}:
        return "Health-conscious users"
    if theme in {"Product discovery issue", "Category awareness"}:
        return "Impulse shoppers"
    if sentiment == "Positive":
        return "Convenience-first users"
    return "Occasional buyers"


def _opportunity_for(theme: str, segment: str) -> str:
    mapping = {
        "Product discovery issue": "Improve in-app search + guided category discovery journeys",
        "Category awareness": "AI Personal Care / non-grocery Recommendation Journey with education cards",
        "Trust issue": "Trust signals: freshness badges, warehouse hygiene proof, quality SLA",
        "Pricing concern": "Transparent price comparison + loyalty pricing for habitual buyers",
        "Delivery experience": "ETA reliability score + proactive delay communication",
        "Habitual buying": "Smart replenishment + subscription for everyday grocery staples",
        "App usability": "Simplify checkout / login recovery and reduce friction steps",
        "Product quality": "Seller quality score + easy one-tap replacement flow",
        "Customer support": "In-app instant resolution for missing/damaged items",
    }
    base = mapping.get(theme, "Run a discovery interview sprint on this theme and ship a targeted experiment")
    if segment in {"New category explorer", "Impulse shoppers", "Occasional buyers"}:
        return "AI-assisted category exploration with personalized recommendations and try-before-you-buy kits"
    return base


def _fallback_analysis(text: str, rating: float | None = None) -> dict[str, str]:
    """Rule-based structured analysis when Gemini is unavailable."""
    lower = (text or "").lower()

    if rating is not None:
        if rating >= 4:
            sentiment = "Positive"
        elif rating <= 2:
            sentiment = "Negative"
        else:
            sentiment = "Neutral"
    elif any(w in lower for w in ("love", "great", "awesome", "excellent", "fast")):
        sentiment = "Positive"
    elif any(
        w in lower
        for w in ("bad", "worst", "delay", "refund", "scam", "hate", "broken", "dirty")
    ):
        sentiment = "Negative"
    else:
        sentiment = "Neutral"

    theme = "Other"
    theme_rules = [
        ("Product discovery issue", ("can't find", "hard to find", "search", "discover", "not showing")),
        ("Category awareness", ("personal care", "beauty", "don't know", "aware", "which product")),
        ("Trust issue", ("trust", "fake", "expired", "quality", "hygiene", "dirty", "fungus")),
        ("Pricing concern", ("price", "expensive", "costly", "discount", "mrp", "cheating")),
        ("Delivery experience", ("delivery", "late", "rider", "eta", "arrived", "minutes")),
        ("Habitual buying", ("always order", "regular", "habit", "everyday", "daily")),
        ("App usability", ("app", "bug", "crash", "ui", "login", "option")),
        ("Product quality", ("spoiled", "damaged", "fresh", "packaging", "empty packet")),
        ("Customer support", ("support", "refund", "customer care", "helpline")),
    ]
    for label, keywords in theme_rules:
        if any(k in lower for k in keywords):
            theme = label
            break

    if sentiment == "Positive" or any(
        w in lower for w in ("thanks", "love", "great", "awesome")
    ):
        intent = "Appreciation"
    elif "?" in (text or "") or any(w in lower for w in ("why", "how", "when", "what")):
        intent = "Question"
    elif any(w in lower for w in ("should", "please add", "wish", "suggest", "hope")):
        intent = "Suggestion"
    else:
        intent = "Complaint" if sentiment == "Negative" else "Suggestion"

    segment = _infer_segment(lower, theme, sentiment)
    summary = (text or "")[:180]
    if sentiment == "Positive" and intent == "Appreciation":
        pain = ""
        root = "Strong delivery / convenience expectation being met"
        opportunity = "Amplify delight moments and convert promoters into category explorers"
    else:
        pain = summary if summary else f"{theme} friction"
        root = {
            "Product discovery issue": "Low findability and weak guided discovery",
            "Category awareness": "Users lack confidence / awareness beyond staple grocery",
            "Trust issue": "Low confidence in freshness, hygiene, or authenticity",
            "Pricing concern": "Perceived price opacity or competitive disadvantage",
            "Delivery experience": "ETA promises not consistently met",
            "App usability": "UX friction blocking intended action",
            "Product quality": "Fulfillment / warehouse quality gaps",
            "Customer support": "Slow or opaque issue resolution",
            "Habitual buying": "Routine use without expanding basket",
        }.get(theme, "Unresolved customer friction in the shopping journey")
        opportunity = _opportunity_for(theme, segment)

    category = "general"
    for cat, keys in (
        ("personal care", ("shampoo", "personal care", "beauty", "skincare")),
        ("grocery", ("grocery", "vegetable", "fruit", "milk", "egg")),
        ("delivery", ("delivery", "rider", "eta")),
        ("pricing", ("price", "mrp", "discount")),
    ):
        if any(k in lower for k in keys):
            category = cat
            break

    return {
        "review_summary": summary or "Insufficient text to summarize",
        "sentiment": sentiment,
        "theme": theme,
        "user_intent": intent,
        "customer_segment": segment,
        "pain_point": pain,
        "root_cause": root,
        "product_opportunity": opportunity,
        "category": category,
    }


def _normalize(data: dict[str, Any], text: str) -> dict[str, str]:
    sentiment = data.get("sentiment", "Neutral")
    theme = data.get("theme", "Other")
    intent = data.get("user_intent", "Suggestion")
    segment = data.get("customer_segment", "General shopper")

    if sentiment not in SENTIMENT_VALUES:
        sentiment = "Neutral"
    if theme not in THEME_TAXONOMY:
        theme = "Other"
    if intent not in INTENT_TAXONOMY:
        intent = "Suggestion"
    if segment not in CUSTOMER_SEGMENTS:
        # Keep free-text segment if Gemini invents a useful label, else fallback
        segment = str(segment or "General shopper")[:80]

    return {
        "review_summary": str(data.get("review_summary") or data.get("summary") or text[:180])[:400],
        "sentiment": sentiment,
        "theme": theme,
        "user_intent": intent,
        "customer_segment": segment,
        "pain_point": str(data.get("pain_point") or "")[:400],
        "root_cause": str(data.get("root_cause") or "")[:400],
        "product_opportunity": str(data.get("product_opportunity") or "")[:400],
        "category": str(data.get("category") or "general")[:80],
    }


def analyze_review(
    text: str,
    rating: float | None = None,
    use_fallback_on_error: bool = True,
) -> dict[str, str]:
    """
    Analyze a single review into the advanced structured PM schema:

    review_summary, sentiment, theme, user_intent, customer_segment,
    pain_point, root_cause, product_opportunity (+ category)
    """
    if not text or not text.strip():
        return _fallback_analysis("", rating)

    if not has_gemini():
        return _fallback_analysis(text, rating)

    prompt = ANALYSIS_PROMPT.format(
        sentiments=", ".join(SENTIMENT_VALUES),
        themes=", ".join(THEME_TAXONOMY),
        intents=", ".join(INTENT_TAXONOMY),
        segments=", ".join(CUSTOMER_SEGMENTS),
        text=text[:3000],
    )

    try:
        raw = generate_gemini_text(prompt)
        data = _extract_json(raw or "")
        return _normalize(data, text)
    except Exception as exc:
        logger.warning("Gemini analysis failed: %s", exc)
        if use_fallback_on_error:
            return _fallback_analysis(text, rating)
        raise


def analyze_batch(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for review in reviews:
        analysis = analyze_review(review.get("text", ""), rating=review.get("rating"))
        results.append({**review, **analysis})
    return results


def generate_pm_answer(
    question: str,
    evidence: list[dict[str, Any]],
    *,
    dashboard_context: str = "",
) -> str:
    """Generate a structured Product Manager research answer from retrieved reviews."""

    def _s(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            try:
                import math

                if math.isnan(value):
                    return ""
            except Exception:
                pass
        return str(value)

    evidence_block = "\n".join(
        [
            f"- [{_s(e.get('source')) or '?'}|{_s(e.get('sentiment')) or '?'}|{_s(e.get('theme')) or '?'}"
            f"|{_s(e.get('customer_segment')) or '?'}] "
            f"pain={_s(e.get('pain_point')) or 'n/a'} | "
            f"root={_s(e.get('root_cause')) or 'n/a'} | "
            f"{(_s(e.get('review_summary')) or _s(e.get('text')))[:220]}"
            for e in evidence[:8]
        ]
    ) or "- No matching reviews found."

    context_block = (
        f"\n\nPre-computed AI Discovery dashboard insights:\n{dashboard_context}\n"
        if dashboard_context
        else ""
    )

    if not has_gemini():
        quotes = "\n".join(
            f'{i}. "{(_s(e.get("text")) or _s(e.get("review_summary")))[:180]}"'
            for i, e in enumerate(evidence[:5], 1)
        ) or "1. No matching customer comments available yet."
        themes = ", ".join(
            sorted({_s(e.get("theme")) for e in evidence if _s(e.get("theme"))})
        ) or "Insufficient data"
        opportunities = [
            _s(e.get("product_opportunity"))
            for e in evidence
            if _s(e.get("product_opportunity"))
        ]
        opportunity = opportunities[0] if opportunities else (
            "Validate these themes with a discovery sprint and design a targeted journey experiment."
        )
        roots = [_s(e.get("root_cause")) for e in evidence if _s(e.get("root_cause"))]
        root = roots[0] if roots else f"Emerging themes: {themes}."
        extra = f"\n\n### Dashboard Context\n{dashboard_context}\n" if dashboard_context else ""
        return (
            f"### Customer Insight\n"
            f"Based on {len(evidence)} retrieved feedback items related to your question.\n\n"
            f"### Evidence\n{quotes}\n\n"
            f"### Root Cause\n{root}\n\n"
            f"### Product Opportunity\n{opportunity}\n"
            f"{extra}"
            f"\n_Note: Configure GEMINI_API_KEY for richer AI synthesis._"
        )

    prompt = f"""You are an AI Product Manager research assistant for Zepto (quick commerce).

A Zepto PM asked:
\"{question}\"

Here are the most relevant recent customer feedback snippets (with structured analysis):
{evidence_block}
{context_block}
Write a crisp research brief with EXACTLY these sections (use markdown headings):

### Customer Insight
One clear insight answering the PM question.

### Evidence
List up to 5 short customer comments (paraphrase lightly if needed, keep voice authentic).

### Root Cause
The underlying reason behind the behavior/problem.

### Product Opportunity
A concrete product opportunity / experiment Zepto could run.

Be specific to Zepto quick commerce. Align with dashboard insights when provided.
Do not invent fake quotes that contradict the evidence.
"""
    try:
        return generate_gemini_text(prompt)
    except Exception as exc:
        logger.error("PM answer generation failed: %s", exc)
        # Fall back to structured evidence brief (no live Gemini)
        quotes = "\n".join(
            f'{i}. "{(_s(e.get("text")) or _s(e.get("review_summary")))[:180]}"'
            for i, e in enumerate(evidence[:5], 1)
        ) or "1. No matching customer comments available yet."
        themes = ", ".join(
            sorted({_s(e.get("theme")) for e in evidence if _s(e.get("theme"))})
        ) or "Insufficient data"
        opportunities = [
            _s(e.get("product_opportunity"))
            for e in evidence
            if _s(e.get("product_opportunity"))
        ]
        opportunity = opportunities[0] if opportunities else (
            "Validate these themes with a discovery sprint and design a targeted journey experiment."
        )
        roots = [_s(e.get("root_cause")) for e in evidence if _s(e.get("root_cause"))]
        root = roots[0] if roots else f"Emerging themes: {themes}."
        return (
            f"### Customer Insight\n"
            f"Based on {len(evidence)} retrieved feedback items related to your question.\n\n"
            f"### Evidence\n{quotes}\n\n"
            f"### Root Cause\n{root}\n\n"
            f"### Product Opportunity\n{opportunity}\n\n"
            f"_Note: AI analysis is temporarily unavailable. "
            f"Showing the most recent successfully analyzed insights from retrieved reviews._"
        )
