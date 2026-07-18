"""Reusable Streamlit render helpers for the Customer Insights dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st


def render_root_cause_analysis(
    discovery: dict[str, Any],
    *,
    chart_layout: dict[str, Any],
) -> None:
    """Render 🧠 AI Root Cause Analysis + PM insights + prioritization."""
    st.markdown("---")
    st.header("🧠 AI Root Cause Analysis")
    st.caption(
        "Gemini explains why Zepto users repeatedly purchase familiar categories "
        "instead of exploring new ones — generated from the latest analyzed reviews."
    )

    rca = discovery.get("root_cause_analysis") or {}
    rca_causes = rca.get("causes") or []
    if not rca_causes:
        st.info(
            "Root cause analysis appears after Gemini discovery runs on analyzed reviews. "
            "Click **▶ Run Review Analysis** or refresh the page after analysis completes."
        )
        return

    avg_sev = sum(int(c.get("severity_score") or 0) for c in rca_causes) / max(
        len(rca_causes), 1
    )
    avg_conf = sum(int(c.get("ai_confidence") or 0) for c in rca_causes) / max(
        len(rca_causes), 1
    )
    top_cause = max(rca_causes, key=lambda c: int(c.get("severity_score") or 0))
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Root causes detected", f"{len(rca_causes)}")
    r2.metric("Avg severity (1–10)", f"{avg_sev:.1f}")
    r3.metric("Avg AI confidence", f"{avg_conf:.0f}%")
    r4.metric("Highest-impact cause", str(top_cause.get("root_cause") or "—")[:40])

    rca_df = pd.DataFrame(rca_causes)
    table_rename = {
        "root_cause": "Root Cause",
        "description": "Description",
        "frequency": "Frequency",
        "severity_score": "Severity Score (1–10)",
        "ai_confidence": "AI Confidence %",
        "example_review": "Example User Review",
        "suggested_product_opportunity": "Suggested Product Opportunity",
    }
    table_cols = [c for c in table_rename if c in rca_df.columns]
    st.dataframe(
        rca_df[table_cols].rename(columns=table_rename),
        use_container_width=True,
        hide_index=True,
    )

    c_bar, c_pie = st.columns(2)
    with c_bar:
        fig_rca_bar = px.bar(
            rca_df,
            x="frequency",
            y="root_cause",
            orientation="h",
            color="severity_score",
            color_continuous_scale=["#95D5B2", "#E9C46A", "#9B2226"],
            title="Root causes (frequency)",
        )
        fig_rca_bar.update_layout(
            yaxis={"categoryorder": "total ascending"},
            **chart_layout,
            height=400,
        )
        st.plotly_chart(fig_rca_bar, use_container_width=True)
    with c_pie:
        fig_rca_pie = px.pie(
            rca_df,
            names="root_cause",
            values="frequency",
            hole=0.4,
            title="Contribution of each root cause",
            color_discrete_sequence=px.colors.sequential.Tealgrn,
        )
        fig_rca_pie.update_layout(**chart_layout, height=400)
        st.plotly_chart(fig_rca_pie, use_container_width=True)

    with st.expander("Severity ranking", expanded=True):
        sev_df = rca_df.sort_values("severity_score", ascending=False)
        fig_sev = px.bar(
            sev_df,
            x="severity_score",
            y="root_cause",
            orientation="h",
            color="severity_score",
            color_continuous_scale=["#D8F3DC", "#9B2226"],
            title="Severity ranking (1–10)",
            range_x=[0, 10],
        )
        fig_sev.update_layout(
            yaxis={"categoryorder": "total ascending"},
            **chart_layout,
            height=360,
        )
        st.plotly_chart(fig_sev, use_container_width=True)

    st.subheader("Why Users Keep Buying the Same Categories")
    st.markdown(rca.get("summary") or "_Summary unavailable — re-run analysis._")

    st.subheader("Product Manager Insights")
    st.caption("Actionable insights that reference the detected root causes.")
    pm_insights = rca.get("pm_insights") or []
    if pm_insights:
        for i, insight in enumerate(pm_insights, 1):
            with st.container(border=True):
                st.markdown(f"**{i}.** {insight}")
    else:
        st.info("PM insights will appear after Gemini root-cause analysis.")

    st.subheader("Impact vs Effort Prioritization")
    prio_cols = [
        c
        for c in [
            "root_cause",
            "business_impact",
            "implementation_effort",
            "priority",
            "suggested_solution",
        ]
        if c in rca_df.columns
    ]
    if not prio_cols:
        return

    prio_df = rca_df[prio_cols].rename(
        columns={
            "root_cause": "Root Cause",
            "business_impact": "Business Impact",
            "implementation_effort": "Implementation Effort",
            "priority": "Priority",
            "suggested_solution": "Suggested Solution",
        }
    )
    if "Priority" in prio_df.columns:
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        prio_df = (
            prio_df.assign(
                _ord=prio_df["Priority"].map(lambda x: order.get(str(x), 9))
            )
            .sort_values("_ord")
            .drop(columns=["_ord"])
        )
    st.dataframe(prio_df, use_container_width=True, hide_index=True)

    impact_map = {"Low": 1, "Medium": 2, "High": 3}
    effort_map = {"Low": 1, "Medium": 2, "High": 3}
    scatter_df = rca_df.copy()
    scatter_df["impact_n"] = scatter_df["business_impact"].map(impact_map).fillna(2)
    scatter_df["effort_n"] = (
        scatter_df["implementation_effort"].map(effort_map).fillna(2)
    )
    fig_mat = px.scatter(
        scatter_df,
        x="effort_n",
        y="impact_n",
        size="frequency",
        color="priority",
        hover_name="root_cause",
        title="Impact vs Effort matrix",
        labels={
            "effort_n": "Implementation Effort",
            "impact_n": "Business Impact",
        },
        color_discrete_map={
            "P0": "#9B2226",
            "P1": "#E76F51",
            "P2": "#E9C46A",
            "P3": "#2A9D8F",
        },
    )
    fig_mat.update_xaxes(
        tickmode="array",
        tickvals=[1, 2, 3],
        ticktext=["Low", "Medium", "High"],
        range=[0.5, 3.5],
    )
    fig_mat.update_yaxes(
        tickmode="array",
        tickvals=[1, 2, 3],
        ticktext=["Low", "Medium", "High"],
        range=[0.5, 3.5],
    )
    fig_mat.update_layout(**chart_layout, height=380)
    st.plotly_chart(fig_mat, use_container_width=True)
