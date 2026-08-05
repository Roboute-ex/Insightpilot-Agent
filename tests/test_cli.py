from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "examples/run_demo.py", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )


def test_cli_transaction_metric_diagnosis() -> None:
    result = _run_cli("--scenario", "transaction", "--goal-mode", "metric_diagnosis")
    assert result.returncode == 0, result.stderr
    assert "场景：交易转化异常" in result.stdout
    assert "质量评分：" in result.stdout
    assert "报告路径：" in result.stdout
    assert "scenario=" not in result.stdout
    assert "route_taken:" not in result.stdout


def test_cli_content_experiment_analysis() -> None:
    result = _run_cli("--scenario", "content", "--goal-mode", "experiment_analysis")
    assert result.returncode == 0, result.stderr
    for value in ("实验分析结果：", "实验组：", "对照组：", "样本量", "lift：", "p-value：", "95% 置信区间：", "显著性结论："):
        assert value in result.stdout
    assert "completion_rate" not in result.stdout
    assert "p_value" not in result.stdout


def test_cli_live_quality() -> None:
    result = _run_cli("--scenario", "live", "--goal-mode", "live_quality")
    assert result.returncode == 0, result.stderr
    assert "场景：体验质量" in result.stdout
    assert "分析目标：体验质量分析" in result.stdout
    assert "scenario=" not in result.stdout


def test_cli_use_langgraph_does_not_require_langgraph() -> None:
    result = _run_cli("--scenario", "transaction", "--goal-mode", "metric_diagnosis", "--use-langgraph", "--verbose")
    assert result.returncode == 0, result.stderr
    assert "scenario=transaction" in result.stdout
    assert "workflow_backend=" in result.stdout
    assert "reviewer_status=" in result.stdout


def test_cli_verbose_restores_debug_details() -> None:
    result = _run_cli("--scenario", "transaction", "--verbose")
    assert result.returncode == 0, result.stderr
    assert "scenario=transaction" in result.stdout
    assert "route_taken:" in result.stdout


def test_cli_json_contains_experiment_statistics() -> None:
    result = _run_cli("--scenario", "content", "--goal-mode", "experiment_analysis", "--output-format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    experiment = payload["runs"][0]["experiment_results"][0]
    assert REQUIRED_EXPERIMENT_JSON_FIELDS.issubset(experiment)


def test_cli_help_lists_all_export_formats() -> None:
    result = _run_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "pdf,markdown,html,excel,manifest,bundle" in result.stdout


REQUIRED_EXPERIMENT_JSON_FIELDS = {
    "control_value",
    "treatment_value",
    "control_sample_size",
    "treatment_sample_size",
    "relative_lift",
    "p_value",
    "confidence_interval_lower",
    "confidence_interval_upper",
    "significance_conclusion",
}
