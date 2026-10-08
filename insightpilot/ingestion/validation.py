"""Validation helpers for custom analysis tables."""

from __future__ import annotations

from insightpilot.performance_tasks import cancellation_checkpoint

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype


def _has_date_like_column(df: pd.DataFrame) -> bool:
    for column in df.columns:
        cancellation_checkpoint()
        lowered = str(column).lower()
        if any(token in lowered for token in ("date", "day", "time", "日期", "时间")):
            return True
        if is_datetime64_any_dtype(df[column]):
            return True
    return False


def validate_dataframe_for_analysis(df: pd.DataFrame) -> list[str]:
    """Return non-blocking warnings for a DataFrame."""

    cancellation_checkpoint()
    warnings: list[str] = []
    if df.empty:
        warnings.append("DataFrame 为空，无法生成可靠分析。")
        return warnings
    if len(df) < 10:
        warnings.append("行数较少，结果仅适合作为结构检查。")
    if len(df.columns) < 2:
        warnings.append("列数较少，建议至少包含日期/维度和数值指标。")
    if not any(is_numeric_dtype(df[column]) for column in df.columns):
        warnings.append("未检测到数值列，无法执行指标趋势或异常检测。")
    if not _has_date_like_column(df):
        warnings.append("未检测到日期列，时间序列分析将受限。")
    duplicate_columns = pd.Index(df.columns).duplicated().sum()
    if duplicate_columns:
        warnings.append("存在重复列名，建议清洗后再分析。")
    empty_columns = [str(column) for column in df.columns if df[column].isna().all()]
    if empty_columns:
        warnings.append(f"存在全空列：{', '.join(empty_columns[:5])}。")
    high_missing = [
        str(column)
        for column in df.columns
        if len(df) and float(df[column].isna().mean()) >= 0.5
    ]
    if high_missing:
        warnings.append(f"存在高缺失率字段：{', '.join(high_missing[:5])}。")
    high_cardinality: list[str] = []
    for column in df.columns:
        cancellation_checkpoint()
        series = df[column]
        if not (
            pd.api.types.is_object_dtype(series)
            or pd.api.types.is_string_dtype(series)
            or isinstance(series.dtype, pd.CategoricalDtype)
        ):
            continue
        if len(df) and series.nunique(dropna=True) > max(100, len(df) * 0.5):
            high_cardinality.append(str(column))
    if high_cardinality:
        warnings.append(f"存在高基数字段：{', '.join(high_cardinality[:5])}，不适合作为优先维度。")
    return warnings


def validate_tables_for_workflow(tables: dict[str, pd.DataFrame]) -> list[str]:
    """Return warnings for a table collection without blocking workflow execution."""

    if not tables:
        return ["没有可用表，workflow 无法执行分析。"]
    cancellation_checkpoint()
    warnings: list[str] = []
    for name, df in tables.items():
        cancellation_checkpoint()
        for warning in validate_dataframe_for_analysis(df):
            warnings.append(f"{name}: {warning}")
    return warnings
