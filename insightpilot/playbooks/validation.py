"""Validation for playbook mappings and safe user parameters."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from insightpilot.ingestion.mapping import ColumnMapping
from insightpilot.playbooks.models import AnalysisPlaybook


def _as_columns(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _date_pair(value: Any) -> tuple[Any, Any] | None:
    if isinstance(value, dict):
        return value.get("start"), value.get("end")
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return value[0], value[1]
    return None


def _parse_date(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value)
    try:
        return pd.Timestamp(str(value))
    except (TypeError, ValueError):
        return None


def validate_playbook_parameters(
    playbook: AnalysisPlaybook,
    parameters: dict[str, Any],
    mapping: ColumnMapping,
    available_columns: list[str],
    dataframe: pd.DataFrame | None = None,
) -> list[str]:
    """Return clear validation errors without running any query."""

    errors = list(playbook.validate_mapping(mapping))
    definitions = {parameter.name: parameter for parameter in playbook.parameters}
    exploration = parameters.get("exploration_request")
    if "exploration_request" in parameters:
        from insightpilot.analysis.exploration import validate_exploration_request
        if playbook.playbook_id not in {"data_profile", "dimension_contribution"}:
            errors.append("该分析剧本不支持单表探索请求。")
        else:
            errors.extend(validate_exploration_request(exploration, mapping, available_columns))
            if isinstance(exploration, dict):
                expected = "data_profile" if exploration.get("kind") == "distribution" else "dimension_contribution"
                if playbook.playbook_id != expected:
                    errors.append("探索类型与所选剧本不一致。")
    for name in playbook.required_parameter_names():
        if parameters.get(name) in (None, "", []):
            errors.append(f"缺少必填参数：{name}。")

    for name, value in parameters.items():
        if name == "exploration_request":
            continue
        definition = definitions.get(name)
        if definition is None:
            errors.append(f"不支持的 playbook 参数：{name}。")
            continue
        if value in (None, ""):
            continue
        if definition.choices and value not in definition.choices and not (exploration and name == "aggregation" and value == "ratio_of_sums"):
            errors.append(f"参数 {name} 必须是：{', '.join(map(str, definition.choices))}。")
        if definition.parameter_type == "column":
            if str(value) not in available_columns:
                errors.append(f"参数 {name} 指定的列不存在：{value}。")
        elif definition.parameter_type in {"metric_columns", "dimension_columns"}:
            for column in _as_columns(value):
                if column not in available_columns:
                    errors.append(f"参数 {name} 指定的列不存在：{column}。")
        elif definition.parameter_type == "integer":
            try:
                int(value)
            except (TypeError, ValueError):
                errors.append(f"参数 {name} 必须是整数。")
        elif definition.parameter_type == "float":
            try:
                float(value)
            except (TypeError, ValueError):
                errors.append(f"参数 {name} 必须是数值。")
        elif definition.parameter_type == "date" and _parse_date(value) is None:
            errors.append(f"参数 {name} 不是有效日期。")
        elif definition.parameter_type == "date_range":
            pair = _date_pair(value)
            if pair is None or _parse_date(pair[0]) is None or _parse_date(pair[1]) is None:
                errors.append(f"参数 {name} 必须包含有效的开始和结束日期。")
            elif _parse_date(pair[0]) > _parse_date(pair[1]):
                errors.append(f"参数 {name} 的开始日期不能晚于结束日期。")

    for name, minimum, maximum in [
        ("top_n", 1, 100),
        ("rolling_window", 1, 90),
        ("confidence_level", 0.8, 0.99),
    ]:
        if parameters.get(name) not in (None, ""):
            try:
                numeric = float(parameters[name])
            except (TypeError, ValueError):
                continue
            if not minimum <= numeric <= maximum:
                errors.append(f"参数 {name} 必须位于 {minimum} 到 {maximum} 之间。")

    date_pairs = [
        ("current_start", "current_end", "当前周期"),
        ("previous_start", "previous_end", "对比周期"),
    ]
    for start_name, end_name, label in date_pairs:
        start = _parse_date(parameters.get(start_name))
        end = _parse_date(parameters.get(end_name))
        if (start is None) != (end is None):
            errors.append(f"{label}需要同时提供开始和结束日期。")
        elif start is not None and end is not None and start > end:
            errors.append(f"{label}开始日期不能晚于结束日期。")

    if mapping.group_column and dataframe is not None and mapping.group_column in dataframe.columns:
        group_count = int(dataframe[mapping.group_column].dropna().nunique())
        if group_count < 2:
            errors.append("group_column 至少需要两个有效分组。")

    if dataframe is not None and exploration is None:
        metric_candidates = list(mapping.metric_columns)
        metric_parameter = parameters.get("metric")
        if metric_parameter:
            metric_candidates.append(str(metric_parameter))
        for column in dict.fromkeys(metric_candidates):
            if column in dataframe.columns and not pd.api.types.is_numeric_dtype(dataframe[column]):
                converted = pd.to_numeric(dataframe[column], errors="coerce")
                if converted.notna().sum() == 0:
                    errors.append(f"指标列无法转换为数值：{column}。")
        if mapping.date_column and mapping.date_column in dataframe.columns:
            converted_dates = pd.to_datetime(dataframe[mapping.date_column], errors="coerce")
            if converted_dates.notna().sum() == 0:
                errors.append(f"日期列无法转换为 datetime：{mapping.date_column}。")

    return list(dict.fromkeys(errors))
