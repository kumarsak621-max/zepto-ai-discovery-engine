"""
Filtered review analytics, trend insights, and chart series for the Discovery Engine.

Builds on the SQLite historical warehouse without deleting or mutating stored reviews.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import (
    HISTORICAL_END_DATE,
    HISTORICAL_START_DATE,
    LIVE_REVIEW_WINDOW_DAYS,
    LIVE_START_DATE,
)
from src.database import (
    fetch_reviews_filtered,
    get_pm_insights,
    get_review_warehouse_stats,
)
from src.review_dates import historical_range_label, live_range_label

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "with",
    "from", "as", "by", "my", "me", "we", "you", "they", "i", "not", "no",
    "so", "if", "do", "does", "did", "have", "has", "had", "will", "would",
    "can", "could", "just", "very", "also", "than", "then", "too", "app",
    "zepto", "order", "delivery", "get", "got", "one", "all", "am", "im",
}


def _parse_dt(value: Any) -> datetime | None:
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


def apply_review_filters(
    *,
    data_source: str = "combined",
    date_range: str = "all",
    platform: str = "both",
    ratings: list[int] | None = None,
    sentiments: list[str] | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    platforms: list[str] | None
    plat = str(platform or "both").lower()
    if plat in {"google play", "playstore", "play"}:
        platforms = ["playstore"]
    elif plat in {"apple store", "appstore", "ios", "apple"}:
        platforms = ["appstore"]
    else:
        platforms = ["playstore", "appstore"]

    return fetch_reviews_filtered(
        data_source=data_source,
        date_range=date_range,
        platforms=platforms,
        ratings=ratings,
        sentiments=sentiments,
        live_window_days=LIVE_REVIEW_WINDOW_DAYS,
        limit=limit,
    )


def compute_trend_insights(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Week-over-week emerging issues, trending complaints/requests, sentiment delta."""
    now = datetime.now(timezone.utc)
    this_week = now - timedelta(days=7)
    last_week = now - timedelta(days=14)

    def _bucket(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict]:
        out = []
        for r in rows:
            dt = _parse_dt(r.get("date") or r.get("fetched_at") or r.get("created_at"))
            if dt and start <= dt < end:
                out.append(r)
        return out

    cur = _bucket(reviews, this_week, now)
    prev = _bucket(reviews, last_week, this_week)

    def _pain_counter(rows: list[dict]) -> Counter:
        c: Counter = Counter()
        for r in rows:
            pain = (r.get("pain_point") or "").strip()
            theme = (r.get("theme") or "").strip()
            intent = (r.get("user_intent") or "").strip()
            if pain:
                c[pain[:90]] += 1
            elif intent == "Complaint" and theme:
                c[theme] += 1
        return c

    def _request_counter(rows: list[dict]) -> Counter:
        c: Counter = Counter()
        for r in rows:
            intent = (r.get("user_intent") or "").strip()
            opp = (r.get("product_opportunity") or "").strip()
            theme = (r.get("theme") or "").strip()
            if intent == "Suggestion" or opp:
                key = (opp or theme or "Feature request")[:100]
                c[key] += 1
        return c

    cur_pain = _pain_counter(cur)
    prev_pain = _pain_counter(prev)
    cur_req = _request_counter(cur)
    prev_req = _request_counter(prev)

    new_issues = []
    for label, count in cur_pain.most_common(15):
        if prev_pain.get(label, 0) == 0 and count > 0:
            new_issues.append({"label": label, "count": count, "trend": "new"})

    increasing = []
    decreasing = []
    for label in set(cur_pain) | set(prev_pain):
        c_now = cur_pain.get(label, 0)
        c_prev = prev_pain.get(label, 0)
        if c_now > c_prev and c_now > 0:
            increasing.append(
                {
                    "label": label,
                    "this_week": c_now,
                    "last_week": c_prev,
                    "delta": c_now - c_prev,
                }
            )
        elif c_prev > c_now and c_prev > 0:
            decreasing.append(
                {
                    "label": label,
                    "this_week": c_now,
                    "last_week": c_prev,
                    "delta": c_now - c_prev,
                }
            )
    increasing.sort(key=lambda x: x["delta"], reverse=True)
    decreasing.sort(key=lambda x: x["delta"])

    trending_complaints = [
        {"label": k, "count": v, "last_week": prev_pain.get(k, 0)}
        for k, v in cur_pain.most_common(8)
    ]
    trending_requests = [
        {"label": k, "count": v, "last_week": prev_req.get(k, 0)}
        for k, v in cur_req.most_common(8)
    ]

    def _sent_share(rows: list[dict]) -> dict[str, float]:
        if not rows:
            return {"Positive": 0.0, "Neutral": 0.0, "Negative": 0.0}
        c = Counter((r.get("sentiment") or "Neutral").title() for r in rows)
        n = max(len(rows), 1)
        return {k: round(100.0 * c.get(k, 0) / n, 1) for k in ("Positive", "Neutral", "Negative")}

    cur_sent = _sent_share(cur)
    prev_sent = _sent_share(prev)
    sentiment_change = {
        k: round(cur_sent.get(k, 0) - prev_sent.get(k, 0), 1)
        for k in ("Positive", "Neutral", "Negative")
    }

    return {
        "new_issues_this_week": new_issues[:8],
        "trending_complaints": trending_complaints,
        "trending_feature_requests": trending_requests,
        "problems_increasing": increasing[:8],
        "problems_decreasing": decreasing[:8],
        "sentiment_change_vs_last_week": sentiment_change,
        "sentiment_this_week": cur_sent,
        "sentiment_last_week": prev_sent,
        "reviews_this_week": len(cur),
        "reviews_last_week": len(prev),
    }


def compute_chart_series(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Time-series and keyword series for Plotly visualizations."""
    daily: Counter = Counter()
    weekly: Counter = Counter()
    monthly: Counter = Counter()
    sent_by_day: dict[str, Counter] = {}
    rating_by_day: dict[str, list[float]] = {}
    category_by_month: dict[str, Counter] = {}
    pain_by_week: dict[str, Counter] = {}
    request_by_week: dict[str, Counter] = {}
    keywords: Counter = Counter()

    for r in reviews:
        dt = _parse_dt(r.get("date") or r.get("fetched_at") or r.get("created_at"))
        if not dt:
            continue
        day = dt.strftime("%Y-%m-%d")
        week = dt.strftime("%G-W%V")
        month = dt.strftime("%Y-%m")
        daily[day] += 1
        weekly[week] += 1
        monthly[month] += 1

        sent = (r.get("sentiment") or "Neutral").title()
        sent_by_day.setdefault(day, Counter())[sent] += 1

        try:
            rating_by_day.setdefault(day, []).append(float(r.get("rating")))
        except (TypeError, ValueError):
            pass

        cat = (r.get("category") or "").strip()
        if cat and cat.lower() not in {"app_review", "general", ""}:
            category_by_month.setdefault(month, Counter())[cat] += 1

        pain = (r.get("pain_point") or r.get("theme") or "").strip()
        if pain and (r.get("user_intent") == "Complaint" or r.get("sentiment") == "Negative"):
            pain_by_week.setdefault(week, Counter())[pain[:60]] += 1

        if r.get("user_intent") == "Suggestion" or r.get("product_opportunity"):
            key = (r.get("product_opportunity") or r.get("theme") or "Feature")[:60]
            request_by_week.setdefault(week, Counter())[key] += 1

        text = str(r.get("text") or "")
        for tok in re.findall(r"[a-zA-Z]{3,}", text.lower()):
            if tok not in _STOPWORDS:
                keywords[tok] += 1

    timeline = [{"date": d, "count": daily[d]} for d in sorted(daily)]
    sentiment_trend = []
    for d in sorted(sent_by_day):
        c = sent_by_day[d]
        sentiment_trend.append(
            {
                "date": d,
                "Positive": c.get("Positive", 0),
                "Neutral": c.get("Neutral", 0),
                "Negative": c.get("Negative", 0),
            }
        )
    rating_trend = []
    for d in sorted(rating_by_day):
        vals = rating_by_day[d]
        if vals:
            rating_trend.append({"date": d, "avg_rating": round(sum(vals) / len(vals), 2)})

    def _top_series(bucket: dict[str, Counter], n: int = 5) -> list[dict]:
        rows = []
        for period in sorted(bucket):
            for label, count in bucket[period].most_common(n):
                rows.append({"period": period, "label": label, "count": count})
        return rows

    return {
        "review_timeline": timeline,
        "sentiment_trend": sentiment_trend,
        "rating_trend": rating_trend,
        "daily_reviews": timeline,
        "weekly_reviews": [{"week": w, "count": weekly[w]} for w in sorted(weekly)],
        "monthly_reviews": [{"month": m, "count": monthly[m]} for m in sorted(monthly)],
        "top_keywords": [{"keyword": k, "count": v} for k, v in keywords.most_common(25)],
        "category_trend": _top_series(category_by_month),
        "pain_point_trend": _top_series(pain_by_week),
        "feature_request_trend": _top_series(request_by_week),
    }


def build_extended_analysis_sections(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    """Structured AI-facing sections derived from analyzed review fields (no extra API required)."""
    pain: Counter = Counter()
    features: Counter = Counter()
    requests: Counter = Counter()
    segments: Counter = Counter()
    opportunities: Counter = Counter()
    emerging: Counter = Counter()

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    for r in reviews:
        if r.get("pain_point"):
            pain[str(r["pain_point"])[:90]] += 1
        if r.get("user_intent") == "Appreciation" and r.get("theme"):
            features[str(r["theme"])[:90]] += 1
        if r.get("user_intent") == "Suggestion" or r.get("product_opportunity"):
            requests[
                str(r.get("product_opportunity") or r.get("theme") or "Request")[:100]
            ] += 1
        if r.get("customer_segment"):
            segments[str(r["customer_segment"])] += 1
        if r.get("product_opportunity"):
            opportunities[str(r["product_opportunity"])[:120]] += 1
        dt = _parse_dt(r.get("date") or r.get("fetched_at"))
        if dt and dt >= week_ago and (r.get("pain_point") or r.get("theme")):
            emerging[str(r.get("pain_point") or r.get("theme"))[:90]] += 1

    neg = sum(1 for r in reviews if (r.get("sentiment") or "").title() == "Negative")
    pos = sum(1 for r in reviews if (r.get("sentiment") or "").title() == "Positive")
    n = max(len(reviews), 1)
    confidence = min(95, max(35, int(40 + 40 * (sum(1 for r in reviews if r.get("theme")) / n))))

    top_pain = [{"label": k, "count": v} for k, v in pain.most_common(8)]
    top_feat = [{"label": k, "count": v} for k, v in features.most_common(8)]
    exec_bits = []
    if top_pain:
        exec_bits.append(f"Top pain points: {', '.join(p['label'] for p in top_pain[:3])}.")
    if top_feat:
        exec_bits.append(f"Most appreciated themes: {', '.join(f['label'] for f in top_feat[:3])}.")
    exec_bits.append(
        f"Sentiment mix across {len(reviews):,} reviews: "
        f"{round(100*pos/n)}% positive, {round(100*neg/n)}% negative."
    )

    return {
        "executive_summary": " ".join(exec_bits),
        "top_pain_points": top_pain,
        "top_appreciated_features": top_feat,
        "emerging_problems": [{"label": k, "count": v} for k, v in emerging.most_common(8)],
        "new_trends": [{"label": k, "count": v} for k, v in emerging.most_common(5)],
        "feature_requests": [{"label": k, "count": v} for k, v in requests.most_common(8)],
        "customer_segments": [{"label": k, "count": v} for k, v in segments.most_common(8)],
        "product_opportunities": [
            {"label": k, "count": v} for k, v in opportunities.most_common(8)
        ],
        "growth_recommendations": [
            f"Address rising pain: {p['label']}" for p in top_pain[:3]
        ]
        + [
            f"Double-down on appreciated theme: {f['label']}" for f in top_feat[:2]
        ],
        "pm_recommendations": [
            f"Prioritize fix for '{p['label']}' ({p['count']} mentions)."
            for p in top_pain[:4]
        ]
        + [
            f"Ship discovery experiment for '{label[:80]}'."
            for label, _count in opportunities.most_common(3)
        ],
        "confidence_score": confidence,
    }


def build_filtered_dashboard(
    *,
    data_source: str = "combined",
    date_range: str = "all",
    platform: str = "both",
    ratings: list[int] | None = None,
    sentiments: list[str] | None = None,
    limit: int = 2000,
) -> dict[str, Any]:
    """
    Full filtered payload for Customer Insights.

    Reuses Gemini discovery when possible; never crashes on Gemini failure.
    """
    from src.discovery_insights import build_discovery_dashboard

    reviews = apply_review_filters(
        data_source=data_source,
        date_range=date_range,
        platform=platform,
        ratings=ratings,
        sentiments=sentiments,
        limit=limit,
    )

    try:
        base = build_discovery_dashboard(
            reviews=reviews, limit=limit, analysis_mode=data_source
        )
    except Exception as exc:
        logger.exception("Filtered discovery dashboard failed")
        base = {
            "reviews": reviews,
            "insights": (
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
                    "ai_summary": f"Insights temporarily unavailable: {exc}",
                    "category_exploration_barriers": [],
                    "exploration_potential_segments": [],
                    "all_segments": [],
                    "recommended_product_opportunities": [],
                }
            ),
            "sentiment": {},
            "discovery": {"source": "fallback-error", "ai_confidence_score": 0},
            "validation": {},
            "review_sources": {},
            "review_kpis": {},
        }

    warehouse = get_review_warehouse_stats(live_window_days=LIVE_REVIEW_WINDOW_DAYS)
    trends = compute_trend_insights(reviews)
    charts = compute_chart_series(reviews)
    extended = build_extended_analysis_sections(reviews)

    # Enrich discovery with extended sections when Gemini omitted them
    discovery = dict(base.get("discovery") or {})
    discovery.setdefault("executive_summary", extended["executive_summary"])
    discovery.setdefault("top_pain_points", extended["top_pain_points"])
    discovery.setdefault("top_appreciated_features", extended["top_appreciated_features"])
    discovery.setdefault("emerging_problems", extended["emerging_problems"])
    discovery.setdefault("new_trends", extended["new_trends"])
    discovery.setdefault("feature_requests", extended["feature_requests"])
    discovery.setdefault("customer_segments_detail", extended["customer_segments"])
    discovery.setdefault("product_opportunities_detail", extended["product_opportunities"])
    discovery.setdefault("growth_recommendations_extra", extended["growth_recommendations"])
    discovery.setdefault("pm_recommendations", extended["pm_recommendations"])
    if not discovery.get("ai_confidence_score"):
        discovery["ai_confidence_score"] = extended["confidence_score"]
    discovery["analysis_mode"] = data_source

    base["discovery"] = discovery
    base["reviews"] = reviews
    base["warehouse_stats"] = warehouse
    base["trend_insights"] = trends
    base["chart_series"] = charts
    base["extended_analysis"] = extended
    base["filter_meta"] = {
        "data_source": data_source,
        "date_range": date_range,
        "platform": platform,
        "ratings": ratings or [],
        "sentiments": sentiments or [],
        "review_count": len(reviews),
        "live_window_days": LIVE_REVIEW_WINDOW_DAYS,
        "historical_date_range": historical_range_label(),
        "live_date_range": live_range_label(),
        "historical_start": HISTORICAL_START_DATE.isoformat(),
        "historical_end": HISTORICAL_END_DATE.isoformat(),
        "live_start": LIVE_START_DATE.isoformat(),
    }
    # Refresh KPIs for filtered set
    base["review_kpis"] = {
        **(base.get("review_kpis") or {}),
        "Total Reviews": len(reviews),
        "Analyzed Reviews": sum(1 for r in reviews if r.get("theme") or r.get("analyzed")),
        "Average Rating": (
            round(
                sum(float(r["rating"]) for r in reviews if r.get("rating") is not None)
                / max(1, sum(1 for r in reviews if r.get("rating") is not None)),
                2,
            )
            if any(r.get("rating") is not None for r in reviews)
            else None
        ),
    }
    return base
