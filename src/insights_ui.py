"""Reusable Streamlit render helpers for the Customer Insights dashboard."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st


def _has_cols(df: pd.DataFrame, cols: list[str]) -> bool:
    return bool(df is not None and not df.empty and all(c in df.columns for c in cols))


def _safe_plotly(fig: Any, *, chart_layout: dict[str, Any], height: int | None = None) -> None:
    try:
        if height is not None:
            fig.update_layout(**chart_layout, height=height)
        else:
            fig.update_layout(**chart_layout)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.warning(f"Chart could not be rendered. Details: {exc}")


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

    try:
        rca = discovery.get("root_cause_analysis") or {}
        if not isinstance(rca, dict):
            rca = {}
        raw_causes = rca.get("causes") or []
        if not isinstance(raw_causes, list):
            raw_causes = []

        # Normalize rows so UI columns always exist
        rca_causes: list[dict[str, Any]] = []
        for row in raw_causes:
            if not isinstance(row, dict):
                continue
            try:
                freq = int(float(row.get("frequency") or 0))
            except (TypeError, ValueError):
                freq = 0
            try:
                sev = int(float(row.get("severity_score") or 5))
            except (TypeError, ValueError):
                sev = 5
            sev = max(1, min(10, sev))
            try:
                conf = int(float(row.get("ai_confidence") or 70))
            except (TypeError, ValueError):
                conf = 70
            rca_causes.append(
                {
                    "root_cause": str(row.get("root_cause") or "Unspecified")[:120],
                    "description": str(row.get("description") or "")[:400],
                    "frequency": max(0, freq),
                    "severity_score": sev,
                    "ai_confidence": max(0, min(100, conf)),
                    "example_review": str(row.get("example_review") or "")[:300],
                    "suggested_product_opportunity": str(
                        row.get("suggested_product_opportunity") or ""
                    )[:300],
                    "business_impact": str(row.get("business_impact") or "Medium").title(),
                    "implementation_effort": str(
                        row.get("implementation_effort") or "Medium"
                    ).title(),
                    "priority": str(row.get("priority") or "P2").upper(),
                    "suggested_solution": str(row.get("suggested_solution") or "")[:300],
                }
            )

        if not rca_causes:
            st.info(
                "Root cause analysis will appear after review analysis completes. "
                "Click **▶ Run Review Analysis** in the sidebar, then refresh this page."
            )
            return

        avg_sev = sum(c["severity_score"] for c in rca_causes) / len(rca_causes)
        avg_conf = sum(c["ai_confidence"] for c in rca_causes) / len(rca_causes)
        top_cause = max(rca_causes, key=lambda c: c["severity_score"])
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Root causes detected", f"{len(rca_causes)}")
        r2.metric("Avg severity (1–10)", f"{avg_sev:.1f}")
        r3.metric("Avg AI confidence", f"{avg_conf:.0f}%")
        r4.metric("Highest-impact cause", top_cause["root_cause"][:40])

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
        if table_cols:
            st.dataframe(
                rca_df[table_cols].rename(columns=table_rename),
                use_container_width=True,
                hide_index=True,
            )

        if _has_cols(rca_df, ["frequency", "root_cause"]):
            c_bar, c_pie = st.columns(2)
            with c_bar:
                fig_rca_bar = px.bar(
                    rca_df,
                    x="frequency",
                    y="root_cause",
                    orientation="h",
                    color="severity_score" if "severity_score" in rca_df.columns else None,
                    color_continuous_scale=["#95D5B2", "#E9C46A", "#9B2226"],
                    title="Root causes (frequency)",
                )
                fig_rca_bar.update_layout(yaxis={"categoryorder": "total ascending"})
                _safe_plotly(fig_rca_bar, chart_layout=chart_layout, height=400)
            with c_pie:
                pie_df = rca_df.copy()
                pie_df["frequency"] = pie_df["frequency"].clip(lower=0)
                if pie_df["frequency"].sum() <= 0:
                    pie_df["frequency"] = 1
                fig_rca_pie = px.pie(
                    pie_df,
                    names="root_cause",
                    values="frequency",
                    hole=0.4,
                    title="Contribution of each root cause",
                    color_discrete_sequence=px.colors.sequential.Tealgrn,
                )
                _safe_plotly(fig_rca_pie, chart_layout=chart_layout, height=400)

        if _has_cols(rca_df, ["severity_score", "root_cause"]):
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
                fig_sev.update_layout(yaxis={"categoryorder": "total ascending"})
                _safe_plotly(fig_sev, chart_layout=chart_layout, height=360)

        st.subheader("Why Users Keep Buying the Same Categories")
        st.markdown(str(rca.get("summary") or "").strip() or "_Summary unavailable — re-run analysis._")

        st.subheader("Product Manager Insights")
        st.caption("Actionable insights that reference the detected root causes.")
        pm_insights = rca.get("pm_insights") or []
        if isinstance(pm_insights, str):
            pm_insights = [pm_insights]
        if not isinstance(pm_insights, list):
            pm_insights = []
        pm_insights = [str(x).strip() for x in pm_insights if str(x).strip()]
        if pm_insights:
            for i, insight in enumerate(pm_insights, 1):
                try:
                    with st.container(border=True):
                        st.markdown(f"**{i}.** {insight}")
                except TypeError:
                    st.markdown(f"**{i}.** {insight}")
        else:
            st.info("PM insights will appear after Gemini root-cause analysis.")

        st.subheader("Impact vs Effort Prioritization")
        if not _has_cols(
            rca_df,
            ["root_cause", "business_impact", "implementation_effort", "priority"],
        ):
            st.info("Prioritization data is not available yet.")
            return

        prio_df = rca_df[
            [
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
        ].rename(
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
                    _ord=prio_df["Priority"].map(lambda x: order.get(str(x).upper(), 9))
                )
                .sort_values("_ord")
                .drop(columns=["_ord"])
            )
        st.dataframe(prio_df, use_container_width=True, hide_index=True)

        impact_map = {"Low": 1, "Medium": 2, "High": 3}
        effort_map = {"Low": 1, "Medium": 2, "High": 3}
        scatter_df = rca_df.copy()
        scatter_df["impact_n"] = (
            scatter_df["business_impact"].astype(str).str.title().map(impact_map).fillna(2)
        )
        scatter_df["effort_n"] = (
            scatter_df["implementation_effort"]
            .astype(str)
            .str.title()
            .map(effort_map)
            .fillna(2)
        )
        scatter_df["size"] = scatter_df["frequency"].clip(lower=1)
        fig_mat = px.scatter(
            scatter_df,
            x="effort_n",
            y="impact_n",
            size="size",
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
        _safe_plotly(fig_mat, chart_layout=chart_layout, height=380)
    except Exception as exc:
        st.error(f"Root Cause Analysis section failed to render. Details: {exc}")
        st.info(
            "Try **▶ Run Review Analysis** again, or clear caches and reload. "
            "Other dashboard sections below may still work."
        )
