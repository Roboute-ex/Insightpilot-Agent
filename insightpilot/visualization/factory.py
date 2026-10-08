"""Plotly chart factory driven by ChartSpec."""

from __future__ import annotations

from typing import Any
from html import escape

from insightpilot.ui.formatters import format_metric_name, format_metric_text
from insightpilot.ui.table_labels import COLUMN_NAMES

import pandas as pd
import numpy as np
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
    if spec.chart_type == "table":
        columns=list(frame.columns)
    else:
        extra=[column for column in ["metric_id","dimension","ci_lower","ci_upper","confidence_interval_lower","confidence_interval_upper","is_anomaly","severity"] if column in frame.columns]
        if spec.chart_type == "box" and spec.metadata.get("precomputed_box"):
            extra += [column for column in ("q1", "median", "q3", "minimum", "maximum") if column in frame]
        columns=list(dict.fromkeys([*required,*extra]))
    prepared = frame.loc[:,columns].copy()
    for metadata_key, column in [("metric_filter", "metric_id"), ("dimension_filter", "dimension")]:
        if metadata_key in spec.metadata and column in prepared.columns:
            prepared = prepared.loc[prepared[column].astype(str) == str(spec.metadata[metadata_key])]
    if prepared.empty:
        spec.metadata["warning"] = "结果表筛选后为空，未生成图表。"
        return None
    if spec.chart_type == "time_series" and spec.x:
        prepared[spec.x] = pd.to_datetime(prepared[spec.x], errors="coerce")
        prepared = prepared.dropna(subset=[spec.x]).sort_values(spec.x)
    elif spec.chart_type in {"contribution_bar", "bar", "grouped_bar", "missingness_bar"} and spec.y and spec.sort:
        ascending = spec.sort == "ascending"
        prepared = prepared.sort_values(spec.y[0], ascending=ascending)
    if spec.top_n:
        prepared = prepared.head(max(1, min(int(spec.top_n), 100)))
    series_budget=int(spec.metadata.get("series_budget",20))
    if spec.color and spec.chart_type != "heatmap":
        categories=prepared[spec.color].drop_duplicates()
        if len(categories)>series_budget:
            prepared=prepared.loc[prepared[spec.color].isin(categories.iloc[:series_budget])]
            spec.metadata["series_limit_applied"]=series_budget
            spec.metadata["display_note"]=f"仅展示前{series_budget}个序列，完整分析结果保持不变。"
    row_budget=max(1,int(spec.metadata.get("point_budget",MAX_CHART_ROWS))//max(1,len(spec.y)))
    total_rows=len(prepared)
    if total_rows > row_budget:
        if spec.chart_type in {"time_series","line","box"}:
            preserve={0,total_rows-1}
            for column in spec.y:
                numeric=pd.to_numeric(prepared[column],errors="coerce").to_numpy()
                if np.isfinite(numeric).any():
                    preserve.update([int(np.nanargmin(numeric)),int(np.nanargmax(numeric))])
            if "is_anomaly" in prepared:
                preserve.update(np.flatnonzero(prepared["is_anomaly"].fillna(False).to_numpy(dtype=bool)).tolist())
            if "severity" in prepared:
                preserve.update(np.flatnonzero(prepared["severity"].astype(str).isin(["HIGH","CRITICAL"]).to_numpy()).tolist())
            if len(preserve)>row_budget:
                spec.metadata["warning"]="异常点超过当前绘图预算，请提高点数预算或缩小展示范围；未删除统计样本。"
                return None
            candidates=np.setdiff1d(np.arange(total_rows),np.array(sorted(preserve)))
            remaining=row_budget-len(preserve)
            chosen=candidates[np.linspace(0,len(candidates)-1,remaining,dtype=int)] if remaining else []
            prepared=prepared.iloc[sorted(preserve|set(map(int,chosen)))]
            spec.metadata["display_note"]=f"显示抽样{len(prepared)}/{total_rows}行，保留首尾、极值与已标记异常；完整统计未抽样。"
        else:
            prepared=prepared.iloc[:row_budget]
            spec.metadata["display_note"]=f"仅展示前{len(prepared)}/{total_rows}行，完整分析结果保持不变。"
        spec.metadata["row_limit_applied"]=row_budget
    spec.metadata["displayed_rows"]=len(prepared)
    spec.metadata["total_display_rows"]=total_rows
    for column in prepared.columns:
        if pd.api.types.is_string_dtype(prepared[column].dtype) or pd.api.types.is_object_dtype(prepared[column].dtype):
            prepared[column] = prepared[column].map(lambda value: escape(value) if isinstance(value, str) else value)
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
            figure = go.Figure(go.Indicator(mode="number", value=float(frame[value_column].iloc[0]), title={"text": escape(format_metric_text(chart_spec.title))}))
        elif chart_type in {"time_series", "line"}:
            figure = px.line(
                frame,
                x=chart_spec.x,
                y=chart_spec.y,
                color=chart_spec.color,
                facet_col=chart_spec.facet,
                markers=True,
                title=escape(format_metric_text(chart_spec.title)),
            )
        elif chart_type in {"bar", "grouped_bar", "contribution_bar", "missingness_bar", "histogram"}:
            figure = px.bar(
                frame,
                x=chart_spec.x,
                y=chart_spec.y,
                color=chart_spec.color,
                facet_col=chart_spec.facet,
                barmode="group" if chart_type == "grouped_bar" else "relative",
                title=escape(format_metric_text(chart_spec.title)),
            )
        elif chart_type == "box" and chart_spec.metadata.get("precomputed_box"):
            if not {"q1", "median", "q3", "minimum", "maximum"}.issubset(frame.columns):
                chart_spec.metadata["warning"] = "箱线摘要缺少全量分位数，未用抽样代替。"
                return None
            figure = go.Figure(go.Box(x=frame[chart_spec.x] if chart_spec.x else None,
                q1=frame["q1"], median=frame["median"], q3=frame["q3"],
                lowerfence=frame["minimum"], upperfence=frame["maximum"], boxpoints=False))
            figure.update_layout(title=escape(format_metric_text(chart_spec.title)))
        elif chart_type == "box":
            figure = px.box(
                frame,
                x=chart_spec.x,
                y=chart_spec.y[0] if chart_spec.y else None,
                color=chart_spec.color,
                title=escape(format_metric_text(chart_spec.title)),
            )
        elif chart_type == "confidence_interval":
            y_column = chart_spec.y[0]
            error_y = None
            error_y_minus = None
            interval_columns = ("ci_lower", "ci_upper") if {"ci_lower", "ci_upper"}.issubset(frame.columns) else ("confidence_interval_lower", "confidence_interval_upper")
            if set(interval_columns).issubset(frame.columns):
                error_y = frame[interval_columns[1]] - frame[y_column]
                error_y_minus = frame[y_column] - frame[interval_columns[0]]
            figure = go.Figure(
                go.Bar(
                    x=frame[chart_spec.x] if chart_spec.x else frame.index,
                    y=frame[y_column],
                    error_y={"type": "data", "array": error_y, "arrayminus": error_y_minus}
                    if error_y is not None
                    else None,
                )
            )
            figure.update_layout(title=escape(format_metric_text(chart_spec.title)))
        elif chart_type == "funnel":
            if not chart_spec.x or not chart_spec.y:
                chart_spec.metadata["warning"] = "漏斗图需要阶段与数量字段。"
                return None
            figure = go.Figure(go.Funnel(y=frame[chart_spec.x], x=frame[chart_spec.y[0]], textinfo="value+percent initial"))
            figure.update_layout(title=escape(format_metric_text(chart_spec.title)))
        elif chart_type == "heatmap":
            if not chart_spec.x or not chart_spec.y or not chart_spec.color:
                chart_spec.metadata["warning"] = "留存热图需要观察周期、队列及留存率字段。"
                return None
            if frame.duplicated([chart_spec.color, chart_spec.x]).any():
                chart_spec.metadata["warning"] = "热图单元格不唯一，需先按明确口径聚合。"
                return None
            matrix = frame.pivot(index=chart_spec.color, columns=chart_spec.x, values=chart_spec.y[0])
            figure = go.Figure(go.Heatmap(z=matrix.to_numpy(), x=matrix.columns, y=matrix.index, colorscale="Blues", hoverongaps=False))
            figure.update_layout(title=escape(format_metric_text(chart_spec.title)))
        elif chart_type == "table":
            figure = go.Figure(
                data=[go.Table(header={"values": list(frame.columns)}, cells={"values": [frame[column] for column in frame.columns]})]
            )
            figure.update_layout(title=escape(format_metric_text(chart_spec.title)))
        else:  # guarded by ChartSpec, retained for defensive compatibility
            return None
        figure.update_layout(
            margin={"l": 24, "r": 24, "t": 56, "b": 32},
            height=360,
            legend_title_text=escape(COLUMN_NAMES.get(chart_spec.color, format_metric_name(chart_spec.color))) if chart_spec.color else "",
        )
        if chart_spec.x:
            figure.update_xaxes(title_text=escape(COLUMN_NAMES.get(chart_spec.x, format_metric_name(chart_spec.x))))
        if chart_spec.y:
            figure.update_yaxes(title_text=", ".join(escape(COLUMN_NAMES.get(column, format_metric_name(column))) for column in chart_spec.y))
        for trace in figure.data:
            if getattr(trace, "name", None):
                trace.name = escape(COLUMN_NAMES.get(trace.name, format_metric_name(trace.name)))
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
