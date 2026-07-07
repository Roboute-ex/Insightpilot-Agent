"""Plotly visualizations used by the Streamlit UI."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def build_time_series_chart(df: pd.DataFrame, date_col: str, value_col: str, title: str = "Time Series") -> go.Figure:
    fig = px.line(df, x=date_col, y=value_col, title=title, markers=True)
    fig.update_layout(margin=dict(l=12, r=12, t=48, b=12), height=320)
    return fig


def build_contribution_bar_chart(
    df: pd.DataFrame,
    dimension_col: str = "dimension_value",
    value_col: str = "contribution_share",
    title: str = "Contribution",
) -> go.Figure:
    fig = px.bar(df, x=dimension_col, y=value_col, title=title)
    fig.update_layout(margin=dict(l=12, r=12, t=48, b=12), height=320)
    return fig


def build_ab_test_comparison_chart(ab_result: dict[str, object], title: str = "A/B Test Comparison") -> go.Figure:
    fig = go.Figure(
        data=[
            go.Bar(
                x=["control", "treatment"],
                y=[ab_result.get("control_mean", 0.0), ab_result.get("treatment_mean", 0.0)],
            )
        ]
    )
    fig.update_layout(title=title, margin=dict(l=12, r=12, t=48, b=12), height=320)
    return fig
