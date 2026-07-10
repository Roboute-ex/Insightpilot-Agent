"""Local analysis tools."""

from insightpilot.tools.duckdb_engine import AnalyticsEngine
from insightpilot.tools.profiling import profile_dataframe

__all__ = ["AnalyticsEngine", "profile_dataframe"]
"""Local deterministic analysis tools."""

from insightpilot.tools.duckdb_engine import AnalyticsEngine, run_parameterized_sql

__all__ = ["AnalyticsEngine", "run_parameterized_sql"]
