from __future__ import annotations

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
    assert "scenario=transaction" in result.stdout
    assert "workflow_backend=rule_based" in result.stdout
    assert "reviewer_status=PASS" in result.stdout
    assert "reviewer_score=" in result.stdout
    assert "report:" in result.stdout


def test_cli_content_experiment_analysis() -> None:
    result = _run_cli("--scenario", "content", "--goal-mode", "experiment_analysis")
    assert result.returncode == 0, result.stderr
    assert "scenario=content" in result.stdout
    assert "intent=experiment_analysis" in result.stdout
    assert "reviewer_status=PASS" in result.stdout


def test_cli_live_quality() -> None:
    result = _run_cli("--scenario", "live", "--goal-mode", "live_quality")
    assert result.returncode == 0, result.stderr
    assert "scenario=live" in result.stdout
    assert "intent=live_quality_analysis" in result.stdout
    assert "reviewer_status=PASS" in result.stdout


def test_cli_use_langgraph_does_not_require_langgraph() -> None:
    result = _run_cli("--scenario", "transaction", "--goal-mode", "metric_diagnosis", "--use-langgraph")
    assert result.returncode == 0, result.stderr
    assert "scenario=transaction" in result.stdout
    assert "workflow_backend=" in result.stdout
    assert "reviewer_status=" in result.stdout
