"""DuckDB-backed local query engine with basic SQL safety checks."""

from __future__ import annotations

import re
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


WRITE_TOKENS = {
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

    def __init__(self) -> None:
        if duckdb is None:
            raise ImportError("duckdb is required for AnalyticsEngine") from _DUCKDB_IMPORT_ERROR
        self._connection = duckdb.connect(database=":memory:")
        self._registered_tables: list[str] = []

    def register_tables(self, tables: dict[str, pd.DataFrame]) -> None:
        for name, frame in tables.items():
            safe_name = sanitize_table_name(name)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", safe_name):
                raise ValueError(f"Unsafe table name: {name}")
            self._connection.register(safe_name, frame)
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

        self._validate_query(query)
        try:
            if parameters is None:
                return self._connection.execute(query).fetchdf()
            return self._connection.execute(query, parameters).fetchdf()
        except Exception as exc:
            raise ValueError(
                "只读参数化查询执行失败。请检查字段、参数类型和已注册表。"
                " Registered tables: "
                f"{', '.join(self.list_tables()) or 'none'}"
            ) from exc

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
        normalized = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL).strip().lower()
        normalized = re.sub(r"--.*?$", " ", normalized, flags=re.MULTILINE)
        if not normalized:
            raise ValueError("SQL query is empty")
        if ";" in normalized.rstrip(";") or normalized.count(";") > 1:
            raise ValueError("Only a single read-only SQL statement is allowed")
        first_token = normalized.split()[0]
        if first_token not in {"select", "with"}:
            raise ValueError("Only SELECT or WITH queries are allowed")
        tokens = set(re.findall(r"\b[a-z_]+\b", normalized))
        blocked = sorted(tokens & WRITE_TOKENS)
        if blocked:
            raise ValueError(f"Unsafe SQL token detected: {', '.join(blocked)}")


def run_parameterized_sql(
    query: str,
    parameters: list[Any] | dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run a standalone read-only DuckDB query, primarily for scalar queries."""

    engine = AnalyticsEngine()
    return engine.run_parameterized_sql(query, parameters)
