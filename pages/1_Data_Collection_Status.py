"""Page 1 — Data Collection Status"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import PLAYSTORE_APP_ID, PLAYSTORE_REVIEW_COUNT
from src.database import fetch_all_reviews, init_db
from src.paths import ensure_runtime_dirs
from src.streamlit_cache import cached_collection_stats, cached_vector_stats, clear_data_caches
from src.streamlit_playstore import (
    format_last_updated,
    render_last_updated_caption,
    render_sidebar_fetch_controls,
    run_fetch_with_progress,
    show_fetch_result,
)

st.set_page_config(page_title="Data Collection Status", page_icon="📊", layout="wide")

try:
    ensure_runtime_dirs()
    init_db()
except Exception as exc:
    st.error(f"Could not initialize storage. Details: {exc}")
    st.stop()

render_sidebar_fetch_controls()

st.title("📊 Data Collection Status")
st.caption("Automated ingestion health across Play Store, Reddit, and social sources.")
render_last_updated_caption()

try:
    stats = cached_collection_stats()
    vs = cached_vector_stats()
except Exception as exc:
    st.error(f"Could not load collection stats. Details: {exc}")
    st.stop()

last_run = stats.get("last_run")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Reviews", f"{stats['total']:,}")
m2.metric(
    "Average Rating",
    f"{stats['avg_rating']:.2f}" if stats.get("avg_rating") is not None else "—",
)
m3.metric("SQLite knowledge base", f"{vs.get('count', 0):,}")
m4.metric(
    "Sources",
    ", ".join(stats.get("by_source", {}).keys()) or "—",
)
m5.metric("Last Updated", format_last_updated())

st.markdown("---")
st.subheader("Source breakdown")
src = stats.get("by_source") or {}
if src:
    df_src = pd.DataFrame({"source": list(src.keys()), "count": list(src.values())})
    c1, c2 = st.columns([1, 1])
    with c1:
        st.dataframe(df_src, use_container_width=True, hide_index=True)
    with c2:
        st.bar_chart(df_src.set_index("source"))
else:
    st.info("No sources yet. Use **📥 Fetch Latest Google Play Reviews** in the sidebar.")

st.subheader("Latest pipeline run")
if last_run:
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Status", last_run.get("status", "—"))
    r2.metric("Play Store fetched", last_run.get("playstore_count", 0))
    r3.metric("Reddit fetched", last_run.get("reddit_count", 0))
    r4.metric("New after dedupe", last_run.get("new_reviews", 0))
    st.write(
        f"Started: `{last_run.get('started_at')}` · Finished: `{last_run.get('finished_at')}`"
    )
    if last_run.get("error_message"):
        st.error(last_run["error_message"])
else:
    st.write("No pipeline runs recorded yet.")

st.subheader("Recent collected feedback")
try:
    rows = fetch_all_reviews(limit=50)
except Exception as exc:
    st.error(f"Could not load recent feedback. Details: {exc}")
    rows = []

if rows:
    view = pd.DataFrame(rows)[
        [
            c
            for c in [
                "id",
                "source",
                "date",
                "rating",
                "sentiment",
                "theme",
                "user_intent",
                "text",
            ]
            if rows and c in rows[0]
        ]
    ]
    st.dataframe(view, use_container_width=True, hide_index=True)
else:
    st.write("Database is empty.")

st.markdown("---")
st.subheader("Fetch Google Play reviews")
st.caption(
    f"Pull up to **{PLAYSTORE_REVIEW_COUNT}** newest English reviews for "
    f"`{PLAYSTORE_APP_ID}`, dedupe into `data/reviews.csv` + `feedback.db`, "
    "then run Gemini analysis so Insights & Chatbot update automatically."
)

force = st.checkbox(
    "Force refresh (ignore cache)",
    value=False,
    key="data_page_force_playstore_refresh",
)

run_col1, run_col2, run_col3 = st.columns(3)
with run_col1:
    if st.button(
        "📥 Fetch Latest Google Play Reviews",
        type="primary",
        use_container_width=True,
        key="data_page_fetch_playstore",
    ):
        result = run_fetch_with_progress(force_refresh=force)
        show_fetch_result(result)
        if result.get("status") == "success":
            clear_data_caches()
            st.rerun()

with run_col2:
    if st.button("▶ Collect all sources + analyze", use_container_width=True):
        try:
            with st.spinner("Running full pipeline..."):
                from src.data_pipeline import run_full_pipeline

                result = run_full_pipeline()
            clear_data_caches()
            if result.get("status") == "success":
                st.success("Pipeline completed successfully.")
            else:
                st.error(result.get("error", "Pipeline failed"))
            st.json(result)
            st.rerun()
        except Exception as exc:
            st.error(f"Pipeline failed. Details: {exc}")

with run_col3:
    if st.button("↻ Analyze pending only", use_container_width=True):
        try:
            with st.spinner("Analyzing unanalyzed reviews..."):
                from src.data_pipeline import run_analysis

                a = run_analysis(batch_size=500)
            clear_data_caches()
            st.success(f"Analyzed {a} reviews")
            st.rerun()
        except Exception as exc:
            st.error(f"Analysis failed. Details: {exc}")
