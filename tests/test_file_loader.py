from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from insightpilot.ingestion.file_loader import (
    get_excel_sheet_names,
    load_uploaded_file,
    read_csv_file,
    read_excel_file,
    sanitize_table_name,
)


def test_sanitize_table_name() -> None:
    assert sanitize_table_name("123 demo-table.csv") == "table_123_demo_table"
    assert sanitize_table_name("") == "uploaded_table"


def test_read_csv_file_like_object() -> None:
    file_obj = BytesIO("日期,metric,city\n2026-01-01,10,A\n".encode("utf-8-sig"))
    loaded = read_csv_file(file_obj, table_name="Demo Table")
    assert loaded.name == "demo_table"
    assert loaded.row_count == 1
    assert loaded.columns == ["日期", "metric", "city"]


def test_read_excel_file_and_sheet_names() -> None:
    file_obj = BytesIO()
    with pd.ExcelWriter(file_obj, engine="openpyxl") as writer:
        pd.DataFrame({"date": ["2026-01-01"], "value": [1]}).to_excel(writer, sheet_name="SheetA", index=False)
        pd.DataFrame({"date": ["2026-01-02"], "value": [2]}).to_excel(writer, sheet_name="SheetB", index=False)
    file_obj.seek(0)
    assert get_excel_sheet_names(file_obj) == ["SheetA", "SheetB"]
    loaded = read_excel_file(file_obj, sheet_name="SheetB", table_name="excel_table")
    assert loaded.name == "excel_table"
    assert loaded.dataframe["value"].iloc[0] == 2


def test_load_uploaded_file_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError):
        load_uploaded_file(BytesIO(b"demo"), "demo.txt")


def test_empty_csv_has_friendly_error() -> None:
    with pytest.raises(ValueError, match="CSV 文件为空"):
        read_csv_file(BytesIO(b""), table_name="empty")
