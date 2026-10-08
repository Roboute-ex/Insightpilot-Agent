"""AST authorization, dialect semantics, and zero-execution rejection regressions."""
from __future__ import annotations
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import date
import pandas as pd
import pytest
from insightpilot.tools import sql_safety as policy
from insightpilot.tools.duckdb_engine import AnalyticsEngine, LazyAnalyticsEngine
from insightpilot.ingestion import db_loader

SCHEMA = {"t": ["x", "category", "日期", "销售 额"], "u": ["x", "z"]}

def check(query, dialect="duckdb", schema=SCHEMA):
    return policy.validate_sql(query, set(schema), dialect=dialect, table_columns=schema)

@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
@pytest.mark.parametrize("query", [
    "SELECT COUNT(*) AS n FROM t",
    'SELECT "日期", SUM("销售 额") AS total FROM t WHERE "日期">=? GROUP BY "日期" ORDER BY total',
    "WITH x(a) AS (SELECT x FROM t) SELECT a FROM x",
    "WITH t AS (SELECT x FROM u) SELECT x FROM t",
    "SELECT t.x,u.z FROM t JOIN u ON t.x=u.x",
    "SELECT x FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.x=t.x)",
    "SELECT x FROM t UNION ALL SELECT x FROM u ORDER BY x",
    "SELECT x AS label, COUNT(*) AS n FROM t GROUP BY label HAVING n>0",
    "SELECT 'DROP TABLE; -- /* UPDATE */' AS message",
    "SELECT 1; -- terminal comment",
    "SELECT 1; /* terminal comment */",
    "SELECT 1 -- no terminal newline",
])
def test_authorized_queries_and_bounded_form(query, dialect):
    first = check(query, dialect)
    assert first.allowed, first.to_dict()
    wrapped = policy.bounded_read_query(query, 10, dialect=dialect, allowed_tables=set(SCHEMA), table_columns=SCHEMA)
    second = check(wrapped, dialect)
    assert second.allowed, second.to_dict()
    assert second.referenced_tables == first.referenced_tables
    assert second.referenced_columns == first.referenced_columns
    assert second.policy_version == policy.SQL_POLICY_VERSION

@pytest.mark.parametrize("query,code", [
    ("SELECT x FROM t; SELECT x FROM u", "MULTIPLE_STATEMENTS"),
    ("SELECT x FROM t; DROP TABLE t; SELECT 1", "MULTIPLE_STATEMENTS"),
    ("SELECT x INTO secret FROM t", "NODE_NOT_ALLOWED"),
    ("WITH changed AS (DELETE FROM t RETURNING x) SELECT x FROM changed", "NODE_NOT_ALLOWED"),
    ("SELECT * FROM read_csv_auto('private.csv')", "TABLE_FUNCTION_NOT_ALLOWED"),
    ("SELECT * FROM read_parquet('https://example.test/private')", "TABLE_FUNCTION_NOT_ALLOWED"),
    ("SELECT * FROM 'private.csv'", "PATH_SOURCE_NOT_ALLOWED"),
    ("SELECT * FROM sqlite_master", "SYSTEM_CATALOG"),
    ("SELECT * FROM information_schema.tables", "QUALIFIED_CATALOG"),
    ("SELECT x FROM t UNION SELECT x FROM forbidden", "TABLE_NOT_ALLOWED"),
    ("SELECT x FROM forbidden UNION ALL SELECT x FROM (WITH forbidden AS (SELECT x FROM t) SELECT x FROM forbidden) q", "TABLE_NOT_ALLOWED"),
    ("WITH unused AS (SELECT x FROM forbidden) SELECT x FROM t", "TABLE_NOT_ALLOWED"),
    ("SELECT name FROM sqlite_master UNION ALL SELECT name FROM (WITH sqlite_master AS (SELECT 'x' AS name) SELECT name FROM sqlite_master) q", "SYSTEM_CATALOG"),
    ("SELECT nonexistent FROM t", "COLUMN_NOT_ALLOWED"),
    ("SELECT t.nonexistent FROM t", "COLUMN_NOT_ALLOWED"),
    ("SELECT other.x FROM t", "COLUMN_NOT_ALLOWED"),
    ("SELECT t.* FROM u", "UNKNOWN_SOURCE_ALIAS"),
    ("SELECT COUNT(other.*) FROM t", "UNKNOWN_SOURCE_ALIAS"),
    ("SELECT x FROM t JOIN u ON t.x=u.x", "AMBIGUOUS_COLUMN"),
    ("SELECT x FROM t UNION SELECT x FROM u ORDER BY missing", "COLUMN_NOT_ALLOWED"),
    ("SELECT secret FROM (SELECT x FROM t) q", "COLUMN_NOT_ALLOWED"),
    ("SELECT x FROM t USING SAMPLE 10 ROWS", "NODE_NOT_ALLOWED"),
    ("SELECT getenv('SECRET')", "FUNCTION_NOT_ALLOWED"),
    ("SELECT load_extension('private')", "FUNCTION_NOT_ALLOWED"),
    ("WITH RECURSIVE x AS (SELECT 1 UNION SELECT * FROM x) SELECT * FROM x", "RECURSIVE_CTE"),
    ("SELECT * FROM t NATURAL JOIN u", "UNSUPPORTED_JOIN"),
    ("SELECT * FROM t JOIN u USING(x)", "UNSUPPORTED_JOIN"),
    ("SELECT * EXCLUDE(x) FROM t", "UNSUPPORTED_STAR"),
])
def test_reject_specific_unsafe_or_unsupported_shapes(query, code):
    result = check(query)
    assert not result.allowed
    assert result.rejection_code == code, result.to_dict()
    assert "private" not in result.reason and "SECRET" not in result.reason

@pytest.mark.parametrize("statement", ["ATTACH 'x' AS y", "DETACH y", "COPY t TO 'x'", "INSTALL httpfs", "LOAD httpfs", "PRAGMA table_info(t)", "SET x=1", "CREATE TABLE x(y INT)", "UPDATE t SET x=1"])
def test_nonquery_statements_fail_before_parsing(statement):
    assert check(statement).rejection_code == "STATEMENT_NOT_READ_ONLY"

def test_references_are_physical_not_cte_names():
    result = check("WITH v AS (SELECT t.x FROM t) SELECT v.x FROM v")
    assert result.allowed
    assert result.referenced_tables == ("t",)
    assert result.referenced_columns == ("t.x",)
    assert result.statement_kind == "select"
    assert "_tree" not in result.to_dict()

def test_caps_and_missing_parser_are_fail_closed(monkeypatch):
    assert check("SELECT '" + "x" * policy.MAX_SQL_LENGTH + "'").rejection_code == "SQL_TOO_LARGE"
    monkeypatch.setattr(policy, "MAX_AST_NODES", 5)
    assert check("SELECT x, category FROM t WHERE x>1").rejection_code == "AST_TOO_LARGE"
    monkeypatch.setattr(policy, "parse", None)
    assert check("SELECT 1").rejection_code == "DEPENDENCY_UNAVAILABLE"

def test_import_without_sqlglot_remains_friendly():
    script = '''import sys
sys.modules["sqlglot"] = None
import insightpilot.ingestion.db_loader
import insightpilot.tools.duckdb_engine
from insightpilot.tools.sql_safety import validate_sql
result=validate_sql("SELECT 1")
assert not result.allowed and result.rejection_code=="DEPENDENCY_UNAVAILABLE"
'''
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr

def test_duckdb_rejection_executes_zero_user_sql():
    class Spy:
        calls = 0
        def __init__(self, connection): self.connection = connection
        def execute(self, *args, **kwargs):
            self.calls += 1
            return self.connection.execute(*args, **kwargs)
        def __getattr__(self, name): return getattr(self.connection, name)
    with AnalyticsEngine() as engine:
        engine.register_tables({"t": pd.DataFrame({"x": [1]})})
        spy = Spy(engine._connection)
        engine._connection = spy
        for sql in ["SELECT x FROM t UNION SELECT x FROM forbidden", "SELECT missing FROM t", "SELECT * FROM read_csv_auto('not-read.csv')"]:
            with pytest.raises(policy.SQLPolicyError): engine.run_sql(sql)
        assert spy.calls == 0

def test_lazy_engine_rejected_query_never_opens_connection(monkeypatch):
    import insightpilot.tools.duckdb_engine as module
    def forbidden(*args, **kwargs): raise AssertionError("connection opened")
    monkeypatch.setattr(module, "AnalyticsEngine", forbidden)
    engine = LazyAnalyticsEngine({"t": pd.DataFrame({"x": [1]})})
    with pytest.raises(policy.SQLPolicyError): engine.run_sql("SELECT * FROM forbidden")

def test_limit_wrap_failure_has_no_unbounded_fallback(monkeypatch):
    original = policy.validate_read_query
    def refuse_wrapper(sql, *args, **kwargs):
        if "__insightpilot_bounded" in sql:
            raise policy.SQLPolicyError(policy.SQLValidationResult(False,"duckdb", rejection_code="WRAPPER_FAILED", reason="测试限流失败"))
        return original(sql, *args, **kwargs)
    with AnalyticsEngine() as engine:
        engine.register_tables({"t": pd.DataFrame({"x": [1]})})
        monkeypatch.setattr(policy, "validate_read_query", refuse_wrapper)
        with pytest.raises(policy.SQLPolicyError, match="WRAPPER_FAILED"):
            engine.run_sql("SELECT x FROM t")

@pytest.fixture
def sqlite_db(tmp_path):
    path = tmp_path / "local.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript('CREATE TABLE t(x INTEGER, "日期" TEXT, "销售 额" REAL); INSERT INTO t VALUES(1,"2026-09-01",10.0),(2,"2026-09-02",20.0);')
    connection.close()
    return path

def test_sqlite_bound_dates_chinese_columns_and_tail_comment(sqlite_db):
    result = db_loader.run_database_query(f"sqlite:///{sqlite_db}", 'SELECT "日期", SUM("销售 额") AS total FROM t WHERE "日期">=? GROUP BY "日期"; -- tail', parameters=["2026-09-02"])
    assert result.dataframe.to_dict("records") == [{"日期":"2026-09-02", "total":20.0}]
    assert "2026-09-02" not in result.query

def test_sqlite_native_semantics_are_preserved(sqlite_db):
    result = db_loader.run_database_query(f"sqlite:///{sqlite_db}", "SELECT 5 / 2 AS quotient, NULLIF(1,1) AS missing, date(?) AS day, strftime('%Y', ?) AS year", parameters=["2026-09-02", "2026-09-02"])
    row = result.dataframe.iloc[0]
    assert row.quotient == 2 and row.missing is None
    assert row.day == "2026-09-02" and row.year == "2026"

def test_duckdb_native_semantics_are_preserved():
    with AnalyticsEngine() as engine:
        row = engine.run_parameterized_sql("SELECT 5 / 2 AS quotient, NULLIF(1,1) AS missing, CAST(? AS DATE) AS day", ["2026-09-02"]).iloc[0]
        assert row.quotient == 2.5 and row.missing is None and row.day == date(2026,9,2)

def test_sqlite_bad_column_never_reaches_user_execute(sqlite_db, monkeypatch):
    calls = []
    connect = sqlite3.connect
    class RecordingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            calls.append(sql)
            return super().execute(sql, *args, **kwargs)
    monkeypatch.setattr(db_loader.sqlite3, "connect", lambda *args, **kwargs: connect(*args, factory=RecordingConnection, **kwargs))
    with pytest.raises(policy.SQLPolicyError):
        db_loader.run_database_query(f"sqlite:///{sqlite_db}", "SELECT secret FROM t")
    assert all("secret" not in sql and "__insightpilot_bounded" not in sql for sql in calls)

def test_sqlite_view_cannot_hide_catalog_access(sqlite_db):
    with sqlite3.connect(sqlite_db) as connection:
        connection.execute("CREATE VIEW hidden AS SELECT name FROM sqlite_master")
    with pytest.raises(ValueError, match="只读数据库查询失败"):
        db_loader.run_database_query(f"sqlite:///{sqlite_db}", "SELECT * FROM hidden")

def test_bad_sql_no_connection_no_new_database(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("connection attempted")
    monkeypatch.setattr(db_loader.sqlite3, "connect", forbidden)
    path = tmp_path / "never-created.sqlite"
    with pytest.raises(policy.SQLPolicyError): db_loader.run_database_query(f"sqlite:///{path}", "SELECT 1; DELETE FROM t")
    assert not path.exists()
    with pytest.raises(policy.SQLPolicyError, match="UNSUPPORTED_DIALECT"):
        db_loader.run_database_query("postgresql://localhost/demo", "SELECT 1")

@pytest.mark.parametrize("parameters", ["user SQL", [object()], {1: "x"}, [[1,2]]])
def test_only_bound_scalars(parameters):
    with pytest.raises(ValueError): policy.validate_bound_parameters(parameters)

@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
@pytest.mark.parametrize("operation", ["UNION ALL", "INTERSECT", "EXCEPT"])
def test_set_operation_output_aliases_and_all_branch_authorization(dialect, operation):
    query = f"SELECT x AS result FROM t {operation} SELECT x AS other FROM u ORDER BY result"
    accepted = check(query, dialect)
    assert accepted.allowed, accepted.to_dict()
    assert accepted.referenced_tables == ("t", "u")
    assert accepted.referenced_columns == ("t.x", "u.x")
    bounded = policy.bounded_read_query(query, 10, dialect=dialect, allowed_tables=set(SCHEMA), table_columns=SCHEMA)
    assert check(bounded, dialect).allowed
    assert check(query.replace("ORDER BY result", "ORDER BY other"), dialect).rejection_code == "COLUMN_NOT_ALLOWED"
    for unauthorized in (
        query.replace("FROM t", "FROM forbidden"),
        query.replace("FROM u", "FROM forbidden"),
        query.replace("SELECT x AS other", "SELECT missing AS other"),
    ):
        rejected = check(unauthorized, dialect)
        assert not rejected.allowed
        assert rejected.rejection_code in {"TABLE_NOT_ALLOWED", "COLUMN_NOT_ALLOWED"}, rejected.to_dict()


@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
def test_nested_set_operations_keep_output_scope_and_reject_hidden_unauthorized_branch(dialect):
    query = "WITH combined AS (SELECT x AS result FROM t UNION ALL SELECT x FROM u) SELECT result FROM combined EXCEPT SELECT x FROM t ORDER BY result"
    assert check(query, dialect).allowed
    rejected = check(query.replace("SELECT x FROM u", "SELECT x FROM forbidden"), dialect)
    assert rejected.rejection_code == "TABLE_NOT_ALLOWED"
    assert check(query.replace("ORDER BY result", "ORDER BY missing"), dialect).rejection_code == "COLUMN_NOT_ALLOWED"


def test_unknown_set_operation_scope_interface_fails_closed(monkeypatch):
    traverse = policy.traverse_scope
    def missing_branches(tree):
        scopes = traverse(tree)
        for scope in scopes:
            if isinstance(scope.expression, (policy.exp.Union, policy.exp.Intersect, policy.exp.Except)):
                for name in ("union_scopes", "set_operation_scopes"):
                    if hasattr(scope, name):
                        delattr(scope, name)
        return scopes
    monkeypatch.setattr(policy, "traverse_scope", missing_branches)
    rejected = check("SELECT x FROM t UNION ALL SELECT x FROM u ORDER BY x")
    assert not rejected.allowed
    assert rejected.rejection_code == "UNRESOLVED_SET_BRANCH"
