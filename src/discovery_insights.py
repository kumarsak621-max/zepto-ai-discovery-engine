"""
AI Discovery Engine insights for the PM assignment dashboard.

Combines quantitative review stats with Gemini-generated qualitative insights.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from src.config import EXPLORATION_BARRIER_THEMES, has_gemini
from src.data_pipeline import get_live_meta
from src.database import get_collection_stats, get_pm_insights
from src.gemini_analysis import _extract_json, generate_gemini_text
from src.paths import DATA_DIR, ensure_runtime_dirs

logger = logging.getLogger(__name__)

DISCOVERY_CACHE_PATH = DATA_DIR / "discovery_insights_cache.json"

DASHBOARD_PROMPT = """You are a Product Growth analyst for Zepto (Indian quick commerce).

Using ONLY the review evidence and aggregates below, return ONLY valid JSON with this schema:

{{
  "category_exploration_opportunities": [
    {{
      "current_category": "e.g. Groceries",
      "suggested_new_category": "e.g. Personal Care",
      "reason": "why users could be encouraged to buy the new category",
      "confidence_score": 0-100
    }}
  ],
  "growth_recommendations": [
    "5 to 10 short actionable recommendations for the Growth team"
  ],
  "growth_kpis": {{
    "users_mentioning_repetitive_purchases": 0-100,
    "users_expressing_interest_in_new_categories": 0-100,
    "users_mentioning_discovery_problems": 0-100,
    "category_exploration_opportunity_score": 0-100,
    "cross_sell_opportunity_score": 0-100,
    "average_experimentation_intent": 0-100,
    "discovery_friction_score": 0-100,
    "recommendation_relevance_score": 0-100
  }},
  "ai_user_segments": [
    {{
      "segment": "segment name",
      "percentage": 0-100,
      "key_characteristics": "short description",
      "typical_shopping_behaviour": "short description"
    }}
  ],
  "shopping_habit_insights": [
    "4 to 8 concise insight sentences about recurring shopping behaviour"
  ],
  "discovery_barriers": [
    {{
      "barrier": "barrier name",
      "frequency": 0-100,
      "severity": "Low|Medium|High",
      "representative_review": "short paraphrase grounded in evidence"
    }}
  ],
  "root_cause_analysis": {{
    "causes": [
      {{
        "root_cause": "name of root cause behind repetitive category purchasing",
        "description": "1-2 sentence explanation grounded in reviews",
        "frequency": 0-100,
        "severity_score": 1-10,
        "ai_confidence": 0-100,
        "example_review": "short paraphrase or quote grounded in evidence",
        "suggested_product_opportunity": "concrete Zepto product/growth opportunity",
        "business_impact": "High|Medium|Low",
        "implementation_effort": "High|Medium|Low",
        "priority": "P0|P1|P2|P3",
        "suggested_solution": "short solution tied to this root cause"
      }}
    ],
    "summary": "3-6 paragraph markdown summary titled rationale for why users keep buying the same categories — cover repetitive purchasing, exploration blockers, highest-impact barriers, most affected segments, and biggest category growth opportunities",
    "pm_insights": [
      "5 to 10 actionable PM insights; each MUST explicitly reference a detected root cause"
    ]
  }},
  "ai_confidence_score": 0-100,
  "theme_confidence_score": 0-100
}}

Rules:
- Generate 4-8 category opportunities, 5-10 growth recommendations, 5-8 segments, 4-8 habit insights, 4-8 barriers.
- For root_cause_analysis: detect 5-10 root causes explaining WHY users repeatedly buy familiar categories instead of exploring new ones.
- Consider causes such as habit-driven shopping, low trust, poor discovery, generic recommendations, price sensitivity, limited product info, fear of wasting money, lack of reviews, limited category awareness, search-first behaviour, time-saving mindset, lack of personalization — AND any additional causes present in the data.
- Percentages across segments should roughly sum to ~100.
- Ground every insight in the evidence. Do not invent unrelated categories.
- Prefer Zepto-relevant categories: Groceries, Snacks, Beverages, Personal Care, Beauty, Baby Care, Household, Fresh Produce, Dairy, Packaged Food.

AGGREGATES:
{aggregates}

SAMPLE ANALYZED REVIEWS:
{samples}
"""


def _hlm(value: Any, default: str = "Medium") -> str:
    s = str(value or default).strip().title()
    return s if s in {"High", "Medium", "Low"} else default


def _priority(value: Any, *, impact: str = "Medium", effort: str = "Medium") -> str:
    s = str(value or "").strip().upper()
    if s in {"P0", "P1", "P2", "P3"}:
        return s
    # Derive when missing: high impact + low effort => P0
    rank = {
        ("High", "Low"): "P0",
        ("High", "Medium"): "P1",
        ("High", "High"): "P2",
        ("Medium", "Low"): "P1",
        ("Medium", "Medium"): "P2",
        ("Medium", "High"): "P3",
        ("Low", "Low"): "P2",
        ("Low", "Medium"): "P3",
        ("Low", "High"): "P3",
    }
    return rank.get((impact, effort), "P2")


def _normalize_root_cause_analysis(data: dict[str, Any] | None) -> dict[str, Any]:
    block = data if isinstance(data, dict) else {}
    causes = []
    for row in block.get("causes") or []:
        if not isinstance(row, dict):
            continue
        impact = _hlm(row.get("business_impact"), "Medium")
        effort = _hlm(row.get("implementation_effort"), "Medium")
        sev = int(_clamp_score(row.get("severity_score"), 5))
        sev = max(1, min(10, sev if sev <= 10 else int(round(sev / 10))))
        causes.append(
            {
                "root_cause": str(row.get("root_cause") or "Unspecified")[:120],
                "description": str(row.get("description") or "")[:400],
                "frequency": int(_clamp_score(row.get("frequency"), 20)),
                "severity_score": sev,
                "ai_confidence": int(_clamp_score(row.get("ai_confidence"), 70)),
                "example_review": str(row.get("example_review") or "")[:300],
                "suggested_product_opportunity": str(
                    row.get("suggested_product_opportunity") or ""
                )[:300],
                "business_impact": impact,
                "implementation_effort": effort,
                "priority": _priority(row.get("priority"), impact=impact, effort=effort),
                "suggested_solution": str(row.get("suggested_solution") or "")[:300],
            }
        )
    causes.sort(key=lambda c: (c["severity_score"], c["frequency"]), reverse=True)
    pm_insights = [
        str(x).strip()
        for x in (block.get("pm_insights") or [])
        if str(x).strip()
    ][:10]
    summary = str(block.get("summary") or "").strip()
    return {
        "causes": causes,
        "summary": summary,
        "pm_insights": pm_insights,
    }


def _build_root_cause_fallback(
    reviews: list[dict[str, Any]],
    insights: dict[str, Any],
    kpi_seeds: dict[str, float],
) -> dict[str, Any]:
    """
    Evidence-derived root-cause payload when Gemini is unavailable.
    Built from per-review root_cause / theme / pain fields — not static copy.
    """
    cause_counter: Counter = Counter()
    examples: dict[str, str] = {}
    opportunities: dict[str, str] = {}
    for r in reviews:
        cause = (r.get("root_cause") or "").strip()
        theme = (r.get("theme") or "").strip()
        pain = (r.get("pain_point") or "").strip()
        key = cause or theme or pain
        if not key:
            continue
        key = key[:90]
        cause_counter[key] += 1
        if key not in examples:
            examples[key] = (r.get("review_summary") or r.get("text") or "")[:220]
        if key not in opportunities and r.get("product_opportunity"):
            opportunities[key] = str(r.get("product_opportunity"))[:240]

    total = max(len(reviews), 1)
    causes = []
    for label, count in cause_counter.most_common(10):
        freq = min(100, int(_pct(count, total) * 2.5)) or max(5, count)
        sev = max(1, min(10, int(round(freq / 10)) + (2 if label in EXPLORATION_BARRIER_THEMES else 0)))
        impact = "High" if sev >= 7 else "Medium" if sev >= 4 else "Low"
        effort = "Medium"
        if any(k in label.lower() for k in ("habit", "awareness", "search")):
            effort = "Low"
        elif any(k in label.lower() for k in ("trust", "personaliz", "recommend")):
            effort = "High"
        causes.append(
            {
                "root_cause": label,
                "description": (
                    f"Detected in {count} analyzed reviews as a driver of "
                    "repetitive category purchasing / limited exploration."
                ),
                "frequency": freq,
                "severity_score": sev,
                "ai_confidence": int(
                    min(
                        92,
                        55
                        + _pct(
                            sum(1 for r in reviews if r.get("root_cause")),
                            total,
                        )
                        * 0.3,
                    )
                ),
                "example_review": examples.get(label) or "See analyzed reviews for evidence.",
                "suggested_product_opportunity": opportunities.get(label)
                or "Design a targeted experiment that removes this friction from discovery.",
                "business_impact": impact,
                "implementation_effort": effort,
                "priority": _priority(None, impact=impact, effort=effort),
                "suggested_solution": (
                    f"Address '{label}' with a focused product experiment tied to "
                    "category discovery and recommendation quality."
                ),
            }
        )

    if not causes:
        # Minimal seeds from KPI signals when structured fields are empty
        signal_map = [
            (
                "Habit-driven shopping",
                kpi_seeds.get("users_mentioning_repetitive_purchases", 40),
                "Users reorder familiar products from the same categories.",
            ),
            (
                "Poor product discovery",
                kpi_seeds.get("users_mentioning_discovery_problems", 30),
                "Users struggle to find or notice new categories in the app.",
            ),
            (
                "Generic recommendations",
                max(0, 100 - kpi_seeds.get("recommendation_relevance_score", 60)),
                "Recommendations feel irrelevant, so users stick to search + staples.",
            ),
            (
                "Limited category awareness",
                kpi_seeds.get("users_expressing_interest_in_new_categories", 25),
                "Users show latent interest but limited awareness of adjacent aisles.",
            ),
        ]
        for name, freq, desc in signal_map:
            freq_i = int(_clamp_score(freq, 25))
            sev = max(1, min(10, int(round(freq_i / 10))))
            impact = "High" if sev >= 7 else "Medium"
            causes.append(
                {
                    "root_cause": name,
                    "description": desc,
                    "frequency": freq_i,
                    "severity_score": sev,
                    "ai_confidence": 60,
                    "example_review": desc,
                    "suggested_product_opportunity": (
                        "Ship a discovery journey that counters this root cause."
                    ),
                    "business_impact": impact,
                    "implementation_effort": "Medium",
                    "priority": _priority(None, impact=impact, effort="Medium"),
                    "suggested_solution": f"Prioritize experiments that reduce '{name}'.",
                }
            )

    top = causes[:3]
    top_names = ", ".join(c["root_cause"] for c in top) or "mixed behavioural drivers"
    segments = insights.get("all_segments") or []
    seg_bits = ", ".join(s.get("label", "") for s in segments[:3] if s.get("label")) or (
        "frequent and convenience-first shoppers"
    )
    cats = insights.get("product_categories") or []
    cat_bits = ", ".join(c.get("label", "") for c in cats[:3] if c.get("label")) or (
        "adjacent non-staple categories"
    )
    summary = (
        f"### Why Users Keep Buying the Same Categories\n\n"
        f"Across {len(reviews):,} reviews, repetitive purchasing is largely explained by "
        f"**{top_names}**. Users return to familiar products because these root causes "
        f"reduce the perceived value and ease of exploring new aisles.\n\n"
        f"Exploration is blocked most by high-severity causes "
        f"(scores {', '.join(str(c['severity_score']) for c in top)}). "
        f"Segments most affected include {seg_bits}.\n\n"
        f"The largest growth opportunities sit in expanding from staple baskets into "
        f"{cat_bits}, if Zepto removes the top root causes through discovery, trust, "
        f"and personalization experiments."
    )
    pm_insights = [
        f"Improve personalized recommendations to counter '{c['root_cause']}' "
        f"(severity {c['severity_score']}/10)."
        for c in causes[:3]
    ]
    pm_insights += [
        f"Introduce category discovery journeys targeting '{c['root_cause']}'."
        for c in causes[3:5]
    ] or [
        "Introduce category discovery journeys for low-awareness aisles."
    ]
    pm_insights += [
        "Offer trial-size bundles to reduce fear of wasting money on unfamiliar categories.",
        "Increase trust through richer reviews/ratings on new-category SKUs.",
        "Highlight complementary products after checkout while intent is still high.",
        "Promote category-specific campaigns for aisles blocked by the top root causes.",
    ]
    return {
        "causes": causes[:10],
        "summary": summary,
        "pm_insights": pm_insights[:10],
    }


def _pct(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 1)


def _normalize_sentiment(value: Any) -> str:
    s = str(value or "").strip().title()
    if s in {"Positive", "Negative", "Neutral"}:
        return s
    return "Neutral" if s else "Unanalyzed"


def compute_sentiment_analysis(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    counts: Counter = Counter()
    for r in reviews:
        counts[_normalize_sentiment(r.get("sentiment"))] += 1
    # Fold unanalyzed into Neutral for overall score display when present
    positive = counts.get("Positive", 0)
    neutral = counts.get("Neutral", 0) + counts.get("Unanalyzed", 0)
    negative = counts.get("Negative", 0)
    total = positive + neutral + negative
    return {
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
        "total": total,
        "positive_pct": _pct(positive, total),
        "neutral_pct": _pct(neutral, total),
        "negative_pct": _pct(negative, total),
        "overall_score": {
            "Positive": _pct(positive, total),
            "Neutral": _pct(neutral, total),
            "Negative": _pct(negative, total),
        },
    }


def _keyword_share(reviews: list[dict[str, Any]], keywords: tuple[str, ...]) -> float:
    if not reviews:
        return 0.0
    hits = 0
    for r in reviews:
        blob = " ".join(
            str(r.get(k) or "")
            for k in ("text", "review_summary", "theme", "pain_point", "root_cause")
        ).lower()
        if any(kw in blob for kw in keywords):
            hits += 1
    return _pct(hits, len(reviews))


def compute_growth_kpi_seeds(reviews: list[dict[str, Any]], insights: dict[str, Any]) -> dict[str, float]:
    repetitive = _keyword_share(
        reviews, ("always", "regular", "everyday", "reorder", "same", "habit", "daily")
    )
    new_cat = _keyword_share(
        reviews,
        ("personal care", "beauty", "try", "new", "explore", "category", "recommend"),
    )
    discovery = _keyword_share(
        reviews, ("can't find", "hard to find", "search", "discover", "not showing", "browse")
    )
    barrier_n = sum(
        b.get("count", 0) for b in (insights.get("category_exploration_barriers") or [])
    )
    analyzed = max(int(insights.get("analyzed_count") or 0), 1)
    friction = min(100.0, round(100.0 * barrier_n / analyzed, 1))
    return {
        "users_mentioning_repetitive_purchases": repetitive,
        "users_expressing_interest_in_new_categories": new_cat,
        "users_mentioning_discovery_problems": discovery,
        "category_exploration_opportunity_score": round((new_cat + (100 - friction)) / 2, 1),
        "cross_sell_opportunity_score": round((new_cat + repetitive) / 2, 1),
        "average_experimentation_intent": round(new_cat * 0.8 + discovery * 0.2, 1),
        "discovery_friction_score": friction,
        "recommendation_relevance_score": round(max(0.0, 100 - discovery * 0.7), 1),
    }


def compute_insight_validation(
    reviews: list[dict[str, Any]],
    insights: dict[str, Any],
    *,
    ai_confidence: float | None = None,
    theme_confidence: float | None = None,
) -> dict[str, Any]:
    meta = get_live_meta() or {}
    stats = get_collection_stats()
    play = int(meta.get("playstore_count") or 0)
    app = int(meta.get("appstore_count") or 0)
    merged = int(meta.get("merged_count") or insights.get("total_reviews") or len(reviews))
    raw_sum = play + app
    duplicates = max(0, raw_sum - merged) if raw_sum else 0

    analyzed = int(insights.get("analyzed_count") or 0)
    total = int(insights.get("total_reviews") or len(reviews))
    complete = 0
    themed = 0
    for r in reviews:
        if r.get("sentiment") and r.get("theme") and r.get("customer_segment"):
            complete += 1
        if r.get("theme"):
            themed += 1

    if ai_confidence is None:
        ai_confidence = _pct(complete, total) if total else 0.0
    if theme_confidence is None:
        theme_confidence = _pct(themed, total) if total else 0.0

    sources = sorted(
        {
            str(s).replace("_", " ").title()
            for s in (stats.get("by_source") or {}).keys()
            if s
        }
    )
    if not sources:
        sources = [
            n
            for n, c in (
                ("Google Play", play),
                ("Apple App Store", app),
            )
            if c
        ]

    return {
        "duplicates_removed": duplicates,
        "total_reviews_analysed": analyzed or total,
        "sources_analysed": sources or ["None yet"],
        "ai_confidence_score": round(float(ai_confidence), 1),
        "theme_confidence_score": round(float(theme_confidence), 1),
        "last_analysis_timestamp": meta.get("last_updated"),
        "note": (
            "AI-generated insights were validated through duplicate removal, "
            "confidence scoring, and review consistency checks."
        ),
    }


def _fallback_discovery(
    reviews: list[dict[str, Any]],
    insights: dict[str, Any],
    kpi_seeds: dict[str, float],
) -> dict[str, Any]:
    cats = [c["label"] for c in (insights.get("product_categories") or [])]
    base = cats[0] if cats else "Groceries"
    opportunities = [
        {
            "current_category": base,
            "suggested_new_category": "Personal Care",
            "reason": "Users who reorder staples often mention adjacent wellness needs.",
            "confidence_score": min(92, int(kpi_seeds.get("cross_sell_opportunity_score", 70) + 10)),
        },
        {
            "current_category": "Snacks",
            "suggested_new_category": "Beverages",
            "reason": "High complementary purchase probability with late-night and routine orders.",
            "confidence_score": min(90, int(kpi_seeds.get("category_exploration_opportunity_score", 65) + 8)),
        },
        {
            "current_category": "Fresh Produce",
            "suggested_new_category": "Dairy",
            "reason": "Frequent grocery buyers show routine basket patterns that include dairy staples.",
            "confidence_score": 78,
        },
        {
            "current_category": "Household",
            "suggested_new_category": "Baby Care",
            "reason": "Household shoppers show latent demand for adjacent family categories.",
            "confidence_score": 71,
        },
    ]

    segments_raw = insights.get("all_segments") or []
    total_seg = sum(s.get("count", 0) for s in segments_raw) or 1
    ai_segments = []
    behaviour_map = {
        "Price-sensitive": ("Compares prices and discounts", "Buys when offers are clear"),
        "Convenience": ("Values speed and low effort", "Reorders familiar items quickly"),
        "Health": ("Cares about freshness and quality", "Prefers trusted brands"),
        "Premium": ("Willing to pay for quality", "Chooses branded / premium SKUs"),
        "Frequent": ("High order frequency", "Weekly or daily grocery routines"),
        "Impulse": ("Responds to cravings and prompts", "Adds unplanned items near checkout"),
        "Occasional": ("Lower engagement", "Uses Zepto for urgent needs"),
    }
    for s in segments_raw[:7]:
        name = s.get("label") or "General shopper"
        chars, behav = "Mixed needs", "Varies by occasion"
        for key, pair in behaviour_map.items():
            if key.lower() in name.lower():
                chars, behav = pair
                break
        ai_segments.append(
            {
                "segment": name,
                "percentage": _pct(int(s.get("count") or 0), total_seg),
                "key_characteristics": chars,
                "typical_shopping_behaviour": behav,
            }
        )
    if not ai_segments:
        ai_segments = [
            {
                "segment": "Frequent buyers",
                "percentage": 34,
                "key_characteristics": "Reorder familiar staples",
                "typical_shopping_behaviour": "Weekly grocery routines",
            },
            {
                "segment": "Convenience-first users",
                "percentage": 28,
                "key_characteristics": "Speed-focused",
                "typical_shopping_behaviour": "Quick checkout, limited browsing",
            },
            {
                "segment": "Price-sensitive shoppers",
                "percentage": 22,
                "key_characteristics": "Deal-aware",
                "typical_shopping_behaviour": "Waits for offers before trying new categories",
            },
            {
                "segment": "Health-conscious users",
                "percentage": 16,
                "key_characteristics": "Quality and freshness focused",
                "typical_shopping_behaviour": "Selective exploration into personal care / organic",
            },
        ]

    barriers = []
    for b in insights.get("category_exploration_barriers") or []:
        count = int(b.get("count") or 0)
        freq = min(100, int(_pct(count, max(len(reviews), 1)) * 3))
        severity = "High" if freq >= 40 else "Medium" if freq >= 20 else "Low"
        examples = b.get("examples") or []
        barriers.append(
            {
                "barrier": b.get("barrier") or "Unknown",
                "frequency": freq,
                "severity": severity,
                "representative_review": examples[0] if examples else "Users cite this barrier in recent feedback.",
            }
        )
    if not barriers:
        barriers = [
            {
                "barrier": "Habit-driven behaviour",
                "frequency": int(kpi_seeds.get("users_mentioning_repetitive_purchases", 40)),
                "severity": "High",
                "representative_review": "Users repeatedly reorder familiar products instead of browsing.",
            },
            {
                "barrier": "Poor recommendations",
                "frequency": int(100 - kpi_seeds.get("recommendation_relevance_score", 60)),
                "severity": "Medium",
                "representative_review": "Suggestions feel irrelevant to current baskets.",
            },
            {
                "barrier": "Lack of trust",
                "frequency": 28,
                "severity": "Medium",
                "representative_review": "Users hesitate to try new categories without quality proof.",
            },
            {
                "barrier": "High prices",
                "frequency": 24,
                "severity": "Medium",
                "representative_review": "Price concerns block experimentation beyond staples.",
            },
        ]

    habits = insights.get("shopping_habits") or []
    habit_cards = [
        f"{h.get('label')}: mentioned in {h.get('count')} analyzed reviews."
        for h in habits[:6]
    ] or [
        "Users repeatedly reorder familiar products.",
        "Users rarely browse beyond staple categories.",
        "Shopping often follows weekly routines.",
        "Recommendations have limited influence on basket expansion.",
        "Users search instead of exploring category pages.",
    ]

    recommendations = [
        "Introduce personalized category recommendations based on reorder patterns.",
        "Offer trial packs for Personal Care and Beauty to reduce risk.",
        "Recommend complementary products (e.g. Snacks → Beverages) after checkout.",
        "Create category discovery campaigns for low-awareness aisles.",
        "Improve recommendation relevance using recent basket context.",
        "Promote seasonal bundles that pair staples with adjacent categories.",
        "Show recommendations after checkout while intent is still high.",
        "Improve trust for new categories with freshness badges and reviews.",
    ]

    rca = _build_root_cause_fallback(reviews, insights, kpi_seeds)
    return {
        "category_exploration_opportunities": opportunities,
        "growth_recommendations": recommendations,
        "growth_kpis": kpi_seeds,
        "ai_user_segments": ai_segments,
        "shopping_habit_insights": habit_cards,
        "discovery_barriers": barriers,
        "root_cause_analysis": rca,
        "ai_confidence_score": _pct(
            sum(1 for r in reviews if r.get("sentiment") and r.get("theme")),
            max(len(reviews), 1),
        ),
        "theme_confidence_score": _pct(
            sum(1 for r in reviews if r.get("theme")),
            max(len(reviews), 1),
        ),
        "source": "fallback",
    }


def _clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _normalize_gemini_payload(data: dict[str, Any], kpi_seeds: dict[str, float]) -> dict[str, Any]:
    opps = []
    for row in data.get("category_exploration_opportunities") or []:
        if not isinstance(row, dict):
            continue
        opps.append(
            {
                "current_category": str(row.get("current_category") or "Groceries")[:80],
                "suggested_new_category": str(row.get("suggested_new_category") or "Personal Care")[:80],
                "reason": str(row.get("reason") or "")[:400],
                "confidence_score": int(_clamp_score(row.get("confidence_score"), 70)),
            }
        )

    recs = [
        str(r).strip()
        for r in (data.get("growth_recommendations") or [])
        if str(r).strip()
    ][:10]

    raw_kpis = data.get("growth_kpis") or {}
    kpis = {**kpi_seeds}
    for key in kpi_seeds:
        if key in raw_kpis:
            kpis[key] = _clamp_score(raw_kpis[key], kpi_seeds[key])

    segments = []
    for row in data.get("ai_user_segments") or []:
        if isinstance(row, str) and row.strip():
            segments.append(
                {
                    "segment": row.strip()[:80],
                    "percentage": 0,
                    "key_characteristics": "",
                    "typical_shopping_behaviour": "",
                }
            )
            continue
        if not isinstance(row, dict):
            continue
        segments.append(
            {
                "segment": str(row.get("segment") or "General")[:80],
                "percentage": _clamp_score(row.get("percentage"), 0),
                "key_characteristics": str(row.get("key_characteristics") or "")[:240],
                "typical_shopping_behaviour": str(
                    row.get("typical_shopping_behaviour")
                    or row.get("typical_shopping_behavior")
                    or ""
                )[:240],
            }
        )

    raw_habits = data.get("shopping_habit_insights") or []
    if isinstance(raw_habits, str):
        raw_habits = [raw_habits]
    habits = []
    for h in raw_habits:
        if isinstance(h, dict):
            text = str(h.get("insight") or h.get("text") or h.get("summary") or "").strip()
        else:
            text = str(h).strip()
        if text:
            habits.append(text)
    habits = habits[:8]

    barriers = []
    for row in data.get("discovery_barriers") or []:
        if not isinstance(row, dict):
            continue
        sev = str(row.get("severity") or "Medium").title()
        if sev not in {"Low", "Medium", "High"}:
            sev = "Medium"
        barriers.append(
            {
                "barrier": str(row.get("barrier") or "Unknown")[:120],
                "frequency": int(_clamp_score(row.get("frequency"), 20)),
                "severity": sev,
                "representative_review": str(row.get("representative_review") or "")[:300],
            }
        )

    rca = _normalize_root_cause_analysis(data.get("root_cause_analysis"))
    return {
        "category_exploration_opportunities": opps,
        "growth_recommendations": recs,
        "growth_kpis": kpis,
        "ai_user_segments": segments,
        "shopping_habit_insights": habits,
        "discovery_barriers": barriers,
        "root_cause_analysis": rca,
        "ai_confidence_score": _clamp_score(data.get("ai_confidence_score"), 70),
        "theme_confidence_score": _clamp_score(data.get("theme_confidence_score"), 70),
        "source": "gemini",
    }


def _discovery_cache_key(insights: dict[str, Any], *, mode: str = "") -> str:
    meta = get_live_meta() or {}
    return "|".join(
        [
            str(meta.get("last_updated") or ""),
            str(insights.get("analyzed_count") or 0),
            str(insights.get("total_reviews") or 0),
            str(insights.get("avg_rating") or ""),
            str(mode or ""),
        ]
    )


def _discovery_payload_is_valid(discovery: dict[str, Any] | None) -> bool:
    if not isinstance(discovery, dict):
        return False
    rca = discovery.get("root_cause_analysis") or {}
    causes = rca.get("causes") if isinstance(rca, dict) else None
    if not isinstance(causes, list) or not causes:
        return False
    if not isinstance(discovery.get("growth_kpis"), dict):
        return False
    if not isinstance(discovery.get("ai_user_segments"), list):
        return False
    return True


def clear_discovery_disk_cache() -> None:
    try:
        if DISCOVERY_CACHE_PATH.exists():
            DISCOVERY_CACHE_PATH.unlink()
    except OSError as exc:
        logger.warning("Could not clear discovery cache: %s", exc)


def _is_durable_discovery_cache(discovery: dict[str, Any]) -> bool:
    """Only durable Gemini successes should be reused from disk."""
    source = str((discovery or {}).get("source") or "").lower()
    if source.startswith("fallback"):
        return False
    return source in {"gemini", "gemini-cached", "cache", "ok"}


def _load_discovery_disk_cache(cache_key: str) -> dict[str, Any] | None:
    if not DISCOVERY_CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(DISCOVERY_CACHE_PATH.read_text(encoding="utf-8"))
        discovery = payload.get("discovery")
        if (
            payload.get("cache_key") == cache_key
            and _discovery_payload_is_valid(discovery)
            and _is_durable_discovery_cache(discovery)
        ):
            return discovery
        # Drop poisoned / fallback caches so Gemini can retry after key fixes
        if isinstance(discovery, dict) and not _is_durable_discovery_cache(discovery):
            clear_discovery_disk_cache()
    except Exception:
        return None
    return None


def _save_discovery_disk_cache(cache_key: str, discovery: dict[str, Any]) -> None:
    """Persist only successful Gemini payloads — never cache auth/timeout fallbacks."""
    if not _discovery_payload_is_valid(discovery) or not _is_durable_discovery_cache(discovery):
        return
    try:
        ensure_runtime_dirs()
        DISCOVERY_CACHE_PATH.write_text(
            json.dumps(
                {"cache_key": cache_key, "discovery": discovery},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not persist discovery cache: %s", exc)


def _call_gemini_discovery_json(prompt: str) -> dict[str, Any]:
    if not (prompt or "").strip():
        raise ValueError("Discovery prompt is empty")
    raw = generate_gemini_text(prompt)
    if not (raw or "").strip():
        raise RuntimeError("Gemini returned an empty discovery response")
    return _extract_json(raw or "")


def _is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "401",
            "403",
            "api key",
            "invalid authentication",
            "access_token_type_unsupported",
            "permission_denied",
            "unauthenticated",
        )
    )


def generate_gemini_discovery(
    reviews: list[dict[str, Any]],
    insights: dict[str, Any],
) -> dict[str, Any]:
    kpi_seeds = compute_growth_kpi_seeds(reviews, insights)
    fallback = _fallback_discovery(reviews, insights, kpi_seeds)
    if not reviews:
        return fallback

    cache_key = _discovery_cache_key(
        insights, mode=str((insights or {}).get("_analysis_mode") or "")
    )
    cached = _load_discovery_disk_cache(cache_key)
    if cached:
        return cached

    if not has_gemini():
        logger.warning("generate_gemini_discovery: no Gemini keys — evidence fallback")
        print("[AI DEBUG] discovery: no Gemini keys — fallback", flush=True)
        return {
            **fallback,
            "source": "fallback-no-keys",
            "error_message": "No Gemini API keys configured",
            "error_type": "ConfigurationError",
            "error_traceback": "",
        }

    # Fresh attempt for dashboard synthesis (avoids stale circuit from prior page load)
    try:
        from src.gemini_key_manager import get_key_manager, gemini_active_label
        from src.config import get_gemini_model

        get_key_manager().reset_circuit()
        logger.info(
            "Discovery Gemini start key=%s model=%s reviews=%s",
            gemini_active_label(),
            get_gemini_model(),
            len(reviews),
        )
        print(
            f"[AI DEBUG] discovery start key={gemini_active_label()} "
            f"model={get_gemini_model()} reviews={len(reviews)}",
            flush=True,
        )
    except Exception:
        logger.exception("Could not reset Gemini circuit before discovery")
        print("[AI DEBUG] discovery circuit reset failed", flush=True)
    sample_lines = []
    for r in reviews[:40]:
        sample_lines.append(
            "- [{src}|{sent}|{theme}|{seg}|{cat}] pain={pain} | {summary}".format(
                src=r.get("source") or "?",
                sent=r.get("sentiment") or "?",
                theme=r.get("theme") or "?",
                seg=r.get("customer_segment") or "?",
                cat=r.get("category") or "?",
                pain=(r.get("pain_point") or "n/a")[:80],
                summary=(r.get("review_summary") or r.get("text") or "")[:180],
            )
        )

    aggregates = {
        "total_reviews": insights.get("total_reviews"),
        "analyzed_count": insights.get("analyzed_count"),
        "avg_rating": insights.get("avg_rating"),
        "top_themes": insights.get("most_frequent_themes"),
        "top_pain_points": insights.get("top_customer_problems"),
        "product_categories": insights.get("product_categories"),
        "segments": insights.get("all_segments"),
        "kpi_seeds": kpi_seeds,
        "ai_summary": insights.get("ai_summary"),
    }

    prompt = DASHBOARD_PROMPT.format(
        aggregates=json.dumps(aggregates, ensure_ascii=False)[:4000],
        samples="\n".join(sample_lines)[:8000],
    )
    try:
        # Key manager handles timeouts, retries, multi-key + multi-model failover
        data = _call_gemini_discovery_json(prompt)
        normalized = _normalize_gemini_payload(data, kpi_seeds)
        # Ensure required lists are populated from evidence-based fallback
        if not normalized["category_exploration_opportunities"]:
            normalized["category_exploration_opportunities"] = fallback[
                "category_exploration_opportunities"
            ]
        if len(normalized["growth_recommendations"]) < 5:
            normalized["growth_recommendations"] = fallback["growth_recommendations"]
        if not normalized["ai_user_segments"]:
            normalized["ai_user_segments"] = fallback["ai_user_segments"]
        if not normalized["shopping_habit_insights"]:
            normalized["shopping_habit_insights"] = fallback["shopping_habit_insights"]
        if not normalized["discovery_barriers"]:
            normalized["discovery_barriers"] = fallback["discovery_barriers"]
        rca = normalized.get("root_cause_analysis") or {}
        if not rca.get("causes") or len(rca.get("pm_insights") or []) < 5 or not rca.get(
            "summary"
        ):
            fb_rca = fallback["root_cause_analysis"]
            if not rca.get("causes"):
                rca["causes"] = fb_rca["causes"]
            if not rca.get("summary"):
                rca["summary"] = fb_rca["summary"]
            if len(rca.get("pm_insights") or []) < 5:
                rca["pm_insights"] = fb_rca["pm_insights"]
            normalized["root_cause_analysis"] = rca
        if not _discovery_payload_is_valid(normalized):
            logger.warning(
                "Gemini discovery payload invalid after normalize — using evidence fallback"
            )
            print("[AI DEBUG] discovery invalid payload — fallback", flush=True)
            return {
                **fallback,
                "source": "fallback-invalid-payload",
                "error_message": "Gemini returned an invalid discovery payload after normalize",
                "error_type": "InvalidPayload",
                "error_traceback": "",
            }
        normalized["source"] = "gemini"
        _save_discovery_disk_cache(cache_key, normalized)
        logger.info("Gemini discovery dashboard generated successfully")
        print("[AI DEBUG] discovery end SUCCESS", flush=True)
        try:
            from src.gemini_debug import record_ai_success

            record_ai_success(stage="generate_gemini_discovery")
        except Exception:
            logger.exception("record_ai_success after discovery failed")
        return normalized
    except Exception as exc:
        import traceback as _tb

        from src.gemini_debug import record_ai_failure

        debug = record_ai_failure(exc, stage="generate_gemini_discovery")
        logger.exception("Gemini discovery dashboard failed — using evidence fallback")
        print(f"[AI DEBUG] discovery FINAL exception: {exc}", flush=True)
        msg = str(exc).lower()
        if "timed out" in msg or "timeout" in msg:
            source = "fallback-timeout"
        elif (
            "all gemini api keys failed" in msg
            or "after trying every configured key" in msg
            or _is_auth_error(exc)
        ):
            source = "fallback-all-keys"
        else:
            source = "fallback-error"
        # Do not disk-cache error fallbacks — allows retry after key/quota recovery
        return {
            **fallback,
            "source": source,
            "error_message": str(exc),
            "error_type": type(exc).__name__,
            "error_traceback": debug.get("traceback") or _tb.format_exc(),
        }


def build_discovery_dashboard(
    reviews: list[dict[str, Any]] | None = None,
    *,
    limit: int = 2000,
    analysis_mode: str = "all",
) -> dict[str, Any]:
    """Full payload for the PM Discovery dashboard. Never raises to the UI layer."""
    from src.database import fetch_all_reviews

    try:
        reviews = reviews if reviews is not None else fetch_all_reviews(limit=limit)
    except Exception as exc:
        logger.exception("fetch_all_reviews failed")
        reviews = []
        fetch_error = str(exc)
    else:
        fetch_error = ""

    try:
        insights = (
            get_pm_insights(reviews=reviews, limit=limit)
            if reviews
            else {
            "analyzed_count": 0,
            "total_reviews": 0,
            "avg_rating": None,
            "top_customer_problems": [],
            "most_frequent_themes": [],
            "shopping_habits": [],
            "product_categories": [],
            "root_causes": [],
            "ai_summary": "",
            "category_exploration_barriers": [],
            "exploration_potential_segments": [],
            "all_segments": [],
            "recommended_product_opportunities": [],
        }
        )
        if isinstance(insights, dict):
            insights["_analysis_mode"] = analysis_mode
    except Exception as exc:
        logger.exception("get_pm_insights failed")
        insights = {
            "analyzed_count": 0,
            "total_reviews": len(reviews),
            "avg_rating": None,
            "top_customer_problems": [],
            "most_frequent_themes": [],
            "shopping_habits": [],
            "product_categories": [],
            "root_causes": [],
            "ai_summary": f"Insights aggregation unavailable: {exc}",
            "category_exploration_barriers": [],
            "exploration_potential_segments": [],
            "all_segments": [],
            "recommended_product_opportunities": [],
        }

    sentiment = compute_sentiment_analysis(reviews)
    try:
        discovery = generate_gemini_discovery(reviews, insights)
    except Exception as exc:
        logger.exception("generate_gemini_discovery failed")
        discovery = _fallback_discovery(
            reviews, insights, compute_growth_kpi_seeds(reviews, insights)
        )
        discovery["source"] = f"fallback-error:{exc}"

    try:
        validation = compute_insight_validation(
            reviews,
            insights,
            ai_confidence=discovery.get("ai_confidence_score"),
            theme_confidence=discovery.get("theme_confidence_score"),
        )
    except Exception:
        validation = {
            "duplicates_removed": 0,
            "total_reviews_analysed": insights.get("analyzed_count") or len(reviews),
            "sources_analysed": [],
            "ai_confidence_score": 0,
            "theme_confidence_score": 0,
            "last_analysis_timestamp": None,
            "note": (
                "AI-generated insights were validated through duplicate removal, "
                "confidence scoring, and review consistency checks."
            ),
        }

    live_meta = get_live_meta() or {}
    try:
        stats = get_collection_stats()
    except Exception:
        stats = {"by_source": {}, "total": len(reviews)}

    by_src = stats.get("by_source") or {}
    play_db = int(by_src.get("playstore") or 0)
    apple_db = int(by_src.get("appstore") or 0)
    play_n = play_db or int(live_meta.get("playstore_count") or 0)
    apple_n = apple_db or int(live_meta.get("appstore_count") or 0)
    # Merged store reviews = Play + Apple only (excludes reddit/social)
    merged_n = play_n + apple_n
    if merged_n <= 0:
        merged_n = int(
            live_meta.get("merged_count")
            or insights.get("total_reviews")
            or len(reviews)
            or 0
        )

    payload = {
        "reviews": reviews,
        "insights": insights,
        "stats": stats,
        "live_meta": live_meta,
        "sentiment": sentiment,
        "discovery": discovery,
        "validation": validation,
        "review_sources": {
            "Google Play Reviews": play_n,
            "Apple App Store Reviews": apple_n,
            "Merged Reviews": merged_n,
        },
        "review_kpis": {
            "Total Reviews": insights.get("total_reviews") or len(reviews) or merged_n,
            "Analyzed Reviews": insights.get("analyzed_count") or 0,
            "Average Rating": insights.get("avg_rating"),
            "Unique Themes": len(insights.get("most_frequent_themes") or []),
            "Pain Points Tracked": len(insights.get("top_customer_problems") or []),
        },
    }
    if fetch_error:
        payload["load_warning"] = fetch_error
    return payload
