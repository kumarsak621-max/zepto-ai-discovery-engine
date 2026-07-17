"""Page 1 — Data Collection Status"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database import fetch_all_reviews, get_collection_stats, init_db
from src.rag_pipeline import collection_stats

st.set_page_config(page_title="Data Collection Status", page_icon="📊", layout="wide")
init_db()

st.title("📊 Data Collection Status")
st.caption("Automated ingestion health across Play Store, Reddit, and social sources.")

stats = get_collection_stats()
vs = collection_stats()
last_run = stats.get("last_run")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total reviews collected", f"{stats['total']:,}")
m2.metric("SQLite knowledge base", f"{vs.get('count', 0):,}")
m3.metric(
    "Sources",
    ", ".join(stats.get("by_source", {}).keys()) or "—",
)
m4.metric(
    "Last update time",
    (stats.get("last_update") or "Never")[:19] if stats.get("last_update") else "Never",
)

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
    st.info("No sources yet. Run the pipeline from the Home page.")

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
rows = fetch_all_reviews(limit=50)
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
run_col1, run_col2 = st.columns(2)
with run_col1:
    if st.button("▶ Collect + analyze now", type="primary"):
        with st.spinner("Running full pipeline..."):
            from src.data_pipeline import run_full_pipeline

            result = run_full_pipeline()
        st.json(result)
        st.rerun()
with run_col2:
    if st.button("↻ Analyze pending only"):
        with st.spinner("Analyzing unanalyzed reviews..."):
            from src.data_pipeline import run_analysis

            a = run_analysis()
        st.success(f"Analyzed {a} reviews")
        st.rerun()
