"""Read genuine BIFF XLS, macro-enabled OOXML XLSM, and encoded CSV fixtures."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd
import pytest

from insightpilot.ingestion.file_loader import get_excel_sheet_names, load_uploaded_file, read_csv_file, read_excel_file
from insightpilot.ingestion.table_registry import TableRegistry


def _ooxml_workbook(*, macro_enabled: bool = False) -> BytesIO:
    xlsx = BytesIO()
    with pd.ExcelWriter(xlsx, engine="openpyxl") as writer:
        pd.DataFrame({"日期": ["2026-06-29", "2026-06-30"], "金额": [120.5, 130.25], "城市": ["北城", "南城"]}).to_excel(writer, sheet_name="交易", index=False)
        pd.DataFrame({"日期": ["2026-06-30"], "金额": [5.25], "城市": ["南城"]}).to_excel(writer, sheet_name="退款", index=False)
    if not macro_enabled:
        xlsx.seek(0)
        return xlsx
    # Macro-enabled workbooks may validly contain no VBA project. Change the
    # package content type, not merely the filename; never add executable macros.
    xlsm = BytesIO()
    with ZipFile(xlsx) as original, ZipFile(xlsm, "w", compression=ZIP_DEFLATED) as target:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "[Content_Types].xml":
                data = data.replace(b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml", b"application/vnd.ms-excel.sheet.macroEnabled.main+xml")
            target.writestr(info.filename, data)
    xlsm.seek(0)
    return xlsm


def test_genuine_biff_xls_chinese_sheets_and_numeric_values():
    fixture = Path(__file__).with_name("fixtures") / "format_recovery.xls"
    payload = fixture.read_bytes()
    assert payload[:8] == bytes.fromhex("d0cf11e0a1b11ae1")  # OLE/BIFF, not renamed OOXML.
    stream = BytesIO(payload)
    with pd.ExcelFile(stream) as workbook:
        assert workbook.engine == "xlrd"
    assert get_excel_sheet_names(stream) == ["交易", "退款"]
    transaction = load_uploaded_file(stream, "真实格式.xls", sheet_name="交易")
    refund = read_excel_file(stream, sheet_name="退款")
    assert transaction.columns == ["日期", "金额", "城市"]
    assert transaction.dataframe.loc[0, "金额"] == 125.5
    assert transaction.dataframe.loc[0, "城市"] == "南城"
    assert refund.dataframe.loc[0, "金额"] == 5.25


def test_macro_enabled_ooxml_xlsm_is_real_package_without_macro_execution():
    stream = _ooxml_workbook(macro_enabled=True)
    with ZipFile(stream) as workbook:
        assert b"application/vnd.ms-excel.sheet.macroEnabled.main+xml" in workbook.read("[Content_Types].xml")
        assert not any(name.endswith("vbaProject.bin") for name in workbook.namelist())
    assert get_excel_sheet_names(stream) == ["交易", "退款"]
    loaded = load_uploaded_file(stream, "模拟数据.xlsm", sheet_name="交易")
    assert loaded.dataframe["金额"].tolist() == [120.5, 130.25]
    assert loaded.row_count == 2


def test_xlsx_multiple_selected_sheets_preserve_all_tables_and_names():
    stream = _ooxml_workbook()
    registry = TableRegistry()
    names = []
    for sheet in ["退款", "交易"]:
        loaded = read_excel_file(stream, sheet_name=sheet, table_name="selected_table")
        names.append(registry.add_table(loaded.name, loaded.dataframe, loaded.source_type, loaded.source_name))
    assert len(set(names)) == 2
    assert [len(registry.get_table(name)) for name in names] == [1, 2]
    assert registry.get_table(names[0])["金额"].sum() == 5.25
    assert registry.get_table(names[1])["金额"].sum() == 250.75


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "gbk"])
def test_real_csv_encodings_and_explicit_semicolon_roundtrip(encoding):
    text = "日期;收入;城市\n2026-06-29;120.5;北城\n2026-06-30;130.25;南城\n"
    stream = BytesIO(text.encode(encoding))
    stream.seek(len(stream.getvalue()))
    loaded = read_csv_file(stream, encoding=encoding, sep=";")
    assert loaded.columns == ["日期", "收入", "城市"]
    assert loaded.dataframe["城市"].tolist() == ["北城", "南城"]
    assert loaded.dataframe["收入"].sum() == 250.75


def test_gbk_detection_retries_from_start_and_duplicate_columns_are_disambiguated():
    text = "日期,金额,金额\n2026-06-30,1,2\n"
    stream = BytesIO(text.encode("gbk"))
    stream.seek(5)
    loaded = read_csv_file(stream)
    assert loaded.dataframe.iloc[0].tolist() == ["2026-06-30", 1, 2]
    assert len(set(loaded.columns)) == 3
    assert any("gbk" in warning for warning in loaded.warnings)


def test_csv_explicit_row_selection_and_cap_error_are_distinct():
    stream = BytesIO(b"amount\n1\n2\n3\n")
    assert read_csv_file(stream, nrows=1).dataframe["amount"].tolist() == [1]
    assert read_csv_file(stream, nrows=0).dataframe.empty
    with pytest.raises(ValueError, match="CSV 行数超过上限 1") as error:
        read_csv_file(stream, max_rows=1)
    assert "编码" not in str(error.value)
    with pytest.raises(ValueError, match="CSV 行数超过上限 1"):
        read_csv_file(stream, nrows=20, max_rows=1)
    assert read_csv_file(stream, nrows=1, max_rows=1).dataframe["amount"].tolist() == [1]


def test_excel_explicit_row_selection_does_not_include_probe_row():
    stream = _ooxml_workbook()
    selected = read_excel_file(stream, sheet_name="交易", nrows=1)
    assert selected.row_count == 1 and selected.dataframe["金额"].tolist() == [120.5]
    with pytest.raises(ValueError, match="行数超过限制"):
        read_excel_file(stream, sheet_name="交易", max_rows=1)
