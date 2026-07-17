"""Page 3 — AI Product Manager Chatbot"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.chatbot import EXAMPLE_QUESTIONS, SYSTEM_INTRO, ask_product_manager
from src.database import init_db
from src.rag_pipeline import collection_stats

st.set_page_config(page_title="AI Product Manager Chatbot", page_icon="🤖", layout="wide")
init_db()

st.title("🤖 AI Product Manager Chatbot")
st.caption(
    "Ask research questions. The assistant retrieves the latest collected reviews, "
    "then Gemini synthesizes insight, evidence, root cause, and product opportunity."
)

vs = collection_stats()
st.info(
    f"{SYSTEM_INTRO}  ·  Knowledge base: **{vs.get('count', 0)}** reviews in `feedback.db` "
    f"({vs.get('analyzed', 0)} analyzed)."
)

if "pm_messages" not in st.session_state:
    st.session_state.pm_messages = []

st.markdown("**Try a research prompt**")
cols = st.columns(2)
for i, q in enumerate(EXAMPLE_QUESTIONS):
    if cols[i % 2].button(q, use_container_width=True, key=f"ex_{i}"):
        st.session_state.pending_question = q

for msg in st.session_state.pm_messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("evidence"):
            with st.expander("Retrieved customer evidence"):
                for idx, ev in enumerate(msg["evidence"], 1):
                    st.markdown(
                        f"**{idx}.** _{ev.get('source')}_ · "
                        f"{ev.get('sentiment')} · {ev.get('theme')}\n\n"
                        f"> {ev.get('text')}"
                    )

prompt = st.chat_input("e.g. Why are Zepto users not trying personal care products?")
if "pending_question" in st.session_state:
    prompt = st.session_state.pop("pending_question")

if prompt:
    st.session_state.pm_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Filtering reviews from feedback.db → Gemini analysis..."):
            result = ask_product_manager(prompt)
        st.markdown(result["answer"])
        if result.get("evidence"):
            with st.expander("Retrieved customer evidence"):
                for idx, ev in enumerate(result["evidence"], 1):
                    header = " · ".join(
                        filter(
                            None,
                            [
                                f"_{ev.get('source')}_" if ev.get("source") else "",
                                ev.get("sentiment"),
                                ev.get("theme"),
                                ev.get("customer_segment"),
                            ],
                        )
                    )
                    st.markdown(f"**{idx}.** {header}")
                    if ev.get("review_summary"):
                        st.markdown(f"*Summary:* {ev['review_summary']}")
                    st.markdown(f"> {ev.get('text')}")
                    if ev.get("pain_point"):
                        st.caption(f"Pain: {ev['pain_point']}")
                    if ev.get("product_opportunity"):
                        st.caption(f"Opportunity: {ev['product_opportunity']}")

    st.session_state.pm_messages.append(
        {
            "role": "assistant",
            "content": result["answer"],
            "evidence": result.get("evidence") or [],
        }
    )

if st.button("Clear conversation"):
    st.session_state.pm_messages = []
    st.rerun()
