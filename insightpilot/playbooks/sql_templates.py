"""Allowlisted, parameterized SQL templates used by analysis playbooks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


ALLOWED_AGGREGATIONS = {"sum": "SUM", "mean": "AVG", "count": "COUNT", "min": "MIN", "max": "MAX"}
ALLOWED_TIME_GRAINS = {"day", "week", "month"}


@dataclass(frozen=True)
class SQLTemplateResult:
    template_id: str
    sql: str
    parameters: list[Any] | dict[str, Any] = field(default_factory=list)
    referenced_tables: list[str] = field(default_factory=list)
    referenced_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_identifier(identifier: str, allowed_identifiers: set[str]) -> str:
    value = str(identifier)
    if value not in allowed_identifiers:
        raise ValueError(f"SQL identifier 不在允许列表中：{value}")
    if "\x00" in value:
        raise ValueError("SQL identifier 包含无效字符。")
    return value


def quote_identifier(identifier: str, allowed_identifiers: set[str]) -> str:
    value = validate_identifier(identifier, allowed_identifiers)
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def _identifiers(
    table_name: str,
    columns: Iterable[str],
    allowed_identifiers: set[str] | None,
) -> tuple[str, list[str], set[str]]:
    column_list = [str(column) for column in columns]
    if allowed_identifiers is None:
        raise ValueError("生成 SQL template 必须提供 allowed_identifiers。")
    table_sql = quote_identifier(table_name, allowed_identifiers)
    for column in column_list:
        validate_identifier(column, allowed_identifiers)
    return table_sql, column_list, allowed_identifiers


def _aggregation(value: str) -> str:
    try:
        return ALLOWED_AGGREGATIONS[value]
    except KeyError as exc:
        raise ValueError(f"不支持的聚合方式：{value}") from exc


def _columns(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def build_profile_query(
    table_name: str,
    columns: list[str] | None = None,
    allowed_identifiers: set[str] | None = None,
    limit: int = 1000,
) -> SQLTemplateResult:
    selected = list(columns or [])
    table_sql, selected, allowlist = _identifiers(table_name, selected, allowed_identifiers)
    select_sql = ", ".join(quote_identifier(column, allowlist) for column in selected) or "*"
    return SQLTemplateResult(
        template_id="data_profile",
        sql=f"SELECT {select_sql} FROM {table_sql} LIMIT ?",
        parameters=[int(limit)],
        referenced_tables=[table_name],
        referenced_columns=selected,
    )


def build_metric_trend_query(
    table_name: str,
    date_column: str,
    metric_columns: str | list[str],
    allowed_identifiers: set[str] | None = None,
    time_grain: str = "day",
    aggregation: str = "sum",
    date_from: Any | None = None,
    date_to: Any | None = None,
) -> SQLTemplateResult:
    metrics = _columns(metric_columns)
    table_sql, referenced, allowlist = _identifiers(table_name, [date_column, *metrics], allowed_identifiers)
    if time_grain not in ALLOWED_TIME_GRAINS:
        raise ValueError(f"不支持的 time_grain：{time_grain}")
    aggregate_sql = _aggregation(aggregation)
    date_sql = quote_identifier(date_column, allowlist)
    metric_sql = ", ".join(
        f"{aggregate_sql}({quote_identifier(metric, allowlist)}) AS {quote_identifier(metric, allowlist)}"
        for metric in metrics
    )
    where: list[str] = []
    parameters: list[Any] = []
    if date_from is not None:
        where.append(f"{date_sql} >= ?")
        parameters.append(date_from)
    if date_to is not None:
        where.append(f"{date_sql} <= ?")
        parameters.append(date_to)
    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    period_sql = f"date_trunc('{time_grain}', CAST({date_sql} AS TIMESTAMP))"
    sql = (
        f"SELECT {period_sql} AS period, {metric_sql} FROM {table_sql}{where_sql} "
        "GROUP BY period ORDER BY period"
    )
    return SQLTemplateResult(
        template_id="metric_trend",
        sql=sql,
        parameters=parameters,
        referenced_tables=[table_name],
        referenced_columns=referenced,
    )


def build_period_comparison_query(
    table_name: str,
    date_column: str,
    metric_column: str,
    allowed_identifiers: set[str] | None = None,
    current_start: Any | None = None,
    current_end: Any | None = None,
    previous_start: Any | None = None,
    previous_end: Any | None = None,
    dimension_column: str | None = None,
    aggregation: str = "sum",
) -> SQLTemplateResult:
    columns = [date_column, metric_column] + ([dimension_column] if dimension_column else [])
    table_sql, referenced, allowlist = _identifiers(table_name, columns, allowed_identifiers)
    date_sql = quote_identifier(date_column, allowlist)
    metric_sql = quote_identifier(metric_column, allowlist)
    aggregate_sql = _aggregation(aggregation)
    parameters = [current_start, current_end, previous_start, previous_end]
    period_case = f"CASE WHEN {date_sql} >= ? AND {date_sql} <= ? THEN 'current' ELSE 'previous' END"
    select_dimension = ""
    group_dimension = ""
    if dimension_column:
        dimension_sql = quote_identifier(dimension_column, allowlist)
        select_dimension = f", {dimension_sql} AS dimension_value"
        group_dimension = ", dimension_value"
    sql = (
        f"SELECT {period_case} AS comparison_period{select_dimension}, "
        f"{aggregate_sql}({metric_sql}) AS metric_value FROM {table_sql} "
        f"WHERE ({date_sql} >= ? AND {date_sql} <= ?) OR ({date_sql} >= ? AND {date_sql} <= ?) "
        f"GROUP BY comparison_period{group_dimension} ORDER BY comparison_period{group_dimension}"
    )
    parameters = [current_start, current_end, current_start, current_end, previous_start, previous_end]
    return SQLTemplateResult(
        template_id="period_comparison",
        sql=sql,
        parameters=parameters,
        referenced_tables=[table_name],
        referenced_columns=referenced,
    )


def build_dimension_contribution_query(
    table_name: str,
    dimension_column: str,
    metric_column: str,
    allowed_identifiers: set[str] | None = None,
    aggregation: str = "sum",
    top_n: int = 10,
) -> SQLTemplateResult:
    table_sql, referenced, allowlist = _identifiers(
        table_name, [dimension_column, metric_column], allowed_identifiers
    )
    dimension_sql = quote_identifier(dimension_column, allowlist)
    metric_sql = quote_identifier(metric_column, allowlist)
    aggregate_sql = _aggregation(aggregation)
    sql = (
        f"SELECT {dimension_sql} AS dimension_value, {aggregate_sql}({metric_sql}) AS metric_value "
        f"FROM {table_sql} GROUP BY {dimension_sql} ORDER BY metric_value DESC LIMIT ?"
    )
    return SQLTemplateResult(
        template_id="dimension_contribution",
        sql=sql,
        parameters=[int(top_n)],
        referenced_tables=[table_name],
        referenced_columns=referenced,
    )


def build_experiment_summary_query(
    table_name: str,
    group_column: str,
    metric_column: str,
    allowed_identifiers: set[str] | None = None,
    control_value: Any = "control",
    treatment_value: Any = "treatment",
) -> SQLTemplateResult:
    table_sql, referenced, allowlist = _identifiers(
        table_name, [group_column, metric_column], allowed_identifiers
    )
    group_sql = quote_identifier(group_column, allowlist)
    metric_sql = quote_identifier(metric_column, allowlist)
    sql = (
        f"SELECT {group_sql} AS group_value, COUNT(*) AS sample_size, AVG({metric_sql}) AS metric_mean, "
        f"STDDEV_SAMP({metric_sql}) AS metric_std FROM {table_sql} "
        f"WHERE {group_sql} IN (?, ?) GROUP BY {group_sql} ORDER BY {group_sql}"
    )
    return SQLTemplateResult(
        template_id="experiment_summary",
        sql=sql,
        parameters=[control_value, treatment_value],
        referenced_tables=[table_name],
        referenced_columns=referenced,
    )
