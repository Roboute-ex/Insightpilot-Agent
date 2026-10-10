"""One rule for matching user-selected group values to the groups in the data.

Shared by preflight, experiment comparison and causal exploration so that every
entry point selects exactly the same rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction
import math

import numpy as np
import pandas as pd


class GroupSelectionError(ValueError):
    """Raised when selected group values cannot identify two distinct data groups."""


def _exact_number(value: object) -> Fraction | None:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, (bool, int)):
        return Fraction(int(value))
    if isinstance(value, float):
        return Fraction(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            return Fraction(value.strip())
        except (ValueError, ZeroDivisionError):
            return None
    return None


def matches_group_value(series: pd.Series, value: object) -> pd.Series:
    """Rows whose group equals ``value`` without changing any group's identity.

    Numeric columns compare by exact number, so 0, 0.0 and "0" select the same group
    while large integers such as 2**53 and 2**53 + 1 stay distinct. Text columns
    compare by exact text, so "01" and "1" stay different groups.
    """

    mask = series.astype(str) == str(value)
    number = _exact_number(value)
    if number is not None and pd.api.types.is_numeric_dtype(series):
        if pd.api.types.is_integer_dtype(series) or pd.api.types.is_bool_dtype(series):
            if number.denominator == 1:
                try:
                    mask = mask | (series == int(number))
                except OverflowError:
                    pass
        else:
            try:
                as_float = float(number)
            except OverflowError:
                as_float = math.inf
            if math.isfinite(as_float) and Fraction(as_float) == number:
                mask = mask | (series == as_float)
    return mask.fillna(False).astype(bool)


def group_labels(series: pd.Series, *, treatment_value: object, control_value: object) -> pd.Series:
    """Label rows "treatment"/"control"; rows outside the two selected groups are NaN."""

    if treatment_value is None or control_value is None or str(treatment_value) == str(control_value):
        raise GroupSelectionError("请同时明确选择两个不同的处理组与对照组取值。")
    treated = matches_group_value(series, treatment_value)
    controlled = matches_group_value(series, control_value)
    if (treated & controlled).any():
        raise GroupSelectionError(f"处理组取值 {treatment_value} 与对照组取值 {control_value} 指向同一组数据，请选择两个不同的组。")
    absent = [str(value) for value, mask in ((treatment_value, treated), (control_value, controlled)) if not mask.any()]
    if absent:
        raise GroupSelectionError(f"所选组取值（{'、'.join(absent)}）在分组字段中不存在，请按数据中的实际取值选择。")
    labels = pd.Series(np.nan, index=series.index, dtype=object)
    labels[treated] = "treatment"
    labels[controlled] = "control"
    return labels


def group_value_position(values: Sequence[object], value: object) -> int | None:
    """Position of ``value`` in a column's distinct-value summary, matched by the same rule."""

    if not values:
        return None
    mask = matches_group_value(pd.Series(list(values)), value)
    return int(np.flatnonzero(mask.to_numpy())[0]) if mask.any() else None
