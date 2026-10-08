"""In-memory CSV and Excel loading utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO
import re

import pandas as pd


@dataclass
class LoadedTable:
    name: str
    source_type: str
    source_name: str
    dataframe: pd.DataFrame
    row_count: int
    column_count: int
    columns: list[str]
    warnings: list[str] = field(default_factory=list)


def sanitize_table_name(name: str) -> str:
    """Return a SQL-safe table name containing only letters, digits, and underscores."""

    stem = Path(str(name or "")).stem or str(name or "")
    sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", stem.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_").lower()
    if not sanitized:
        sanitized = "uploaded_table"
    if sanitized[0].isdigit():
        sanitized = f"table_{sanitized}"
    return sanitized


def _check_size(file_obj: Any, max_bytes: int = 100 * 1024 * 1024) -> None:
    if hasattr(file_obj, "seek") and hasattr(file_obj, "tell"):
        file_obj.seek(0, 2)
        size = file_obj.tell()
        file_obj.seek(0)
        if size > max_bytes:
            raise ValueError("文件超过大小限制，请缩小输入。")


def _seek_start(file_obj: Any) -> None:
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)


def _source_name(file_obj: Any, fallback: str) -> str:
    return Path(str(getattr(file_obj, "name", "") or fallback)).name


def _clean_columns(columns: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    cleaned: list[str] = []
    for index, column in enumerate(columns, start=1):
        name = "" if column is None else str(column).strip()
        if not name or name.lower().startswith("unnamed:"):
            name = f"column_{index}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        cleaned.append(name if count == 0 else f"{name}_{count + 1}")
    return cleaned


def _build_loaded_table(name: str, source_type: str, source_name: str, df: pd.DataFrame, warnings: list[str]) -> LoadedTable:
    df = df.copy()
    df.columns = _clean_columns(list(df.columns))
    if df.empty:
        warnings.append("读取结果为空，请确认文件或 sheet 中包含可分析数据。")
    return LoadedTable(
        name=sanitize_table_name(name),
        source_type=source_type,
        source_name=source_name,
        dataframe=df,
        row_count=int(len(df)),
        column_count=int(len(df.columns)),
        columns=[str(column) for column in df.columns],
        warnings=warnings,
    )


def read_csv_file(file_obj: BinaryIO, table_name: str | None = None, **kwargs: Any) -> LoadedTable:
    """Read a CSV file-like object into a LoadedTable without writing it to disk."""

    source = _source_name(file_obj, table_name or "uploaded_table.csv")
    read_kwargs = dict(kwargs)
    read_kwargs.pop("max_rows_preview", None)
    warnings: list[str] = []
    last_error: Exception | None = None
    requested_encoding = read_kwargs.pop("encoding", None)
    max_rows = int(read_kwargs.pop("max_rows", 1000000))
    max_bytes = int(read_kwargs.pop("max_bytes", 100 * 1024 * 1024))
    _check_size(file_obj, max_bytes)
    requested_rows = read_kwargs.pop("nrows", None)
    # Probe one extra row only when enforcing the global input cap. An explicit
    # smaller nrows is a selection request and must be returned exactly.
    read_kwargs["nrows"] = max_rows + 1 if requested_rows is None or int(requested_rows) > max_rows else int(requested_rows)
    for encoding in ([requested_encoding] if requested_encoding else ("utf-8-sig", "utf-8", "gbk")):
        try:
            _seek_start(file_obj)
            df = pd.read_csv(file_obj, encoding=encoding, **read_kwargs)
        except pd.errors.EmptyDataError as exc:
            raise ValueError("CSV 文件为空，无法读取。") from exc
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except Exception as exc:
            last_error = exc
            break
        if len(df) > max_rows:
            raise ValueError(f"CSV 行数超过上限 {max_rows}，请缩小输入数据或明确选择读取行数。")
        warnings.append(f"CSV 使用 {encoding} 编码读取。")
        return _build_loaded_table(table_name or source, "uploaded_file", source, df, warnings)
    raise ValueError("CSV 文件读取失败，请确认编码、分隔符和文件内容。") from last_error


def get_excel_sheet_names(file_obj: BinaryIO) -> list[str]:
    """Return sheet names from an Excel file-like object."""

    try:
        _seek_start(file_obj)
        _check_size(file_obj)
        with pd.ExcelFile(file_obj) as workbook:
            return [str(sheet_name) for sheet_name in workbook.sheet_names]
    except ImportError as exc:
        raise ImportError("读取 Excel 需要 openpyxl 或对应 Excel 引擎，请先安装 requirements.txt。") from exc
    finally:
        _seek_start(file_obj)


def read_excel_file(
    file_obj: BinaryIO,
    sheet_name: str | int | None = 0,
    table_name: str | None = None,
    **kwargs: Any,
) -> LoadedTable:
    """Read a selected Excel sheet into a LoadedTable."""

    source = _source_name(file_obj, table_name or "uploaded_table.xlsx")
    warnings: list[str] = []
    try:
        _seek_start(file_obj)
        _check_size(file_obj, int(kwargs.pop("max_bytes", 100 * 1024 * 1024)))
        max_rows = int(kwargs.pop("max_rows", 1000000))
        requested_rows = kwargs.pop("nrows", None)
        kwargs["nrows"] = max_rows + 1 if requested_rows is None or int(requested_rows) > max_rows else int(requested_rows)
        df = pd.read_excel(file_obj, sheet_name=0 if sheet_name is None else sheet_name, **kwargs)
        if len(df) > max_rows:
            raise ValueError("Excel 行数超过限制，请缩小输入。")
    except ImportError as exc:
        raise ImportError("读取 Excel 需要 openpyxl 或对应 Excel 引擎，请先安装 requirements.txt。") from exc
    except ValueError as exc:
        raise ValueError(f"Excel sheet 读取失败：{exc}") from exc
    finally:
        _seek_start(file_obj)
    if df.empty:
        warnings.append("Excel sheet 为空，请选择包含数据的 sheet。")
    sheet_suffix = "" if sheet_name in (None, 0) else f"_{sheet_name}"
    return _build_loaded_table(table_name or f"{source}{sheet_suffix}", "uploaded_file", source, df, warnings)


def load_uploaded_file(
    file_obj: BinaryIO,
    filename: str,
    sheet_name: str | int | None = None,
    table_name: str | None = None,
) -> LoadedTable:
    """Load a supported uploaded file entirely in memory."""

    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return read_csv_file(file_obj, table_name=table_name or filename)
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return read_excel_file(file_obj, sheet_name=0 if sheet_name is None else sheet_name, table_name=table_name or filename)
    raise ValueError(f"不支持的文件格式：{suffix or 'unknown'}。请上传 CSV 或 Excel 文件。")
