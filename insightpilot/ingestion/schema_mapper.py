"""Schema inference helpers for custom data tables."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
    is_object_dtype,
    is_string_dtype,
)


@dataclass(frozen=True)
class SchemaMappingSuggestion:
    table_name: str
    detected_date_columns: list[str] = field(default_factory=list)
    detected_numeric_columns: list[str] = field(default_factory=list)
    detected_categorical_columns: list[str] = field(default_factory=list)
    possible_metric_columns: list[str] = field(default_factory=list)
    possible_dimension_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _looks_like_date_column(name: str, series: pd.Series) -> bool:
    lowered = name.lower()
    if any(token in lowered for token in ("date", "day", "time", "日期", "时间")):
        return True
    return is_datetime64_any_dtype(series)


def _looks_like_id_column(name: str, series: pd.Series, row_count: int) -> bool:
    lowered = name.lower()
    if not any(token in lowered for token in ("id", "编号", "code")):
        return False
    if row_count == 0:
        return True
    return series.nunique(dropna=True) > max(20, row_count * 0.5)


def infer_schema_mapping(table_name: str, df: pd.DataFrame) -> SchemaMappingSuggestion:
    """Infer date, metric, and dimension column candidates with simple rules."""

    row_count = int(len(df))
    warnings: list[str] = []
    date_columns: list[str] = []
    numeric_columns: list[str] = []
    categorical_columns: list[str] = []
    metric_columns: list[str] = []
    dimension_columns: list[str] = []
    dimension_threshold = min(100, max(10, row_count * 0.3))

    for column in df.columns:
        name = str(column)
        series = df[column]
        if _looks_like_date_column(name, series):
            date_columns.append(name)
        if is_numeric_dtype(series) and not is_bool_dtype(series):
            numeric_columns.append(name)
            if not _looks_like_id_column(name, series, row_count):
                metric_columns.append(name)
        is_category = isinstance(series.dtype, pd.CategoricalDtype)
        if is_object_dtype(series) or is_string_dtype(series) or is_category or is_bool_dtype(series):
            unique_count = int(series.nunique(dropna=True))
            if unique_count <= dimension_threshold:
                categorical_columns.append(name)
                if not _looks_like_id_column(name, series, row_count):
                    dimension_columns.append(name)

    if not date_columns:
        warnings.append("未识别到日期列，时间趋势和异常检测将退化为描述性摘要。")
    if not numeric_columns:
        warnings.append("未识别到数值列，无法执行通用指标趋势或异常检测。")
    if row_count < 10:
        warnings.append("行数较少，结果仅适合作为结构检查。")
    if len(df.columns) > 50:
        warnings.append("列数较多，建议先筛选核心字段。")

    return SchemaMappingSuggestion(
        table_name=table_name,
        detected_date_columns=date_columns,
        detected_numeric_columns=numeric_columns,
        detected_categorical_columns=categorical_columns,
        possible_metric_columns=metric_columns,
        possible_dimension_columns=dimension_columns,
        warnings=warnings,
    )
