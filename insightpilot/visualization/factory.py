"""Plotly chart factory driven by ChartSpec."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from insightpilot.visualization.specs import ChartSpec


MAX_CHART_ROWS = 5000


def _prepare_frame(spec: ChartSpec, result_tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    frame = result_tables.get(spec.table_key)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        spec.metadata["warning"] = f"结果表 {spec.table_key} 为空，未生成图表。"
        return None
    required = [column for column in [spec.x, spec.color, spec.facet, *spec.y] if column]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        spec.metadata["warning"] = f"图表缺少字段：{', '.join(missing)}。"
        return None
    prepared = frame.copy()
    if spec.chart_type in {"time_series", "line"} and spec.x:
        prepared[spec.x] = pd.to_datetime(prepared[spec.x], errors="coerce")
        prepared = prepared.dropna(subset=[spec.x]).sort_values(spec.x)
    elif spec.chart_type in {"contribution_bar", "bar", "grouped_bar", "missingness_bar"} and spec.y:
        ascending = spec.sort == "ascending"
        prepared = prepared.sort_values(spec.y[0], ascending=ascending)
    if spec.top_n:
        prepared = prepared.head(max(1, min(int(spec.top_n), 100)))
    if len(prepared) > MAX_CHART_ROWS:
        prepared = prepared.head(MAX_CHART_ROWS)
        spec.metadata["row_limit_applied"] = MAX_CHART_ROWS
    return prepared


def build_chart(
    spec: ChartSpec | dict[str, Any],
    result_tables: dict[str, pd.DataFrame],
) -> go.Figure | None:
    """Build one Plotly figure; invalid or empty inputs return None."""

    chart_spec = ChartSpec.from_dict(spec) if isinstance(spec, dict) else spec
    frame = _prepare_frame(chart_spec, result_tables)
    if frame is None:
        return None
    try:
        chart_type = chart_spec.chart_type
        if chart_type == "metric_card":
            value_column = chart_spec.y[0] if chart_spec.y else next(
                (str(column) for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])),
                None,
            )
            if value_column is None:
                chart_spec.metadata["warning"] = "metric_card 没有可用数值字段。"
                return None
            figure = go.Figure(go.Indicator(mode="number", value=float(frame[value_column].iloc[0]), title={"text": chart_spec.title}))
        elif chart_type in {"time_series", "line"}:
            figure = px.line(
                frame,
                x=chart_spec.x,
                y=chart_spec.y,
                color=chart_spec.color,
                facet_col=chart_spec.facet,
                markers=True,
                title=chart_spec.title,
            )
        elif chart_type in {"bar", "grouped_bar", "contribution_bar", "missingness_bar", "histogram"}:
            figure = px.bar(
                frame,
                x=chart_spec.x,
                y=chart_spec.y,
                color=chart_spec.color,
                facet_col=chart_spec.facet,
                barmode="group" if chart_type == "grouped_bar" else "relative",
                title=chart_spec.title,
            )
        elif chart_type == "box":
            figure = px.box(
                frame,
                x=chart_spec.x,
                y=chart_spec.y[0] if chart_spec.y else None,
                color=chart_spec.color,
                title=chart_spec.title,
            )
        elif chart_type == "confidence_interval":
            y_column = chart_spec.y[0]
            error_y = None
            error_y_minus = None
            if {"ci_lower", "ci_upper"}.issubset(frame.columns):
                error_y = frame["ci_upper"] - frame[y_column]
                error_y_minus = frame[y_column] - frame["ci_lower"]
            figure = go.Figure(
                go.Bar(
                    x=frame[chart_spec.x] if chart_spec.x else frame.index,
                    y=frame[y_column],
                    error_y={"type": "data", "array": error_y, "arrayminus": error_y_minus}
                    if error_y is not None
                    else None,
                )
            )
            figure.update_layout(title=chart_spec.title)
        elif chart_type == "table":
            figure = go.Figure(
                data=[go.Table(header={"values": list(frame.columns)}, cells={"values": [frame[column] for column in frame.columns]})]
            )
            figure.update_layout(title=chart_spec.title)
        else:  # guarded by ChartSpec, retained for defensive compatibility
            return None
        figure.update_layout(
            margin={"l": 24, "r": 24, "t": 56, "b": 32},
            height=360,
            legend_title_text=chart_spec.color or "",
        )
        if chart_spec.x:
            figure.update_xaxes(title_text=chart_spec.x)
        if chart_spec.y:
            figure.update_yaxes(title_text=", ".join(chart_spec.y))
        return figure
    except Exception as exc:
        chart_spec.metadata["warning"] = f"图表生成失败：{exc}"
        return None


def build_charts(
    specs: list[ChartSpec | dict[str, Any]],
    result_tables: dict[str, pd.DataFrame],
) -> list[tuple[ChartSpec, go.Figure]]:
    charts: list[tuple[ChartSpec, go.Figure]] = []
    for item in specs:
        spec = ChartSpec.from_dict(item) if isinstance(item, dict) else item
        figure = build_chart(spec, result_tables)
        if figure is not None:
            charts.append((spec, figure))
    return charts
