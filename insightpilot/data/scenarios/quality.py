"""Opt-in, documented synthetic quality faults; clean datasets remain unchanged."""
from __future__ import annotations

from copy import deepcopy

import pandas as pd

from .common import DemoDataset


def with_quality_issues(dataset: DemoDataset, table_name: str, *, missing_column: str | None = None,
                        duplicate_rows: int = 0) -> DemoDataset:
    """Return a copied table with controlled faults and an explicit audit record.

    Duplicate rows remain exact copies so normal duplicate checks can detect them.
    Metadata records their inserted positions. No analyzer reads this audit record.
    """
    if table_name not in dataset.tables:
        raise ValueError(f"模拟质量测试表不存在：{table_name}")
    frame = dataset.tables[table_name].copy(deep=True)
    if missing_column is not None and missing_column not in frame.columns:
        raise ValueError(f"待注入缺失的列不存在：{missing_column}")
    if not 0 <= duplicate_rows <= min(10, len(frame)):
        raise ValueError("模拟重复行数应在0至10之间且不超过源表行数。")
    faults: list[dict[str, object]] = []
    if missing_column is not None and not frame.empty:
        frame.loc[frame.index[0], missing_column] = None
        faults.append({"kind": "missing", "row_position": 0, "column": missing_column})
    if duplicate_rows:
        original_length = len(frame)
        frame = pd.concat([frame, frame.iloc[:duplicate_rows]], ignore_index=True)
        faults.append({"kind": "duplicate", "source_positions": list(range(duplicate_rows)), "inserted_positions": list(range(original_length, len(frame)))})
    tables = {**dataset.tables, table_name: frame}
    details = deepcopy(dataset.metadata)
    details["quality_test_faults"] = {"table": table_name, "faults": faults}
    details["row_counts"][table_name] = len(frame)
    details["quality_test_warning"] = "此变体为显式质量测试；重复行可能影响计数，须先检测/去重，不能当干净分析结果。"
    return DemoDataset(dataset.scenario, tables, details)
