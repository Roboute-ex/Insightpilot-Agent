"""Read-only, bounded database ingestion; query values never enter metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import pandas as pd
from insightpilot.ingestion.file_loader import sanitize_table_name
from insightpilot.tools.sql_safety import (validate_read_query, redact_sql_values, bounded_read_query,
    validate_bound_parameters, SAFE_FUNCTIONS, SQLPolicyError)
from insightpilot.performance_tasks import cancellation_checkpoint

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

def is_safe_select_query(query: str, dialect: str = "duckdb") -> bool:
    try:
        validate_read_query(query, dialect=dialect)
        return True
    except ValueError:
        return False

def normalize_database_url(url: str) -> str:
    normalized = (url or "").strip()
    if not normalized:
        raise ValueError("database_url 不能为空。")
    return normalized

def mask_database_url(url: str) -> str:
    normalized = normalize_database_url(url)
    parsed = urlsplit(normalized)
    if parsed.scheme.startswith("sqlite") and not parsed.query and not parsed.fragment:
        return normalized
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        netloc = userinfo.split(":", 1)[0] + ":***@" + host if ":" in userinfo else netloc
    # Even innocuous query parameter names can carry credentials; redact all values.
    query = urlencode([(key, "***") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)])
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, ""))

def database_dialect(database_url: str) -> str:
    """Resolve a backend without connecting; unverified backends fail policy."""
    from sqlalchemy import make_url
    try:
        backend = make_url(normalize_database_url(database_url)).get_backend_name()
    except Exception:
        raise ValueError("数据库地址格式无效，请检查本地连接配置。") from None
    return "sqlite" if backend == "sqlite" else backend


def _limit_query(query: str, limit: int | None, *, dialect: str = "sqlite",
                 allowed_tables: set[str] | None = None, table_columns=None) -> tuple[str, list[str]]:
    return bounded_read_query(query, limit, dialect=dialect,
        allowed_tables=allowed_tables or set(), table_columns=table_columns or {}), []


def _sqlite_scope(connection) -> dict[str, list[str]]:
    # Trusted internal introspection runs before the user-query authorizer.
    names = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'")]
    schema = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        schema[name] = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted})")]
    return schema


def _sqlite_authorizer(schema):
    """Check expanded view reads/functions too, not merely their outer AST."""
    allowed = {name.casefold(): {col.casefold() for col in cols} for name, cols in schema.items()}
    def authorize(action, first, second, database, trigger):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            names = allowed.get(str(first).casefold())
            # SQLite uses an empty column for COUNT(*) / EXISTS.
            if database == "main" and names is not None and (not second or str(second).casefold() in names):
                return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if str(second).upper() in SAFE_FUNCTIONS:
                return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY
    return authorize


def run_database_query(database_url: str, query: str, table_name: str = "db_query_result",
                       limit: int | None = 10000, timeout_seconds: float = 30.0,
                       parameters: list | dict | None = None) -> DatabaseQueryResult:
    from sqlalchemy import make_url
    dialect = database_dialect(database_url)
    # All unverified backends fail BEFORE opening any connection.
    validate_read_query(query, dialect=dialect)
    validate_bound_parameters(parameters)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100000:
        raise ValueError("取数上限必须是 1 到 100000 之间的整数。")
    if not 0 < timeout_seconds <= 3600:
        raise ValueError("查询超时必须在 0 到 3600 秒之间。")
    url = make_url(normalize_database_url(database_url))
    if not url.database or url.database == ":memory:":
        raise ValueError("请选择已存在的 SQLite 文件。")
    path = Path(url.database).resolve()
    if not path.is_file():
        raise ValueError("SQLite 文件不存在，不会创建新数据库。")
    connection = None
    try:
        cancellation_checkpoint()
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=timeout_seconds)
        connection.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + timeout_seconds
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        schema = _sqlite_scope(connection)
        effective_query, warnings = _limit_query(query, limit, dialect=dialect,
            allowed_tables=set(schema), table_columns=schema)
        cancellation_checkpoint()
        connection.set_authorizer(_sqlite_authorizer(schema))
        cursor = connection.execute(effective_query, parameters if parameters is not None else ())
        rows = cursor.fetchmany(limit + 1)
        cancellation_checkpoint()
        frame = pd.DataFrame.from_records(rows, columns=[item[0] for item in cursor.description])
        if len(frame) > limit:
            frame = frame.iloc[:limit].copy()
            warnings.append(f"结果超过 {limit} 行，已截断；分析只覆盖本次授权取数范围。")
    except SQLPolicyError:
        raise
    except Exception:
        raise ValueError("只读数据库查询失败：请检查字段、只读权限、函数或超时限制。未执行无限制回退；详细地址和查询值已隐藏。") from None
    finally:
        if connection is not None:
            connection.close()
    return DatabaseQueryResult(sanitize_table_name(table_name), "database", redact_sql_values(query, dialect=dialect),
        frame, len(frame), len(frame.columns), list(map(str, frame.columns)), warnings)
