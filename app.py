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

from src.config import has_appstore, has_gemini, validate_runtime_config
from src.data_pipeline import get_live_meta
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import cached_collection_stats, cached_vector_stats
from src.streamlit_playstore import render_sidebar_fetch_controls
from src.streamlit_sources import render_live_review_controls, show_source_metrics

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
  <p>AI-powered customer intelligence for Product Managers — automatically collect, analyze, and act on live reviews.</p>
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

live_meta = get_live_meta()
st.subheader("Source metrics")
show_source_metrics(live_meta)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total in DB", f"{stats.get('total', 0):,}")
c2.metric(
    "Average Rating",
    f"{stats['avg_rating']:.2f}" if stats.get("avg_rating") is not None else "—",
)
c3.metric("Reviews in SQLite", f"{vs.get('count', 0):,}")
c4.metric("Sources active", len(stats.get("by_source") or {}))

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
        '<span class="status-pill ok">Google Play ready</span>',
        unsafe_allow_html=True,
    )
with col_c:
    if has_appstore():
        label, cls = "App Store ready", "ok"
    else:
        label, cls = "App Store off", "warn"
    st.markdown(
        f'<span class="status-pill {cls}">{label}</span>',
        unsafe_allow_html=True,
    )

st.markdown("---")
st.markdown(
    """
### What this tool does for PMs

1. **Collects** live Zepto reviews from Google Play and Apple App Store, plus optional manual CSV/Excel uploads
2. **Merges & deduplicates** feedback into `feedback.db`
3. **Analyzes** each item with Gemini for sentiment, theme, intent, and opportunities
4. **Powers the PM chatbot** using fetched review evidence from SQLite

Use the sidebar:

- **📂 Upload Manual Reviews** — CSV / Excel
- **Data Collection Status** — pipeline health & volume
- **Customer Insights** — complaints, themes, sentiment
- **AI Product Manager Chatbot** — ask research questions with evidence
"""
)

render_live_review_controls(key_prefix="home")

if stats.get("by_source"):
    st.subheader("Reviews collected by source")
    src_cols = st.columns(max(len(stats["by_source"]), 1))
    for i, (source_name, source_count) in enumerate(stats["by_source"].items()):
        src_cols[i % len(src_cols)].metric(
            str(source_name).replace("_", " ").title(),
            f"{source_count:,}",
        )
    st.bar_chart(stats["by_source"])
else:
    st.warning(
        "No feedback collected yet. Click **▶ Run Review Analysis** or "
        "**🔄 Refresh Live Reviews** to download online reviews automatically."
    )
