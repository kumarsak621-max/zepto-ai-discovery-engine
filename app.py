"""
Zepto AI Discovery Engine
AI-Powered Customer Intelligence Assistant for Product Managers

Entry point for local + Railway:
  python app.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — must run before any `src.*` imports (Railway / python app.py)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv()
except ImportError:
    pass

_BOOTSTRAP_FLAG = "ZEPTO_STREAMLIT_BOOTSTRAPPED"


def _should_bootstrap_streamlit() -> bool:
    """Launch Streamlit only for a direct `python app.py` invocation."""
    if __name__ != "__main__":
        return False
    if os.environ.get(_BOOTSTRAP_FLAG) == "1":
        return False
    # Already inside Streamlit runtime (e.g. `streamlit run app.py`)
    if "streamlit.runtime" in sys.modules or "streamlit.web" in sys.modules:
        return False
    argv0 = Path(sys.argv[0]).name.lower()
    if "streamlit" in argv0:
        return False
    return True


if _should_bootstrap_streamlit():
    os.environ[_BOOTSTRAP_FLAG] = "1"
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        f"--server.port={port}",
        f"--server.address={host}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
    ]
    raise SystemExit(subprocess.call(cmd))


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------
import streamlit as st

from src.config import has_gemini, has_reddit, validate_runtime_config
from src.database import get_collection_stats, init_db
from src.rag_pipeline import collection_stats

_config_warnings = validate_runtime_config()

st.set_page_config(
    page_title="Zepto AI Discovery Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

try:
    init_db()
except Exception as exc:
    st.error(f"Failed to initialize database: {exc}")
    st.stop()

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

stats = get_collection_stats()
vs = collection_stats()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total feedback", f"{stats['total']:,}")
c2.metric("Reviews in SQLite", f"{vs.get('count', 0):,}")
c3.metric("Sources active", len(stats.get("by_source") or {}))
c4.metric(
    "Last update",
    (stats.get("last_update") or "—")[:19] if stats.get("last_update") else "—",
)

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

qa1, qa2 = st.columns(2)
with qa1:
    if st.button("▶ Run full data pipeline now", type="primary", use_container_width=True):
        with st.spinner("Collecting → cleaning → analyzing..."):
            from src.data_pipeline import run_full_pipeline

            result = run_full_pipeline()
        if result.get("status") == "success":
            st.success(
                f"Pipeline OK — new: {result.get('new_reviews', 0)}, "
                f"analyzed: {result.get('analyzed_count', 0)}"
            )
            st.rerun()
        else:
            st.error(f"Pipeline failed: {result.get('error', 'unknown error')}")

with qa2:
    st.info(
        "For unattended daily runs:\n\n"
        "`python scheduler.py`\n\n"
        "One-shot: `python scheduler.py --once`"
    )

if stats.get("by_source"):
    st.subheader("Feedback by source")
    st.bar_chart(stats["by_source"])
else:
    st.warning(
        "No feedback collected yet. Click **Run full data pipeline now** "
        "or configure API keys in `.env` / Railway variables and re-run."
    )
