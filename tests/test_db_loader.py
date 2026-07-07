from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from insightpilot.ingestion.db_loader import (
    is_safe_select_query,
    mask_database_url,
    normalize_database_url,
    run_database_query,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _workspace_tmp_dir() -> Path:
    path = PROJECT_ROOT / ".tmp_tests" / str(uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_safe_select_query_rules() -> None:
    assert is_safe_select_query("SELECT * FROM demo")
    assert is_safe_select_query("WITH source AS (SELECT 1 AS value) SELECT * FROM source")
    assert not is_safe_select_query("DROP TABLE demo")
    assert not is_safe_select_query("DELETE FROM demo")
    assert not is_safe_select_query("INSERT INTO demo VALUES (1)")
    assert not is_safe_select_query("UPDATE demo SET value = 1")
    assert not is_safe_select_query("SELECT * FROM demo; SELECT * FROM other")


def test_mask_database_url_hides_password() -> None:
    masked = mask_database_url("postgresql://user:secret@localhost:5432/db")
    assert "secret" not in masked
    assert masked == "postgresql://user:***@localhost:5432/db"
    assert mask_database_url("sqlite:///local.db") == "sqlite:///local.db"


def test_normalize_database_url_rejects_empty() -> None:
    try:
        normalize_database_url(" ")
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("empty database URL should fail")


def test_run_database_query_sqlite_file() -> None:
    db_path = _workspace_tmp_dir() / "demo.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE metrics (date TEXT, value INTEGER)")
        connection.executemany("INSERT INTO metrics VALUES (?, ?)", [("2026-01-01", 1), ("2026-01-02", 2)])
        connection.commit()
    finally:
        connection.close()

    result = run_database_query(f"sqlite:///{db_path}", "SELECT * FROM metrics", table_name="metrics_result")
    assert result.table_name == "metrics_result"
    assert result.row_count == 2
    assert result.columns == ["date", "value"]
