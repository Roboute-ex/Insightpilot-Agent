"""Read-only database ingestion utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import re

import pandas as pd

from insightpilot.ingestion.file_loader import sanitize_table_name


BLOCKED_SQL_TOKENS = {
    "drop",
    "delete",
    "insert",
    "update",
    "alter",
    "create",
    "truncate",
    "merge",
    "replace",
    "grant",
    "revoke",
    "attach",
    "detach",
    "copy",
}


@dataclass
class DatabaseQueryResult:
    table_name: str
    source_type: str
    query: str
    dataframe: pd.DataFrame
    row_count: int
    column_count: int
    columns: list[str]
    warnings: list[str] = field(default_factory=list)


def _strip_sql_comments(query: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    return re.sub(r"--.*?$", " ", without_block, flags=re.MULTILINE).strip()


def is_safe_select_query(query: str) -> bool:
    """Conservatively allow only single SELECT/WITH read queries."""

    cleaned = _strip_sql_comments(query)
    if not cleaned:
        return False
    if ";" in cleaned.rstrip(";"):
        return False
    if cleaned.count(";") > 1:
        return False
    normalized = cleaned.rstrip(";").strip().lower()
    if not normalized.startswith(("select", "with")):
        return False
    tokens = set(re.findall(r"\b[a-z_]+\b", normalized))
    return not bool(tokens & BLOCKED_SQL_TOKENS)


def normalize_database_url(url: str) -> str:
    normalized = (url or "").strip()
    if not normalized:
        raise ValueError("database_url 不能为空。")
    return normalized


def mask_database_url(url: str) -> str:
    """Mask password in a database URL for UI/report display."""

    normalized = normalize_database_url(url)
    parsed = urlsplit(normalized)
    if not parsed.netloc or "@" not in parsed.netloc:
        return normalized
    userinfo, hostinfo = parsed.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return normalized
    username = userinfo.split(":", 1)[0]
    return urlunsplit((parsed.scheme, f"{username}:***@{hostinfo}", parsed.path, parsed.query, parsed.fragment))


def _limit_query(query: str, limit: int | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    cleaned = _strip_sql_comments(query).rstrip(";").strip()
    if limit is None:
        return cleaned, warnings
    if re.search(r"\blimit\s+\d+\b", cleaned, flags=re.IGNORECASE):
        return cleaned, warnings
    wrapped = f"SELECT * FROM ({cleaned}) AS source LIMIT {int(limit)}"
    return wrapped, warnings


def run_database_query(
    database_url: str,
    query: str,
    table_name: str = "db_query_result",
    limit: int | None = 10000,
) -> DatabaseQueryResult:
    """Run a read-only SQL query through SQLAlchemy and return an in-memory table."""

    if not is_safe_select_query(query):
        raise ValueError("SQL 安全检查未通过：仅允许单条 SELECT/WITH 查询，禁止写操作。")
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:
        raise ImportError("Database ingestion 需要 SQLAlchemy>=2.0，请先安装 requirements.txt。") from exc

    normalized_url = normalize_database_url(database_url)
    effective_query, warnings = _limit_query(query, limit)
    engine = create_engine(normalized_url)
    try:
        try:
            df = pd.read_sql_query(effective_query, engine)
        except Exception as exc:
            if effective_query != query:
                warnings.append("自动 LIMIT 包装查询失败，已尝试执行原始只读 query。")
                df = pd.read_sql_query(_strip_sql_comments(query).rstrip(";").strip(), engine)
            else:
                raise exc
    finally:
        engine.dispose()

    safe_name = sanitize_table_name(table_name or "db_query_result")
    return DatabaseQueryResult(
        table_name=safe_name,
        source_type="database",
        query=_strip_sql_comments(query).rstrip(";").strip(),
        dataframe=df,
        row_count=int(len(df)),
        column_count=int(len(df.columns)),
        columns=[str(column) for column in df.columns],
        warnings=warnings,
    )
