"""Deterministic validation for table, column, and metric contracts."""

from __future__ import annotations

from typing import Any

import pandas as pd

from insightpilot.contracts.models import ColumnContract, ContractCheckResult, MetricContract, TableContract


def _status(passed: bool, severity: str) -> str:
    if passed:
        return "PASS"
    return "FAIL" if severity == "error" else "WARN"


def _check(name: str, object_name: str, actual: Any, expected: Any, passed: bool, severity: str, message: str) -> ContractCheckResult:
    return ContractCheckResult(name, object_name, actual, expected, severity, _status(passed, severity), message)


def _validate_column(table_name: str, frame: pd.DataFrame, contract: ColumnContract) -> list[ContractCheckResult]:
    object_name = f"{table_name}.{contract.column_name}"
    if contract.column_name not in frame.columns:
        return [_check("column_exists", object_name, False, True, False, contract.severity, "缺少契约要求的字段。")]
    series = frame[contract.column_name]
    results = [_check("column_exists", object_name, True, True, True, contract.severity, "字段存在。")]
    if contract.data_type:
        actual_dtype = str(series.dtype)
        expected = contract.data_type.lower()
        dtype_passed = expected in actual_dtype.lower()
        if expected in {"number", "numeric"}:
            dtype_passed = pd.api.types.is_numeric_dtype(series)
        elif expected in {"date", "datetime"}:
            dtype_passed = pd.api.types.is_datetime64_any_dtype(series)
        elif expected in {"string", "category"}:
            dtype_passed = pd.api.types.is_object_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype)
        results.append(_check("column_type", object_name, actual_dtype, contract.data_type, dtype_passed, contract.severity, "检查字段类型。"))
    if not contract.nullable:
        missing = int(series.isna().sum())
        results.append(_check("column_not_null", object_name, missing, 0, missing == 0, contract.severity, "检查字段空值。"))
    if contract.unique:
        duplicate_count = int(series.duplicated().sum())
        results.append(_check("column_unique", object_name, duplicate_count, 0, duplicate_count == 0, contract.severity, "检查字段唯一性。"))
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if contract.minimum is not None:
        actual = float(numeric.min()) if not numeric.empty else None
        passed = actual is not None and actual >= contract.minimum
        results.append(_check("column_minimum", object_name, actual, contract.minimum, passed, contract.severity, "检查字段最小值。"))
    if contract.maximum is not None:
        actual = float(numeric.max()) if not numeric.empty else None
        passed = actual is not None and actual <= contract.maximum
        results.append(_check("column_maximum", object_name, actual, contract.maximum, passed, contract.severity, "检查字段最大值。"))
    if contract.allowed_values:
        invalid = sorted(set(series.dropna().tolist()) - set(contract.allowed_values), key=str)
        results.append(_check("column_allowed_values", object_name, invalid, contract.allowed_values, not invalid, contract.severity, "检查字段枚举范围。"))
    return results


def validate_table_contract(frame: pd.DataFrame | None, contract: TableContract) -> list[ContractCheckResult]:
    if frame is None:
        return [_check("table_exists", contract.table_name, False, True, False, contract.severity, "缺少契约要求的数据表。")]
    results = [_check("table_exists", contract.table_name, True, True, True, contract.severity, "数据表存在。")]
    row_count = int(len(frame))
    results.append(_check("table_minimum_rows", contract.table_name, row_count, contract.minimum_rows, row_count >= contract.minimum_rows, contract.severity, "检查最小行数。"))
    if contract.maximum_rows is not None:
        results.append(_check("table_maximum_rows", contract.table_name, row_count, contract.maximum_rows, row_count <= contract.maximum_rows, contract.severity, "检查最大行数。"))
    for column in contract.columns:
        results.extend(_validate_column(contract.table_name, frame, column))
    if contract.unique_key:
        missing = [column for column in contract.unique_key if column not in frame.columns]
        duplicate_count = int(frame.duplicated(contract.unique_key).sum()) if not missing else None
        results.append(
            _check(
                "table_unique_key",
                contract.table_name,
                duplicate_count if not missing else {"missing_columns": missing},
                0,
                not missing and duplicate_count == 0,
                contract.severity,
                "检查表级唯一键。",
            )
        )
    return results


def validate_metric_contract(values: pd.Series | list[Any], contract: MetricContract) -> list[ContractCheckResult]:
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    numeric = pd.to_numeric(series, errors="coerce")
    results: list[ContractCheckResult] = []
    if not contract.nullable:
        missing = int(numeric.isna().sum())
        results.append(_check("metric_not_null", contract.metric_id, missing, 0, missing == 0, contract.severity, "检查指标空值。"))
    valid = numeric.dropna()
    if contract.minimum is not None:
        actual = float(valid.min()) if not valid.empty else None
        results.append(_check("metric_minimum", contract.metric_id, actual, contract.minimum, actual is not None and actual >= contract.minimum, contract.severity, "检查指标最小值。"))
    if contract.maximum is not None:
        actual = float(valid.max()) if not valid.empty else None
        results.append(_check("metric_maximum", contract.metric_id, actual, contract.maximum, actual is not None and actual <= contract.maximum, contract.severity, "检查指标最大值。"))
    return results


def validate_contracts(tables: dict[str, pd.DataFrame], contracts: list[TableContract]) -> list[ContractCheckResult]:
    results: list[ContractCheckResult] = []
    for contract in contracts:
        results.extend(validate_table_contract(tables.get(contract.table_name), contract))
    return results
