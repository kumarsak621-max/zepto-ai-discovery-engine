"""
Zepto AI Discovery Engine
AI-Powered Customer Intelligence Assistant for Product Managers

Streamlit Community Cloud entry point:
  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv()
except ImportError:
    pass

import streamlit as st

from src.auto_bootstrap import (
    ensure_live_reviews_loaded,
    render_auto_collect_warning,
    render_auto_status_sidebar,
)
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import cached_collection_stats, cached_pm_insights

st.set_page_config(
    page_title="Zepto AI Discovery Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
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

# Automatic Play Store + App Store collection + Gemini analysis (once per session)
ensure_live_reviews_loaded()
render_auto_status_sidebar()

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
.hero {
  background: linear-gradient(135deg, #0B1F17 0%, #1A4D3A 45%, #2D6A4F 100%);
  color: #F1FAEE;
  padding: 2.2rem 2rem;
  border-radius: 18px;
  margin-bottom: 1.5rem;
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: "";
  position: absolute;
  right: -40px; top: -40px;
  width: 220px; height: 220px;
  background: radial-gradient(circle, rgba(149,213,178,0.35), transparent 70%);
}
.hero h1 { color: #F1FAEE !important; margin: 0 0 0.4rem 0; font-size: 2.1rem; }
.hero p { color: #B7E4C7; margin: 0; font-size: 1.05rem; }
.platform-list {
  margin: 0.5rem 0 1.5rem 0;
  padding-left: 1.2rem;
  color: #1B4332;
  line-height: 1.7;
}
@media (max-width: 768px) {
  .hero { padding: 1.4rem 1.1rem; }
  .hero h1 { font-size: 1.55rem !important; }
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="hero">
  <h1>Zepto AI Discovery Engine</h1>
  <p>AI-powered customer feedback analysis platform for Product Managers.</p>
</div>
""",
    unsafe_allow_html=True,
)

render_auto_collect_warning()

st.markdown("The platform automatically:")
st.markdown(
    """
<div class="platform-list">
  <ul>
    <li>Collects customer reviews</li>
    <li>Performs AI sentiment analysis</li>
    <li>Detects customer pain points</li>
    <li>Identifies shopping habits</li>
    <li>Segments users</li>
    <li>Discovers product opportunities</li>
    <li>Generates actionable PM recommendations</li>
  </ul>
</div>
""",
    unsafe_allow_html=True,
)

try:
    stats = cached_collection_stats()
    insights = cached_pm_insights(limit=2000)
except Exception as exc:
    st.error(f"Could not load dashboard metrics right now. Details: {exc}")
    stats, insights = {"total": 0, "by_sentiment": {}}, {}

by_sentiment = stats.get("by_sentiment") or {}
positive = int(by_sentiment.get("Positive") or 0)
pain_points = len(insights.get("top_customer_problems") or [])
growth_opps = len(insights.get("recommended_product_opportunities") or [])
if growth_opps == 0:
    growth_opps = len(insights.get("most_frequent_themes") or [])

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Reviews", f"{int(stats.get('total') or 0):,}")
k2.metric("Positive Sentiment", f"{positive:,}")
k3.metric("Pain Points", f"{pain_points:,}")
k4.metric("Growth Opportunities", f"{growth_opps:,}")
