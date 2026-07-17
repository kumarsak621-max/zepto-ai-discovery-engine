"""
Zepto AI Discovery Engine
AI-Powered Customer Intelligence Assistant for Product Managers

Streamlit Community Cloud entry point:
  streamlit run app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Path bootstrap — must run before any `src.*` imports
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

from src.config import (
    PLAYSTORE_REVIEW_COUNT,
    has_gemini,
    has_reddit,
    validate_runtime_config,
)
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import cached_collection_stats, cached_vector_stats, clear_data_caches
from src.streamlit_playstore import (
    format_last_updated,
    render_last_updated_caption,
    render_sidebar_fetch_controls,
    run_fetch_with_progress,
    show_fetch_result,
)

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

_config_warnings = validate_runtime_config()

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
.status-pill {
  display: inline-block;
  padding: 0.25rem 0.7rem;
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 600;
}
.ok { background: #D8F3DC; color: #1B4332; }
.warn { background: #FFF3CD; color: #856404; }
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
  <p>AI-powered customer intelligence for Product Managers — automatically collect, analyze, and act on feedback.</p>
</div>
""",
    unsafe_allow_html=True,
)

for warning in _config_warnings:
    st.warning(warning)

render_sidebar_fetch_controls()

try:
    stats = cached_collection_stats()
    vs = cached_vector_stats()
except Exception as exc:
    st.error(f"Could not load dashboard metrics right now. Details: {exc}")
    stats, vs = {"total": 0, "by_source": {}, "avg_rating": None}, {"count": 0}

render_last_updated_caption()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Reviews", f"{stats.get('total', 0):,}")
c2.metric(
    "Average Rating",
    f"{stats['avg_rating']:.2f}" if stats.get("avg_rating") is not None else "—",
)
c3.metric("Reviews in SQLite", f"{vs.get('count', 0):,}")
c4.metric("Sources active", len(stats.get("by_source") or {}))
c5.metric("Last Updated", format_last_updated())

st.subheader("System readiness")
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.markdown(
        f'<span class="status-pill {"ok" if has_gemini() else "warn"}">'
        f'{"Gemini connected" if has_gemini() else "Gemini API key missing"}</span>',
        unsafe_allow_html=True,
    )
with col_b:
    st.markdown(
        f'<span class="status-pill {"ok" if has_reddit() else "warn"}">'
        f'{"Reddit connected" if has_reddit() else "Reddit credentials optional"}</span>',
        unsafe_allow_html=True,
    )
with col_c:
    st.markdown(
        '<span class="status-pill ok">Play Store scraper ready</span>',
        unsafe_allow_html=True,
    )

st.markdown("---")
st.markdown(
    """
### What this tool does for PMs

1. **Automatically collects** Play Store reviews and Reddit discussions about Zepto / quick commerce
2. **Cleans & deduplicates** feedback into `feedback.db`
3. **Analyzes** each item with Gemini for sentiment, theme, intent, and opportunities
4. **Powers the PM chatbot** by filtering relevant reviews from SQLite and synthesizing insights with Gemini

Use the sidebar pages:

- **Data Collection Status** — pipeline health & volume
- **Customer Insights** — complaints, themes, sentiment
- **AI Product Manager Chatbot** — ask research questions with evidence

### Quick actions
"""
)

force_home = st.checkbox(
    "Force refresh Play Store cache",
    value=False,
    key="home_force_playstore_refresh",
)

qa1, qa2, qa3 = st.columns(3)
with qa1:
    if st.button(
        "📥 Fetch Latest Google Play Reviews",
        type="primary",
        use_container_width=True,
        key="home_fetch_playstore",
    ):
        result = run_fetch_with_progress(
            force_refresh=force_home,
            count=PLAYSTORE_REVIEW_COUNT,
        )
        show_fetch_result(result)
        if result.get("status") == "success":
            clear_data_caches()
            st.rerun()

with qa2:
    if st.button("▶ Run full data pipeline", use_container_width=True):
        try:
            with st.spinner("Collecting all sources → cleaning → analyzing..."):
                from src.data_pipeline import run_full_pipeline

                result = run_full_pipeline()
            if result.get("status") == "success":
                clear_data_caches()
                st.success(
                    f"Pipeline OK — new: {result.get('new_reviews', 0)}, "
                    f"analyzed: {result.get('analyzed_count', 0)}"
                )
                st.rerun()
            else:
                st.error(
                    "Pipeline could not finish. "
                    f"{result.get('error', 'Please try again later.')}"
                )
        except Exception as exc:
            st.error(f"Pipeline failed unexpectedly. Details: {exc}")

with qa3:
    st.info(
        f"Fetches up to **{PLAYSTORE_REVIEW_COUNT}** English Google Play reviews for "
        f"`com.zeptoconsumerapp`, saves `data/reviews.csv`, caches while fresh, "
        "runs Gemini analysis, and refreshes Insights + Chatbot.\n\n"
        "Local daily job: `python scheduler.py`"
    )

if stats.get("by_source"):
    st.subheader("Feedback by source")
    st.bar_chart(stats["by_source"])
else:
    st.warning(
        "No feedback collected yet. Click **📥 Fetch Latest Google Play Reviews** "
        "in the sidebar (or below), or configure API keys in `.env` / Streamlit Secrets."
    )
