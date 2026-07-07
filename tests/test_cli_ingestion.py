from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _workspace_tmp_dir() -> Path:
    path = PROJECT_ROOT / ".tmp_tests" / str(uuid4())
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "examples/run_demo.py", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_cli_csv_ingestion() -> None:
    csv_path = _workspace_tmp_dir() / "sample.csv"
    csv_path.write_text("date,value,city\n2026-01-01,1,A\n2026-01-02,2,B\n", encoding="utf-8")
    result = _run_cli(
        "--data-source",
        "file",
        "--input-file",
        str(csv_path),
        "--table-name",
        "uploaded_table",
        "--goal-mode",
        "growth_trend",
    )
    assert result.returncode == 0, result.stderr
    assert "scenario=file" in result.stdout
    assert "data_source=uploaded_files" in result.stdout


def test_cli_excel_ingestion() -> None:
    excel_path = _workspace_tmp_dir() / "sample.xlsx"
    pd.DataFrame({"date": ["2026-01-01", "2026-01-02"], "value": [1, 2]}).to_excel(
        excel_path,
        sheet_name="Sheet1",
        index=False,
    )
    result = _run_cli(
        "--data-source",
        "file",
        "--input-file",
        str(excel_path),
        "--sheet-name",
        "Sheet1",
        "--table-name",
        "uploaded_table",
        "--goal-mode",
        "growth_trend",
    )
    assert result.returncode == 0, result.stderr
    assert "scenario=file" in result.stdout


def test_cli_sqlite_ingestion() -> None:
    db_path = _workspace_tmp_dir() / "sample.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE metrics (date TEXT, value INTEGER)")
        connection.executemany("INSERT INTO metrics VALUES (?, ?)", [("2026-01-01", 1), ("2026-01-02", 2)])
        connection.commit()
    finally:
        connection.close()
    result = _run_cli(
        "--data-source",
        "database",
        "--database-url",
        f"sqlite:///{db_path}",
        "--query",
        "SELECT * FROM metrics",
        "--table-name",
        "db_table",
        "--goal-mode",
        "growth_trend",
    )
    assert result.returncode == 0, result.stderr
    assert "scenario=database" in result.stdout
    assert "data_source=database" in result.stdout


def test_cli_unsafe_sql_is_rejected_without_password_leak() -> None:
    result = _run_cli(
        "--data-source",
        "database",
        "--database-url",
        "postgresql://user:secret@localhost/db",
        "--query",
        "DROP TABLE metrics",
    )
    assert result.returncode != 0
    assert "secret" not in result.stdout
    assert "secret" not in result.stderr
