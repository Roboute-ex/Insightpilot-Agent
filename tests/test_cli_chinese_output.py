from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "examples/run_demo.py", *args], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=120, check=False)


def _output_dir() -> Path:
    path = PROJECT_ROOT / ".tmp_tests" / f"cli_zh_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_cli_text_defaults_to_chinese_and_hides_debug_details() -> None:
    result = _run("--scenario", "transaction", "--export-dir", str(_output_dir()))
    assert result.returncode == 0, result.stderr
    for label in ["场景：", "数据来源：", "分析目标：", "分析剧本：", "质量评分：", "报告路径：", "执行摘要："]:
        assert label in result.stdout
    assert "数据来源：内置模拟数据" in result.stdout
    assert "scenario=" not in result.stdout
    assert "route_taken:" not in result.stdout


def test_cli_json_uses_stable_english_schema() -> None:
    result = _run("--scenario", "multi_table", "--plan-only", "--output-format", "json", "--export-dir", str(_output_dir()))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert set(payload) == {"schema_version", "runs", "evaluations"}
    assert payload["schema_version"] == "0.6"
    assert {"scenario", "data_source_type", "workflow_backend", "query_plan_id", "join_step_count", "risk_level", "run_id"}.issubset(payload["runs"][0])
    assert all(key.isascii() for key in payload["runs"][0])
