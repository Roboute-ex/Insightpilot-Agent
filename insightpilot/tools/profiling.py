"""DataFrame profiling helpers."""

from __future__ import annotations

import pandas as pd


def profile_dataframe(df: pd.DataFrame) -> dict[str, object]:
    """Return a compact profile for a pandas DataFrame."""

    return {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "missing_rate_by_column": df.isna().mean().round(4).to_dict(),
        "numeric_columns": list(df.select_dtypes(include="number").columns),
        "categorical_columns": list(df.select_dtypes(exclude="number").columns),
    }
