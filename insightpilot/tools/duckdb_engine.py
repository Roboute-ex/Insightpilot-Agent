"""DuckDB-backed local query engine with basic SQL safety checks."""

from __future__ import annotations

import re
from threading import Timer
from insightpilot.tools.sql_safety import (validate_read_query, validate_sql, SQLPolicyError, bounded_read_query, validate_bound_parameters)
from insightpilot.observability.tracer import trace_stage
from typing import Any

import pandas as pd

from insightpilot.ingestion.file_loader import sanitize_table_name

try:
    import duckdb
except ImportError as exc:  # pragma: no cover - dependency is declared for normal use
    duckdb = None
    _DUCKDB_IMPORT_ERROR = exc
else:
    _DUCKDB_IMPORT_ERROR = None


SAFE_QUERY_TEMPLATES: dict[str, str] = {
    "daily_metric_by_date": (
        "SELECT date, SUM({metric}) AS metric_value "
        "FROM daily_metrics GROUP BY date ORDER BY date"
    ),
    "dimension_contribution": (
        "SELECT {dimension}, date, SUM({metric}) AS metric_value "
        "FROM daily_metrics GROUP BY {dimension}, date"
    ),
}
safe_query_templates = SAFE_QUERY_TEMPLATES


class AnalyticsEngine:
    """Small in-memory DuckDB wrapper for synthetic pandas tables."""

    def __init__(self, max_rows: int = 100000, timeout_seconds: float = 30.0) -> None:
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or not 1 <= max_rows <= 100000:
            raise ValueError("查询行上限必须为 1 到 100000 的整数。")
        if not 0 < timeout_seconds <= 3600:
            raise ValueError("查询超时必须在 0 到 3600 秒之间。")
        if duckdb is None:
            raise ImportError("duckdb is required for AnalyticsEngine") from _DUCKDB_IMPORT_ERROR
        from insightpilot.performance import PerformanceConfig
        config=PerformanceConfig.from_environment()
        self._connection = None
        try:
            with trace_stage("database_connection",threads=config.duckdb_threads,memory_limit_mb=config.duckdb_memory_limit_mb,spill_enabled=False):
                self._connection = duckdb.connect(database=":memory:", config={"enable_external_access":"false","allow_unsigned_extensions":"false","threads":str(config.duckdb_threads),"memory_limit":f"{config.duckdb_memory_limit_mb}MB","temp_directory":"","max_temp_directory_size":"0B"})
        except BaseException:
            # A cancellation at the connection stage exit occurs before the
            # caller can own this engine, so construction must close it itself.
            if self._connection is not None:
                self._connection.close()
            raise
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds
        self._registered_tables: list[str] = []
        self._table_columns: dict[str, list[str]] = {}

    def register_tables(self, tables: dict[str, pd.DataFrame]) -> None:
        for name, frame in tables.items():
            safe_name = sanitize_table_name(name)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", safe_name):
                raise ValueError(f"Unsafe table name: {name}")
            with trace_stage("table_registration",table=safe_name,rows=len(frame),columns=len(frame.columns)):
                self._connection.register(safe_name, frame)
            self._table_columns[safe_name] = list(map(str, frame.columns))
            if safe_name not in self._registered_tables:
                self._registered_tables.append(safe_name)

    def run_sql(self, query: str) -> pd.DataFrame:
        return self.run_parameterized_sql(query)

    def run_parameterized_sql(
        self,
        query: str,
        parameters: list[Any] | dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """Execute one read-only statement with bound scalar values."""

        validate_bound_parameters(parameters)
        effective_query = bounded_read_query(query, self.max_rows, dialect="duckdb",
            allowed_tables=set(self._registered_tables), table_columns=self._table_columns)
        timer = Timer(self.timeout_seconds, self._connection.interrupt)
        timer.daemon = True
        try:
            timer.start()
            with trace_stage("sql_query",output_limit=self.max_rows) as span:
                cursor = self._connection.execute(effective_query, parameters) if parameters is not None else self._connection.execute(effective_query)
                columns = [column[0] for column in cursor.description]
                rows = cursor.fetchmany(self.max_rows + 1)
                if span is not None:
                    span.attributes["result_rows"]=len(rows)
            if len(rows) > self.max_rows:
                raise ValueError("查询结果超出输出上限，请增加聚合或缩小查询范围。")
            return pd.DataFrame.from_records(rows, columns=columns)
        except Exception:
            raise ValueError("只读参数化查询执行失败或超过限制，请检查字段、参数类型和已注册表。") from None
        finally:
            timer.cancel()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def list_tables(self) -> list[str]:
        return sorted(self._registered_tables)

    def list_registered_tables(self) -> list[str]:
        return self.list_tables()

    def describe_table(self, table_name: str) -> pd.DataFrame:
        if table_name not in self._registered_tables:
            raise ValueError(f"Table is not registered: {table_name}")
        return self.run_sql(f"SELECT * FROM {table_name} LIMIT 0").dtypes.reset_index(name="dtype")

    def profile_table(self, table_name: str) -> dict[str, object]:
        if table_name not in self._registered_tables:
            raise ValueError(f"Table is not registered: {table_name}")
        from insightpilot.tools.profiling import profile_dataframe

        return profile_dataframe(self.run_sql(f"SELECT * FROM {table_name}"))

    @staticmethod
    def _validate_query(query: str) -> None:
        validate_read_query(query)


def run_parameterized_sql(
    query: str,
    parameters: list[Any] | dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run a standalone read-only DuckDB query, primarily for scalar queries."""

    with AnalyticsEngine() as engine:
        return engine.run_parameterized_sql(query, parameters)


class LazyAnalyticsEngine:
    """Own a connection only when a routed node actually executes SQL."""
    def __init__(self,tables: dict[str,pd.DataFrame]):
        self._tables=tables
        self._engine: AnalyticsEngine | None=None

    def run_sql(self,query: str) -> pd.DataFrame:
        validation=validate_sql(query,set(self._tables),dialect="duckdb",
            table_columns={name:list(frame.columns) for name,frame in self._tables.items()})
        if not validation.allowed:
            raise SQLPolicyError(validation)
        actual_names={name.casefold():name for name in self._tables}
        required={actual_names[name.casefold()] for name in validation.referenced_tables}
        if self._engine is None:
            self._engine=AnalyticsEngine()
        registered=set(self._engine.list_registered_tables())
        self._engine.register_tables({name:self._tables[name] for name in required-registered})
        return self._engine.run_sql(query)

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()
            self._engine=None
        self._tables={}
