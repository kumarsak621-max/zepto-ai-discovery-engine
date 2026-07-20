"""
Zepto AI Discovery Engine
AI-Powered Customer Intelligence Assistant for Product Managers

Streamlit Community Cloud entry point:
  streamlit run app.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv()
except ImportError:
    pass

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Dashboard · Zepto AI Discovery Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _format_last_updated(ts: str | None) -> str:
    """Format fetch timestamp as DD MMM YYYY HH:MM."""
    if not ts:
        return "—"
    raw = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%d %b %Y %H:%M")
    except ValueError:
        pass
    # Fallback: trim ISO-like strings
    cleaned = raw.replace("T", " ")[:16]
    try:
        dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M")
        return dt.strftime("%d %b %Y %H:%M")
    except ValueError:
        return cleaned or "—"


def _source_label(source: Any) -> str:
    key = str(source or "").strip().lower()
    if key in {"playstore", "google play", "google_play"}:
        return "Google Play"
    if key in {"appstore", "apple app store", "app_store", "ios"}:
        return "Apple App Store"
    return str(source or "Unknown").replace("_", " ").title()


def _load_latest_reviews(limit: int = 20) -> pd.DataFrame:
    from src.database import fetch_all_reviews

    rows = fetch_all_reviews(limit=max(limit * 5, 200))
    if not rows:
        return pd.DataFrame(columns=["Source", "Rating", "Review", "Date"])

    df = pd.DataFrame(rows)
    if "source" in df.columns:
        allowed = {"playstore", "appstore"}
        df = df[df["source"].astype(str).str.lower().isin(allowed)].copy()
    if df.empty:
        return pd.DataFrame(columns=["Source", "Rating", "Review", "Date"])

    if "date" in df.columns:
        df["_sort_date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df = df.sort_values("_sort_date", ascending=False, na_position="last")
    else:
        df["_sort_date"] = pd.NaT

    out = pd.DataFrame(
        {
            "Source": df["source"].map(_source_label) if "source" in df.columns else "—",
            "Rating": df["rating"] if "rating" in df.columns else None,
            "Review": df["text"] if "text" in df.columns else "",
            "Date": df["_sort_date"].dt.strftime("%d %b %Y"),
        }
    )
    out["Date"] = out["Date"].fillna("—")
    out["Review"] = out["Review"].fillna("").astype(str)
    return out.head(limit).reset_index(drop=True)


def render_dashboard() -> None:
    """Executive Dashboard — KPIs, live stats, review feed, refresh."""
    from src.auto_bootstrap import (
        ensure_live_reviews_loaded,
        render_auto_collect_warning,
    )
    from src.data_pipeline import get_live_meta
    from src.paths import ensure_runtime_dirs
    from src.streamlit_cache import (
        cached_collection_stats,
        cached_pm_insights,
        clear_data_caches,
    )

    try:
        ensure_runtime_dirs()
        from src.database import init_db

        init_db()
    except Exception as exc:
        st.error(
            "Could not prepare the app storage folders or database. "
            f"Please retry in a moment. Details: {exc}"
        )
        st.stop()

    # Automatic collection on first visit this session
    ensure_live_reviews_loaded()

    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');

html, body, [class*="css"] {
  font-family: 'DM Sans', sans-serif;
}
h1, h2, h3 {
  font-family: 'Fraunces', Georgia, serif !important;
  letter-spacing: -0.02em;
}
div[data-testid="stMetric"] {
  background: #F7FBF8;
  border: 1px solid #D8F3DC;
  border-radius: 12px;
  padding: 0.75rem 1rem;
}
</style>
""",
        unsafe_allow_html=True,
    )

    st.title("Zepto AI Discovery Engine")
    st.caption(
        "AI-powered customer feedback analysis platform for Product Managers."
    )

    render_auto_collect_warning()

    header_l, header_r = st.columns([3, 1])
    with header_r:
        refresh = st.button(
            "🔄 Refresh Reviews",
            type="primary",
            use_container_width=True,
            key="dashboard_refresh_reviews",
        )

    if refresh:
        with st.spinner(
            "Fetching latest Google Play and App Store reviews, updating analysis…"
        ):
            from src.auto_bootstrap import ensure_live_reviews_loaded as _reload

            result = _reload(force=True)
            clear_data_caches()
        if result.get("status") == "success":
            st.success("Reviews refreshed and analysis updated.")
        else:
            st.warning(
                "Unable to fetch latest reviews. Displaying the most recently analyzed dataset."
            )
        st.rerun()

    try:
        stats = cached_collection_stats()
        insights = cached_pm_insights(limit=2000)
        live_meta = get_live_meta() or {}
        from src.streamlit_cache import cached_warehouse_stats
        from src.review_sync import get_refresh_status

        warehouse = cached_warehouse_stats()
        refresh = get_refresh_status()
    except Exception as exc:
        st.error(f"Could not load dashboard metrics right now. Details: {exc}")
        stats, insights, live_meta = {"total": 0, "by_sentiment": {}}, {}, {}
        warehouse, refresh = {}, {}

    by_sentiment = stats.get("by_sentiment") or {}
    positive = int(by_sentiment.get("Positive") or 0)
    negative = int(by_sentiment.get("Negative") or 0)
    playstore = int(live_meta.get("playstore_count") or 0)
    appstore = int(live_meta.get("appstore_count") or 0)
    # Fallback to DB source breakdown when meta is empty
    by_source = stats.get("by_source") or {}
    if playstore <= 0:
        playstore = int(by_source.get("playstore") or 0)
    if appstore <= 0:
        appstore = int(by_source.get("appstore") or 0)

    growth_opps = len(insights.get("recommended_product_opportunities") or [])
    if growth_opps == 0:
        growth_opps = len(insights.get("most_frequent_themes") or [])

    st.caption(
        f"🟢 LIVE · 📚 Historical · {_format_last_updated(refresh.get('last_sync_at') or live_meta.get('last_updated'))} · "
        f"Next refresh: {_format_last_updated(refresh.get('next_refresh_at'))}"
    )

    with st.container():
        w1 = st.columns(3)
        w1[0].metric(
            "Total Historical Reviews",
            f"{int(warehouse.get('total_historical') or stats.get('total') or 0):,}",
        )
        w1[1].metric("Total Live Reviews", f"{int(warehouse.get('total_live') or 0):,}")
        w1[2].metric(
            "Merged Reviews",
            f"{int(warehouse.get('merged_reviews') or stats.get('total') or 0):,}",
        )
        w2 = st.columns(3)
        w2[0].metric("New Reviews Today", f"{int(warehouse.get('new_reviews_today') or 0):,}")
        w2[1].metric(
            "New Reviews This Week",
            f"{int(warehouse.get('new_reviews_this_week') or 0):,}",
        )
        w2[2].metric(
            "Last Sync Time",
            _format_last_updated(
                warehouse.get("last_sync_time")
                or refresh.get("last_sync_at")
                or live_meta.get("last_updated")
            ),
        )
        st.caption(
            f"Latest Review Date: {_format_last_updated(warehouse.get('latest_review_date'))}"
        )

    with st.container():
        r1 = st.columns(3)
        r1[0].metric("Total Reviews", f"{int(stats.get('total') or 0):,}")
        r1[1].metric("Google Play Reviews", f"{playstore:,}")
        r1[2].metric("Apple App Store Reviews", f"{appstore:,}")

        r2 = st.columns(3)
        r2[0].metric("Positive Sentiment", f"{positive:,}")
        r2[1].metric("Negative Sentiment", f"{negative:,}")
        r2[2].metric("Growth Opportunities", f"{growth_opps:,}")

    st.markdown("## Live Customer Reviews")

    with st.container():
        s1, s2, s3 = st.columns(3)
        s1.markdown(f"**Google Play Reviews:** {playstore:,}")
        s2.markdown(f"**Apple App Store Reviews:** {appstore:,}")
        s3.markdown(
            f"**Last Updated:** {_format_last_updated(live_meta.get('last_updated'))}"
        )

    try:
        feed = _load_latest_reviews(limit=20)
    except Exception as exc:
        st.warning(f"Could not load the live review feed. Details: {exc}")
        feed = pd.DataFrame(columns=["Source", "Rating", "Review", "Date"])

    if feed.empty:
        st.info(
            "No live reviews to display yet. Click **🔄 Refresh Reviews** to collect "
            "the latest Google Play and App Store feedback."
        )
    else:
        st.dataframe(
            feed,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Source": st.column_config.TextColumn("Source", width="small"),
                "Rating": st.column_config.NumberColumn("Rating", format="%.1f"),
                "Review": st.column_config.TextColumn("Review", width="large"),
                "Date": st.column_config.TextColumn("Date", width="small"),
            },
        )


# ---------------------------------------------------------------------------
# Navigation: Dashboard (default) · Customer Insights · Chatbot
# Using st.navigation so the sidebar labels match the product IA.
# Existing page files are unchanged (backend / charts / chatbot preserved).
# ---------------------------------------------------------------------------
dashboard_page = st.Page(
    render_dashboard,
    title="Dashboard",
    icon="📊",
    default=True,
)
insights_page = st.Page(
    "pages/1_Customer_Insights.py",
    title="Customer Insights",
    icon="📈",
)
chatbot_page = st.Page(
    "pages/2_AI_Product_Manager_Chatbot.py",
    title="AI Product Manager Chatbot",
    icon="🤖",
)

pg = st.navigation([dashboard_page, insights_page, chatbot_page])
pg.run()
