from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cli_lists_playbooks() -> None:
    result = subprocess.run([sys.executable, "examples/run_demo.py", "--list-playbooks"], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=60, check=False)
    assert result.returncode == 0
    assert "metric_trend" in result.stdout
    assert "periodic_summary" in result.stdout


def test_cli_runs_playbook_and_reports_run_id() -> None:
    result = subprocess.run([sys.executable, "examples/run_demo.py", "--scenario", "transaction", "--playbook", "data_profile", "--verbose"], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    assert "playbook=data_profile" in result.stdout
    assert "run_id=" in result.stdout


def test_cli_config_can_be_exported_and_loaded() -> None:
    temp_dir = PROJECT_ROOT / ".tmp_tests" / f"cli_config_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    config_path = temp_dir / "run-config.json"
    first = subprocess.run([sys.executable, "examples/run_demo.py", "--scenario", "transaction", "--playbook", "data_profile", "--config-out", str(config_path), "--export-dir", str(temp_dir)], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=120, check=False)
    assert first.returncode == 0, first.stderr
    assert config_path.exists()
    second = subprocess.run([sys.executable, "examples/run_demo.py", "--scenario", "transaction", "--config-in", str(config_path), "--export-dir", str(temp_dir), "--verbose"], cwd=PROJECT_ROOT, text=True, capture_output=True, timeout=120, check=False)
    assert second.returncode == 0, second.stderr
    assert "playbook=data_profile" in second.stdout
