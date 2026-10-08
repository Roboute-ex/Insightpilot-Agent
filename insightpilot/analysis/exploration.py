"""Bounded single-table exploration through the existing playbook/result protocol.

All statistical queries cover the complete selected scope. Display limits are
applied only after aggregation; exceeding the engine output budget is an error.
"""
from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.metrics.aggregation import metric_components
from insightpilot.metrics.definitions import column_metric_card, stable_fingerprint
from insightpilot.performance_tasks import cancellation_checkpoint
from insightpilot.playbooks.models import PlaybookExecutionResult
from insightpilot.playbooks.sql_templates import quote_identifier
from insightpilot.semantic.query import FILTER_OPERATORS, MetricFilter
from insightpilot.tools.sql_safety import validate_bound_parameters
from insightpilot.visualization.specs import ChartSpec

KINDS = {"distribution", "grouped", "pivot"}
AGGREGATIONS = {"sum", "mean", "count", "count_distinct", "min", "max", "ratio_of_sums"}
REQUEST_KEYS = {"kind", "field", "distribution_type", "row_dimension", "column_dimension", "filters",
                "date_from", "date_to", "time_grain", "top_n", "include_others", "max_display_rows", "max_display_columns"}
CAVEAT = "全量当前范围的描述性探索；字段齐全与查询通过不代表独立性、显著性或因果关系已经成立。"
FINITE_MAX = "1.7976931348623157e308"


def _raw_mapping(mapping) -> dict:
    return mapping.to_dict() if isinstance(mapping, ColumnMapping) else dict(mapping or {})


def validate_exploration_request(request: Any, mapping, columns: list[str], metadata: dict | None = None) -> list[str]:
    """Metadata-only extension of the existing playbook validation gate."""
    if not isinstance(request, dict):
        return ["exploration_request 必须是结构化单表探索请求。"]
    errors = []
    unknown = set(request) - REQUEST_KEYS
    if unknown:
        errors.append("探索请求包含不支持的字段：" + ", ".join(sorted(unknown)))
    kind = request.get("kind")
    if kind not in KINDS:
        errors.append("探索类型只支持 distribution、grouped 和 pivot。")
    raw = _raw_mapping(mapping)
    available = set(columns)
    if not raw.get("table_name"):
        errors.append("探索需要明确选择一张分析表。")
    for role in ("field", "row_dimension", "column_dimension"):
        value = request.get(role)
        required = role == "field" and kind == "distribution" or role == "row_dimension" and kind in {"grouped", "pivot"} or role == "column_dimension" and kind == "pivot"
        if required and not value:
            errors.append("请明确选择探索字段。" if role == "field" else "请明确选择透视列维度。" if role == "column_dimension" else "请明确选择分组行维度。")
        elif value and value not in available:
            errors.append(f"探索 {role} 指定的列不存在：{value}。")
    if kind == "pivot" and request.get("row_dimension") == request.get("column_dimension"):
        errors.append("交叉表需要两个不同的维度。")
    if request.get("distribution_type", "auto") not in {"auto", "numeric", "categorical", "date"}:
        errors.append("不支持的字段分布类型。")
    if kind == "distribution" and request.get("distribution_type") == "date":
        fact = (metadata or {}).get("readiness_summary", {}).get("columns", {}).get(request.get("field"), {})
        dtype = str(fact.get("dtype", "")).lower()
        if any(word in dtype for word in ("int", "float", "double", "decimal")):
            errors.append("数值日期需要在摄入阶段明确 epoch 单位；探索不会猜测单位。")
    if kind != "distribution":
        metrics = raw.get("metric_columns") or []
        if len(metrics) != 1:
            errors.append("分组和交叉表需要一个已明确的指标，不能自动选第一列。")
        aggregation = raw.get("aggregation", "sum")
        if aggregation not in AGGREGATIONS:
            errors.append("探索聚合方式不受支持。")
        pair = (raw.get("numerator_column"), raw.get("denominator_column"))
        if any(pair) and not all(pair):
            errors.append("加权比率需要同时明确分子字段与分母字段。")
        if any(pair) and aggregation != "ratio_of_sums":
            errors.append("已指定分子分母，聚合方式必须明确为 ratio_of_sums。")
        for column in pair:
            if column and column not in available:
                errors.append(f"比率字段不存在：{column}。")
        metric = metrics[0] if len(metrics) == 1 else None
        known_pair = metric_components(str(metric), columns) if metric else None
        if aggregation == "ratio_of_sums" and not all(pair) and not known_pair:
            errors.append("加权比率缺少实际分子与分母字段，不能平均已有比例代替。")
        if metric and metric not in available and not known_pair:
            errors.append(f"指标字段不存在：{metric}。")
        if metric and (str(metric).endswith("_rate") or metric in {"ctr", "cvr"}) and not known_pair and not all(pair) and aggregation != "mean":
            errors.append("该比率缺少原始分子分母，不能求和；请补齐字段或明确等权单位后选择 mean。")
        if raw.get("deduplication_key") and raw["deduplication_key"] not in available:
            errors.append("去重键不存在于当前表。")
        facts = (metadata or {}).get("readiness_summary", {}).get("columns", {})
        numeric_fields = list(pair) if all(pair) else list(known_pair) if known_pair else metrics if aggregation in {"sum", "mean", "min", "max"} else []
        for column in numeric_fields:
            fact = facts.get(column, {})
            if fact and fact.get("valid_numeric_count", 0) == 0:
                errors.append(f"指标字段 {column} 没有有效有限数值。")
    for key, low, high, default in (("top_n", 1, 100, 20), ("max_display_rows", 1, 50, 50), ("max_display_columns", 1, 30, 30)):
        value = request.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            errors.append(f"{key} 必须是 {low} 到 {high} 的整数；它只限制展示。")
    if not isinstance(request.get("include_others", True), bool):
        errors.append("include_others 必须为布尔值。")
    grain = request.get("time_grain")
    if grain is not None:
        if grain not in {"day", "week", "month"}:
            errors.append("时间粒度只支持 day、week 和 month。")
        if not raw.get("date_column") or request.get("row_dimension") != raw.get("date_column"):
            errors.append("时间粒度需要把已明确的日期字段选为行维度。")
    dates = request.get("date_from"), request.get("date_to")
    if any(value is not None for value in dates):
        if not all(value is not None for value in dates) or raw.get("date_column") not in available:
            errors.append("日期筛选需要日期字段和完整开始/结束日期。")
        else:
            try:
                if date.fromisoformat(str(dates[0])) > date.fromisoformat(str(dates[1])):
                    raise ValueError()
            except (ValueError, TypeError):
                errors.append("日期范围必须为有序的 ISO 日期。")
    filters = request.get("filters", [])
    if not isinstance(filters, list) or len(filters) > 8:
        errors.append("探索最多接受八个结构化筛选条件。")
    else:
        for item in filters:
            if not isinstance(item, dict) or set(item) != {"column", "operator", "value"}:
                errors.append("筛选必须只包含 column、operator、value。")
                continue
            if item["column"] not in available:
                errors.append("筛选字段不在当前表白名单内。")
            values_to_check = item["value"] if isinstance(item["value"], list) else [item["value"]]
            if any(isinstance(value, str) and value == "<已脱敏，需重新输入>" for value in values_to_check):
                errors.append("探索筛选值已脱敏，请明确重新提供实际筛选值后再执行。")
                continue
            try:
                MetricFilter(str(item["column"]), str(item["operator"]), item["value"])
                op, value = item["operator"], item["value"]
                if op in {"in", "between"}:
                    if not isinstance(value, list) or not 1 <= len(value) <= 100 or op == "between" and len(value) != 2:
                        raise ValueError("in/between 需要有界值列表。")
                    validate_bound_parameters(value)
                else:
                    validate_bound_parameters([value])
                    if value is None and op != "eq":
                        raise ValueError("空值筛选只支持 eq。")
            except (ValueError, TypeError) as exc:
                errors.append("筛选条件无效：" + str(exc))
    return list(dict.fromkeys(errors))


def _where(request: dict, mapping: ColumnMapping, allowed: set[str]) -> tuple[str, list]:
    clauses, values = [], []
    for item in request.get("filters", []):
        column, op, value = quote_identifier(item["column"], allowed), item["operator"], item["value"]
        if op == "eq" and value is None:
            clauses.append(f"{column} IS NULL")
        elif op == "in":
            nonnull = [v for v in value if v is not None]
            parts = [f"{column} IN ({', '.join('?' for _ in nonnull)})"] if nonnull else []
            if None in value:
                parts.append(f"{column} IS NULL")
            clauses.append("(" + " OR ".join(parts) + ")")
            values.extend(nonnull)
        elif op == "between":
            clauses.append(f"{column} BETWEEN ? AND ?")
            values.extend(value)
        else:
            symbol = {"eq": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            clauses.append(f"{column} {symbol} ?")
            values.append(value)
    if request.get("date_from") is not None:
        col = quote_identifier(mapping.date_column, allowed)
        clauses.append(f"CAST(TRY_CAST({col} AS TIMESTAMP) AS DATE) BETWEEN ? AND ?")
        values.extend([request["date_from"], request["date_to"]])
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), values


def _finite_sql(column: str) -> str:
    cast = f"TRY_CAST({column} AS DOUBLE)"
    return f"CASE WHEN {cast} BETWEEN -{FINITE_MAX} AND {FINITE_MAX} THEN {cast} ELSE NULL END"


def _scalar(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.generic,)):
        value = value.item()
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def group_identity(column: str, value: Any, *, others: bool = False) -> str:
    value = _scalar(value)
    return ("others:" if others else "value:") + stable_fingerprint({"column": column, "kind": "others" if others else "null" if value is None else type(value).__name__, "value": value})


def _add_keys(frame: pd.DataFrame, request: dict) -> pd.DataFrame:
    for axis, column in (("row", request.get("row_dimension")), ("column", request.get("column_dimension"))):
        name = axis + "_value"
        if name not in frame:
            continue
        flag = axis + "_is_others"
        if flag not in frame:
            frame[flag] = False
        frame[flag] = frame[flag].astype(bool)
        frame[axis + "_key"] = [group_identity(str(column), value, others=bool(other)) for value, other in zip(frame[name], frame[flag])]
        frame[axis + "_label"] = ["其他分组（Others，余集）" if other else "缺失值（真实空值）" if _scalar(value) is None else str(value) for value, other in zip(frame[name], frame[flag])]
        labels = frame[[axis + "_label", axis + "_key"]].drop_duplicates()
        collisions = set(labels.loc[labels.duplicated(axis + "_label", keep=False), axis + "_label"])
        if collisions:
            frame[axis + "_label"] = [label + " [" + key[-6:] + "]" if label in collisions else label for label, key in zip(frame[axis + "_label"], frame[axis + "_key"])]
    frame["observed"] = True
    return frame


def _sort(frame: pd.DataFrame, key: str = "row_key") -> pd.DataFrame:
    return frame.sort_values(["metric_value", key], ascending=[False, True], na_position="last", kind="stable").reset_index(drop=True)


def _execute_query(engine, sql: str, values: list, queries: list, purpose: str, table: str) -> pd.DataFrame:
    cancellation_checkpoint()
    frame = engine.run_parameterized_sql(sql, values)
    queries.append({"tool": "duckdb", "template_id": "single_table_exploration", "purpose": purpose,
                    "query": sql, "status": "success", "row_count": len(frame), "referenced_tables": [table]})
    return frame


def _metric_scope(mapping: ColumnMapping, columns: list[str], request: dict) -> tuple[str, list, dict]:
    allowed = set(columns) | {mapping.table_name}
    q = lambda name: quote_identifier(name, allowed)
    metric = mapping.metric_columns[0]
    pair = (mapping.numerator_column, mapping.denominator_column)
    pair = pair if all(pair) else metric_components(metric, columns)
    aggregation = "ratio_of_sums" if pair else mapping.aggregation
    entity = mapping.deduplication_key or ("user_id" if metric == "active_users" else metric)
    if metric == "active_users":
        aggregation = "count_distinct"
    projections = []
    for axis in ("row", "column"):
        dimension = request.get(axis + "_dimension")
        if dimension:
            expression = q(dimension)
            if axis == "row" and request.get("time_grain"):
                expression = f"date_trunc('{request['time_grain']}', TRY_CAST({expression} AS TIMESTAMP))"
            projections.append(f"{expression} AS _ip_{axis}")
    if pair:
        projections += [f"{_finite_sql(q(pair[0]))} AS _ip_num", f"{_finite_sql(q(pair[1]))} AS _ip_den"]
        aggregate = "SUM(_ip_num) / NULLIF(SUM(_ip_den), 0)"
        extras = ", SUM(_ip_num) AS numerator_sum, SUM(_ip_den) AS denominator_sum, COUNT(_ip_num) AS numerator_valid_count, COUNT(_ip_den) AS denominator_valid_count"
        valid = "COUNT(CASE WHEN _ip_num IS NOT NULL AND _ip_den IS NOT NULL THEN 1 END)"
    elif aggregation == "count_distinct":
        projections.append(f"{q(entity)} AS _ip_metric")
        aggregate, valid, extras = "COUNT(DISTINCT _ip_metric)", "COUNT(_ip_metric)", ""
    elif aggregation == "count":
        projections.append(f"{q(metric)} AS _ip_metric")
        aggregate, valid, extras = "COUNT(_ip_metric)", "COUNT(_ip_metric)", ""
    else:
        projections.append(f"{_finite_sql(q(metric))} AS _ip_metric")
        aggregate = {"sum": "SUM", "mean": "AVG", "min": "MIN", "max": "MAX"}[aggregation] + "(_ip_metric)"
        valid, extras = "COUNT(_ip_metric)", ", SUM(_ip_metric) AS metric_sum"
    where, values = _where(request, mapping, allowed)
    cte = f"WITH _ip_scope AS (SELECT {', '.join(projections)} FROM {q(mapping.table_name)}{where})"
    aggregates = f"{aggregate} AS metric_value, COUNT(*) AS observation_count, {valid} AS valid_count{extras}"
    return cte, values, {"sql": aggregates, "aggregation": aggregation, "pair": pair, "entity": entity}


def _aggregate_query(cte: str, aggregate: str, axes: list[str], *, source="_ip_scope", other_flags=False) -> str:
    select, groups = [], []
    for axis in axes:
        select.append(f"_ip_{axis} AS {axis}_value")
        groups.append(f"_ip_{axis}")
        if other_flags:
            select.append(f"_ip_{axis}_other AS {axis}_is_others")
            groups.append(f"_ip_{axis}_other")
    return f"{cte} SELECT {', '.join(select) + ', ' if select else ''}{aggregate} FROM {source}" + (f" GROUP BY {', '.join(groups)}" if groups else "")


def _kept_condition(axis: str, keep: pd.DataFrame) -> tuple[str, list]:
    vals = [_scalar(v) for v in keep[axis + "_value"]]
    nonnull = [v for v in vals if v is not None]
    parts = [f"_ip_{axis} IN ({', '.join('?' for _ in nonnull)})"] if nonnull else []
    if None in vals:
        parts.append(f"_ip_{axis} IS NULL")
    return "(" + " OR ".join(parts) + ")" if parts else "FALSE", nonnull


def _grouped(request: dict, mapping: ColumnMapping, frame: pd.DataFrame, engine, queries: list):
    cte, values, agg = _metric_scope(mapping, list(map(str, frame.columns)), request)
    axes = ["row", "column"] if request["kind"] == "pivot" else ["row"]
    def query(axes, label):
        return _execute_query(engine, _aggregate_query(cte, agg["sql"], axes), values, queries, label, mapping.table_name)
    cells = _add_keys(query(axes, "完整观测交叉分组"), request)
    cells = cells.sort_values(["metric_value", *[axis + "_key" for axis in axes]], ascending=[False, *([True] * len(axes))], na_position="last", kind="stable").reset_index(drop=True)
    all_total = query([], "全范围独立合计")
    all_total["scope"] = "all"
    if len(axes) == 1:
        row_totals = cells.copy(deep=False)
    else:
        row_totals = _sort(_add_keys(query(["row"], "行范围独立合计"), request))
    row_totals = row_totals.assign(scope="row")
    totals = [all_total, row_totals]
    columns = None
    if len(axes) == 2:
        columns = _sort(_add_keys(query(["column"], "列范围独立合计"), request), "column_key").assign(scope="column")
        totals.append(columns)
    display_rows = min(request.get("top_n", 20), request.get("max_display_rows", 50))
    row_overflow = len(row_totals) > display_rows
    col_budget = request.get("max_display_columns", 30)
    col_overflow = columns is not None and len(columns) > col_budget
    include_others = request.get("include_others", True)
    kept_rows = row_totals.head(max(0, display_rows - int(row_overflow and include_others)))
    kept_cols = columns.head(max(0, col_budget - int(col_overflow and include_others))) if columns is not None else None
    if (row_overflow or col_overflow) and include_others:
        select, extra_values = [], []
        for axis, keep, overflow in (("row", kept_rows, row_overflow), ("column", kept_cols, col_overflow)):
            if axis not in axes:
                continue
            if overflow:
                cond, bound = _kept_condition(axis, keep)
                select += [f"CASE WHEN {cond} THEN _ip_{axis} END AS _ip_{axis}", f"CASE WHEN {cond} THEN 0 ELSE 1 END AS _ip_{axis}_other"]
                extra_values += [*bound, *bound]
            else:
                select += [f"_ip_{axis}", f"0 AS _ip_{axis}_other"]
        select += ["_ip_num", "_ip_den"] if agg["pair"] else ["_ip_metric"]
        display_cte = cte + ", _ip_display AS (SELECT " + ", ".join(select) + " FROM _ip_scope)"
        display = _execute_query(engine, _aggregate_query(display_cte, agg["sql"], axes, source="_ip_display", other_flags=True), [*values, *extra_values], queries, "Top N与余集独立重聚合", mapping.table_name)
        display = _add_keys(display, request)
    else:
        display = cells.loc[cells["row_key"].isin(kept_rows["row_key"])]
        if kept_cols is not None:
            display = display.loc[display["column_key"].isin(kept_cols["column_key"])]
        display = display.copy()
    display = display.sort_values(["row_is_others", "metric_value", "row_key"], ascending=[True, False, True], na_position="last", kind="stable").reset_index(drop=True)
    if agg["aggregation"] in {"count", "count_distinct"}:
        # Count-distinct shares are intentionally absent: entities may cross cells.
        if agg["aggregation"] == "count":
            if len(axes) == 1:
                denominator = float(all_total["metric_value"].iloc[0])
                display["frequency_share"] = display["metric_value"] / denominator if denominator else np.nan
            elif include_others or not (row_overflow or col_overflow):
                rt = display.groupby("row_key")["metric_value"].sum()
                ct = display.groupby("column_key")["metric_value"].sum()
                display["row_frequency_share"] = display["metric_value"] / display["row_key"].map(rt).replace(0, np.nan)
                display["column_frequency_share"] = display["metric_value"] / display["column_key"].map(ct).replace(0, np.nan)
    note = "完整观测分组保存在 exploration_cells；未观测组合为缺失而非 0。行/列/总计均在原始对应范围重聚合。"
    if row_overflow or col_overflow:
        note += f" 展示至多 {display_rows} 行维度 × {col_budget} 列维度；" + ("Others 是余集，不能当真实字段值下钻。" if include_others else "其余分组仅从展示隐藏，导出完整聚合未截断。")
    return {"exploration_cells": cells, "exploration_totals": pd.concat(totals, ignore_index=True, sort=False), "exploration_display": display}, {"aggregation": agg["aggregation"], "full_group_count": len(cells), "scope_row_count": int(all_total["observation_count"].iloc[0]), "display_note": note}


def _distribution(request: dict, mapping: ColumnMapping, frame: pd.DataFrame, engine, queries: list, metadata: dict | None = None):
    field = request["field"]
    dtype = frame[field].dtype
    kind = request.get("distribution_type", "auto")
    if kind == "auto":
        meta = metadata or {}
        fact = meta.get("readiness_summary", {}).get("columns", {}).get(field, {})
        confirmed_date = field in meta.get("schema_mapping", {}).get("detected_date_columns", []) and bool(fact.get("valid_date_count"))
        kind = "date" if pd.api.types.is_datetime64_any_dtype(dtype) or confirmed_date and not pd.api.types.is_numeric_dtype(dtype) else "numeric" if pd.api.types.is_numeric_dtype(dtype) and not (field.lower().endswith("_id") or field.lower() == "id") else "categorical"
    if kind == "date" and pd.api.types.is_numeric_dtype(dtype):
        raise ValueError("数值日期需要明确并在摄入阶段转换 epoch 单位；探索不会猜测单位。")
    allowed = set(map(str, frame.columns)) | {mapping.table_name}
    raw = quote_identifier(field, allowed)
    where, values = _where(request, mapping, allowed)
    table = quote_identifier(mapping.table_name, allowed)
    if kind == "numeric":
        cte = f"WITH _ip_scope AS (SELECT {raw} AS _ip_raw, TRY_CAST({raw} AS DOUBLE) AS _ip_converted, {_finite_sql(raw)} AS _ip_value FROM {table}{where})"
        summary_sql = (cte + " SELECT COUNT(*) AS row_count, COUNT(*)-COUNT(_ip_raw) AS missing_count, COUNT(_ip_raw)-COUNT(_ip_converted) AS invalid_numeric_count, COUNT(_ip_converted)-COUNT(_ip_value) AS nonfinite_count, COUNT(_ip_value) AS valid_count, MIN(_ip_value) AS minimum, QUANTILE_CONT(_ip_value, 0.25) AS q1, QUANTILE_CONT(_ip_value, 0.5) AS median, QUANTILE_CONT(_ip_value, 0.75) AS q3, MAX(_ip_value) AS maximum, AVG(_ip_value) AS mean, STDDEV_SAMP(_ip_value) AS stddev FROM _ip_scope")
        summary = _execute_query(engine, summary_sql, values, queries, "全量数值分布统计", mapping.table_name)
        summary["ddof"] = 1
        summary["field"] = field
        row = summary.iloc[0]
        bins = pd.DataFrame(columns=["bin_start", "bin_end", "count"])
        if int(row["valid_count"]):
            low, high = float(row["minimum"]), float(row["maximum"])
            count = 1 if low == high else 20
            width = (high - low) / count if high != low else 1.0
            if not isfinite(width):
                raise ValueError("数值范围超过稳定分箱边界；统计未截断，请调整数据单位。")
            sql = cte + " SELECT LEAST(FLOOR((_ip_value - ?) / ?), ?) AS bin_index, COUNT(*) AS count FROM _ip_scope WHERE _ip_value IS NOT NULL GROUP BY bin_index ORDER BY bin_index"
            bins = _execute_query(engine, sql, [*values, low, width, count - 1], queries, "全量直方分箱", mapping.table_name)
            bins["bin_start"] = low + bins["bin_index"] * width
            bins["bin_end"] = low + (bins["bin_index"] + 1) * width
            bins.loc[bins["bin_index"] == count - 1, "bin_end"] = high
        return {"distribution_summary": summary, "distribution_bins": bins}, {"distribution_type": kind, "scope_row_count": int(row["row_count"]), "display_note": "直方图为全量有限值分箱；统计量使用全部有效值，标准差 ddof=1。缺失/解析失败/非有限值单列计数。"}
    if kind == "date":
        cte = f"WITH _ip_scope AS (SELECT {raw} AS _ip_raw, TRY_CAST({raw} AS TIMESTAMP) AS _ip_date FROM {table}{where})"
        summary = _execute_query(engine, cte + " SELECT COUNT(*) AS row_count, COUNT(*)-COUNT(_ip_raw) AS missing_count, COUNT(_ip_date) AS valid_count, COUNT(_ip_raw)-COUNT(_ip_date) AS parse_failure_count, MIN(_ip_date) AS minimum, MAX(_ip_date) AS maximum FROM _ip_scope", values, queries, "全量日期解析分布", mapping.table_name)
        bins = _execute_query(engine, cte + " SELECT date_trunc('day', _ip_date) AS period, COUNT(*) AS count FROM _ip_scope WHERE _ip_date IS NOT NULL GROUP BY period ORDER BY period", values, queries, "全量日期频数", mapping.table_name)
        summary["field"] = field
        return {"distribution_summary": summary, "distribution_bins": bins}, {"distribution_type": kind, "scope_row_count": int(summary["row_count"].iloc[0]), "display_note": "日期按日显示全量解析成功频数；无效日期不静默转成 epoch。"}
    sql = f"SELECT {raw} AS row_value, COUNT(*) AS metric_value FROM {table}{where} GROUP BY {raw}"
    frequencies = _execute_query(engine, sql, values, queries, "全量分类频数", mapping.table_name)
    identity_request = {**request, "row_dimension": field}
    frequencies = _sort(_add_keys(frequencies, identity_request))
    total = int(frequencies["metric_value"].sum())
    frequencies["frequency_share"] = frequencies["metric_value"] / total if total else np.nan
    limit = min(request.get("top_n", 20), request.get("max_display_rows", 50))
    overflow = len(frequencies) > limit
    keep = limit - int(overflow and request.get("include_others", True))
    display = frequencies.head(keep).copy()
    if overflow and request.get("include_others", True):
        rest = int(frequencies.iloc[keep:]["metric_value"].sum())
        other = _add_keys(pd.DataFrame([{"row_value": None, "row_is_others": True, "metric_value": rest, "frequency_share": rest / total if total else np.nan}]), identity_request)
        display = _add_keys(pd.concat([display, other], ignore_index=True), identity_request)
    summary = pd.DataFrame([{"field": field, "row_count": total, "missing_count": int(frequencies.loc[frequencies["row_value"].isna(), "metric_value"].sum()), "observed_group_count": len(frequencies)}])
    return {"distribution_summary": summary, "distribution_frequencies": frequencies, "exploration_display": display}, {"distribution_type": kind, "scope_row_count": total, "display_note": "频数和占比分母为筛选范围内全部观测行（含缺失组），不是去重人数；Others 是余集。"}


def build_exploration_chart_spec(result_tables: dict[str, pd.DataFrame], kind: str, chart_type: str | None = None) -> dict | None:
    """Pure presentation: never query, scan source data, or mutate a run."""
    if kind == "distribution":
        if "distribution_frequencies" in result_tables:
            spec = ChartSpec("exploration", chart_type or "bar", "字段频数分布", "exploration_display", x="row_label", y=["metric_value"])
        elif "distribution_bins" in result_tables and "period" in result_tables["distribution_bins"]:
            spec = ChartSpec("exploration", chart_type or "line", "日期频数分布", "distribution_bins", x="period", y=["count"])
        elif chart_type == "box":
            spec = ChartSpec("exploration", "box", "全量数值箱线摘要", "distribution_summary", x="field", y=["median"], metadata={"precomputed_box": True})
        else:
            spec = ChartSpec("exploration", chart_type or "histogram", "全量数值分布", "distribution_bins", x="bin_start", y=["count"])
    else:
        spec = ChartSpec("exploration", chart_type or ("heatmap" if kind == "pivot" else "bar"), "交叉表" if kind == "pivot" else "分组汇总", "exploration_display", x="column_label" if kind == "pivot" else "row_label", y=["metric_value"], color="row_label" if kind == "pivot" else None)
    return spec.to_dict()


def execute_exploration(playbook, tables, mapping: ColumnMapping, frame: pd.DataFrame, parameters: dict, engine, metadata: dict | None = None) -> PlaybookExecutionResult:
    request = dict(parameters["exploration_request"])
    queries = []
    if request["kind"] == "distribution":
        result_tables, extra = _distribution(request, mapping, frame, engine, queries, metadata)
        card = None
    else:
        result_tables, extra = _grouped(request, mapping, frame, engine, queries)
        card = column_metric_card(mapping.metric_columns[0], table_name=mapping.table_name, metadata=metadata or {"columns": list(frame.columns)}, mapping=mapping.to_dict(), parameters={**parameters, "aggregation": mapping.aggregation})
    spec = build_exploration_chart_spec(result_tables, request["kind"])
    total = extra["scope_row_count"]
    value_summary = ""
    if "exploration_totals" in result_tables:
        row = result_tables["exploration_totals"].query("scope == 'all'").iloc[0]
        number = row["metric_value"]
        value_summary = f" 全范围 {extra['aggregation']} 为 {number:.8g}。" if pd.notna(number) else " 全范围指标未定义（无有效值或分母为零）。"
    findings = [f"已对 {mapping.table_name} 当前筛选范围的 {total} 行进行全量描述性探索。" + value_summary, extra["display_note"]]
    return PlaybookExecutionResult(playbook.playbook_id, playbook.display_name, "PASS", parameters,
        findings, [CAVEAT, extra["display_note"]], result_tables, [spec] if spec else [], queries, [],
        {"exploration": {"request": request, "metric_card": card, **extra}, "safe_query_generated": True})
