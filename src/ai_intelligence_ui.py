"""
AI-Powered Customer Feedback Intelligence — dashboard hero section.

Additive UI only. Reuses existing warehouse stats, PM insights, and Gemini status.
Does not replace Customer Insights, charts, or review collection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st


def _fmt_ts(ts: Any) -> str:
    if not ts:
        return "—"
    raw = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d %b %Y %H:%M")
    except ValueError:
        cleaned = raw.replace("T", " ")[:16]
        return cleaned or "—"


def _as_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for x in value:
            if isinstance(x, str) and x.strip():
                out.append(x.strip())
            elif isinstance(x, dict):
                label = x.get("label") or x.get("pain_point") or x.get("text")
                if label:
                    out.append(str(label))
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _overall_sentiment(by_sentiment: dict[str, Any]) -> str:
    pos = int(by_sentiment.get("Positive") or 0)
    neg = int(by_sentiment.get("Negative") or 0)
    neu = int(by_sentiment.get("Neutral") or 0)
    total = pos + neg + neu
    if total <= 0:
        return "Awaiting analysis"
    if pos >= neg and pos >= neu:
        return f"Positive ({pos:,} / {total:,})"
    if neg >= pos and neg >= neu:
        return f"Negative ({neg:,} / {total:,})"
    return f"Neutral ({neu:,} / {total:,})"


def _analysis_status_label(
    *,
    analyzed: int,
    pending: int,
    processing: bool,
    gemini_ok: bool,
) -> tuple[str, str]:
    """Return (indicator_line, status_word)."""
    if processing:
        return "🟡 AI Analysis Running", "Processing"
    if pending > 0 and gemini_ok:
        return "🟡 AI Analysis Waiting", "Waiting"
    if analyzed > 0:
        if gemini_ok:
            return "🟢 AI Analysis Running", "Success"
        return "🟠 AI Analysis Cached", "Success"
    return "⚪ AI Analysis Waiting", "Waiting"


def build_ai_intelligence_snapshot(
    *,
    stats: dict[str, Any] | None = None,
    insights: dict[str, Any] | None = None,
    discovery: dict[str, Any] | None = None,
    live_meta: dict[str, Any] | None = None,
    processing: bool = False,
) -> dict[str, Any]:
    """Assemble live AI metrics from existing cached payloads."""
    stats = stats or {}
    insights = insights or {}
    discovery = discovery or {}
    live_meta = live_meta or {}

    total = int(stats.get("total") or 0)
    analyzed = int(
        stats.get("analyzed_count")
        or insights.get("analyzed_count")
        or 0
    )
    pending = int(stats.get("pending_analysis") or max(0, total - analyzed))
    by_sentiment = stats.get("by_sentiment") or {}

    conf = (
        discovery.get("ai_confidence_score")
        or discovery.get("theme_confidence_score")
    )
    if conf is None and total > 0:
        conf = round(100.0 * analyzed / max(total, 1), 1)
    conf = float(conf or 0)

    gemini_ok = True
    gemini_issue: str | None = None
    try:
        from src.config import has_gemini
        from src.gemini_debug import get_ai_debug_snapshot
        from src.gemini_key_manager import gemini_status

        gemini_ok = bool(has_gemini())
        if not gemini_ok:
            gemini_issue = "No Gemini API keys configured"
        gstat = gemini_status()
        dbg = get_ai_debug_snapshot()
        # Only mark unhealthy when the latest AI debug event failed, or manager
        # reports failures with zero successes in this process.
        if dbg and dbg.get("ok") is False and dbg.get("exception_message"):
            gemini_ok = False
            gemini_issue = str(dbg.get("exception_message"))
        elif int(gstat.get("total_keys") or 0) > 0 and int(
            gstat.get("successful_requests") or 0
        ) == 0 and int(gstat.get("failed_requests") or 0) > 0:
            gemini_ok = False
            gemini_issue = str(gstat.get("last_error") or "Gemini requests failing")
        disc_src = str((discovery or {}).get("source") or "")
        if disc_src.startswith("fallback-") and disc_src not in {
            "fallback",
        }:
            # Evidence fallback due to AI/config failure
            if disc_src not in {"fallback-invalid-payload"} or (discovery or {}).get(
                "error_message"
            ):
                if (discovery or {}).get("error_message") or disc_src.startswith(
                    ("fallback-all-keys", "fallback-error", "fallback-timeout", "fallback-no-keys", "fallback-auth")
                ):
                    gemini_ok = False
                    gemini_issue = str(
                        (discovery or {}).get("error_message")
                        or f"Discovery source={disc_src}"
                    )
    except Exception as exc:
        gemini_ok = False
        gemini_issue = str(exc)
        print(f"[AI DEBUG] gemini_ok status check failed: {exc}", flush=True)
        try:
            from src.gemini_debug import record_ai_failure

            record_ai_failure(exc, stage="ai_intelligence_status_check")
        except Exception:
            pass

    indicator, status_word = _analysis_status_label(
        analyzed=analyzed,
        pending=pending,
        processing=processing,
        gemini_ok=gemini_ok,
    )

    last_ai = (
        stats.get("last_ai_analysis")
        or live_meta.get("last_updated")
        or stats.get("last_update")
    )

    # New reviews since last analysis ≈ pending unanalyzed rows
    new_since = pending

    return {
        "reviews_processed": total,
        "reviews_analyzed": analyzed,
        "pending_analysis": pending,
        "new_since_last_analysis": new_since,
        "last_ai_analysis": last_ai,
        "last_updated": live_meta.get("last_updated") or stats.get("last_update"),
        "overall_sentiment": _overall_sentiment(by_sentiment),
        "ai_confidence": conf,
        "status_indicator": indicator,
        "analysis_status": status_word,
        "gemini_ok": gemini_ok,
        "gemini_issue": gemini_issue,
        "executive_summary": (
            discovery.get("executive_summary")
            or insights.get("ai_summary")
            or "AI analysis will appear as reviews are processed."
        ),
        "top_pain_points": _as_records(
            discovery.get("top_pain_points") or insights.get("top_customer_problems")
        ),
        "appreciated_features": _as_records(
            discovery.get("top_appreciated_features")
        ),
        "feature_requests": _as_records(discovery.get("feature_requests")),
        "emerging_trends": _as_records(
            discovery.get("new_trends") or discovery.get("emerging_problems")
        ),
        "product_opportunities": _as_records(
            discovery.get("product_opportunities_detail")
            or discovery.get("product_opportunities")
            or insights.get("recommended_product_opportunities")
        ),
        "customer_segments": _as_records(
            discovery.get("customer_segments_detail")
            or insights.get("all_segments")
            or insights.get("exploration_potential_segments")
        ),
        "root_causes": _as_records(insights.get("root_causes")),
        "growth_opportunities": _as_str_list(
            discovery.get("growth_recommendations_extra")
            or discovery.get("growth_recommendations")
            or insights.get("recommended_product_opportunities")
        ),
        "pm_recommendations": _as_str_list(
            discovery.get("pm_recommendations") or insights.get("ai_summary")
        ),
        "business_impact": (
            discovery.get("business_impact")
            or insights.get("ai_summary")
            or "Impact assessment updates as AI completes review analysis."
        ),
    }


def ensure_incremental_ai_analysis(*, batch_size: int = 100) -> dict[str, Any]:
    """
    Analyze only newly collected (unanalyzed) reviews once per session.

    Never reprocesses already-analyzed rows. Safe no-op when nothing pending.
    """
    if st.session_state.get("_ai_incremental_done"):
        return {"status": "skipped", "analyzed": 0}

    try:
        from src.database import fetch_unanalyzed
        from src.data_pipeline import run_analysis
        from src.streamlit_cache import clear_data_caches

        pending = fetch_unanalyzed(limit=1)
        if not pending:
            st.session_state["_ai_incremental_done"] = True
            return {"status": "success", "analyzed": 0, "message": "up_to_date"}

        with st.spinner("AI is analyzing newly collected reviews…"):
            n = run_analysis(batch_size=batch_size)
            clear_data_caches()
        st.session_state["_ai_incremental_done"] = True
        return {"status": "success", "analyzed": int(n or 0)}
    except Exception as exc:
        # Keep dashboard usable with last successful analysis
        st.session_state["_ai_incremental_done"] = True
        return {"status": "cached", "analyzed": 0, "error": str(exc)}


def _priority_buckets(items: list[dict[str, Any]]) -> dict[str, list[str]]:
    labels: list[str] = []
    for item in items:
        label = item.get("label") or item.get("pain_point") or item.get("theme")
        if label:
            labels.append(str(label))
    return {
        "High": labels[:3],
        "Medium": labels[3:6],
        "Low": labels[6:9],
    }


def render_ai_intelligence_section(
    *,
    stats: dict[str, Any] | None = None,
    insights: dict[str, Any] | None = None,
    discovery: dict[str, Any] | None = None,
    live_meta: dict[str, Any] | None = None,
    processing: bool = False,
) -> dict[str, Any]:
    """Prominent dashboard hero: AI-Powered Customer Feedback Intelligence."""
    snap = build_ai_intelligence_snapshot(
        stats=stats,
        insights=insights,
        discovery=discovery,
        live_meta=live_meta,
        processing=processing,
    )

    st.markdown("---")
    st.markdown("## 🧠 AI-Powered Customer Feedback Intelligence")
    st.markdown(
        "Continuously analyzes customer feedback at scale to uncover trends, "
        "customer pain points, feature requests, product opportunities, and "
        "actionable product insights."
    )

    st.markdown(
        f"**{snap['status_indicator']}** · "
        f"Last Updated: **{_fmt_ts(snap['last_updated'])}** · "
        f"Reviews Processed: **{int(snap['reviews_processed']):,}** · "
        f"Analysis Status: **{snap['analysis_status']}**"
    )

    if not snap.get("gemini_ok") and int(snap.get("reviews_analyzed") or 0) > 0:
        try:
            from src.gemini_status_ui import render_gemini_all_keys_failed_warning

            render_gemini_all_keys_failed_warning(discovery=discovery)
        except Exception as exc:
            print(f"[AI DEBUG] warning render failed: {exc}", flush=True)
            st.info(
                "Showing the most recent successful AI analysis. "
                "New analysis will retry automatically when Gemini is available."
            )
            try:
                from src.gemini_status_ui import render_ai_debug_expander

                render_ai_debug_expander(exc, discovery=discovery, expanded=True)
            except Exception as nested:
                print(f"[AI DEBUG] debug expander failed: {nested}", flush=True)

    m1 = st.columns(4)
    m1[0].metric("Reviews Processed", f"{int(snap['reviews_processed']):,}")
    m1[1].metric("Reviews Analyzed by AI", f"{int(snap['reviews_analyzed']):,}")
    m1[2].metric("Last AI Analysis Time", _fmt_ts(snap["last_ai_analysis"]))
    m1[3].metric("AI Processing Status", snap["analysis_status"])

    m2 = st.columns(3)
    m2[0].metric(
        "New Reviews Since Last Analysis",
        f"{int(snap['new_since_last_analysis']):,}",
    )
    m2[1].metric("Overall Customer Sentiment", snap["overall_sentiment"])
    m2[2].metric("AI Confidence Score", f"{float(snap['ai_confidence']):.0f}%")

    with st.expander("AI Capabilities & Latest Insights", expanded=True):
        st.subheader("Executive Summary")
        st.write(snap["executive_summary"])

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Top Customer Pain Points**")
            for item in snap["top_pain_points"][:6]:
                st.write(
                    f"- {item.get('label') or item.get('pain_point')} "
                    f"({item.get('count', 0)})"
                )
            st.markdown("**Feature Requests**")
            for item in snap["feature_requests"][:5]:
                st.write(f"- {item.get('label')} ({item.get('count', 0)})")
            st.markdown("**Emerging Trends**")
            for item in snap["emerging_trends"][:5]:
                st.write(f"- {item.get('label')} ({item.get('count', 0)})")
            st.markdown("**Root Cause Analysis**")
            for item in snap["root_causes"][:5]:
                st.write(
                    f"- {item.get('label') or item.get('root_cause')} "
                    f"({item.get('count', 0)})"
                )
        with c2:
            st.markdown("**Most Appreciated Features**")
            for item in snap["appreciated_features"][:6]:
                st.write(f"- {item.get('label')} ({item.get('count', 0)})")
            st.markdown("**Product Opportunities**")
            for item in snap["product_opportunities"][:6]:
                label = item.get("label") or item.get("opportunity") or item.get("theme")
                st.write(f"- {label} ({item.get('count', 0)})")
            st.markdown("**Customer Segments**")
            for item in snap["customer_segments"][:5]:
                st.write(f"- {item.get('label')} ({item.get('count', 0)})")
            st.markdown("**Growth Opportunities**")
            for line in snap["growth_opportunities"][:6]:
                st.write(f"- {line}")

        st.markdown("**Business Impact Assessment**")
        st.write(snap["business_impact"])

        st.markdown("**Priority Matrix**")
        buckets = _priority_buckets(snap["top_pain_points"] or snap["product_opportunities"])
        p1, p2, p3 = st.columns(3)
        with p1:
            st.markdown("**High**")
            for x in buckets["High"] or ["—"]:
                st.write(f"- {x}")
        with p2:
            st.markdown("**Medium**")
            for x in buckets["Medium"] or ["—"]:
                st.write(f"- {x}")
        with p3:
            st.markdown("**Low**")
            for x in buckets["Low"] or ["—"]:
                st.write(f"- {x}")

        st.markdown("**PM Recommendations**")
        recs = snap["pm_recommendations"]
        if recs:
            for line in recs[:8]:
                st.write(f"- {line}")
        else:
            st.caption("Recommendations appear after AI analysis completes.")

        st.markdown("**Suggested Next Product Actions**")
        actions = snap["growth_opportunities"][:5] or [
            "Refresh reviews to pull the latest store feedback.",
            "Review high-priority pain points in Customer Insights.",
            "Validate opportunities with the AI Product Manager Chatbot.",
        ]
        for line in actions:
            st.write(f"- {line}")

    return snap
