"""Exercise the distribution CLI without creating environments or using a network."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

import scripts.check_distribution as distribution


def run_distribution(tmp_path, monkeypatch, mode_args, *, fail_lock=False, offline=False):
    project = tmp_path / "project"
    project.mkdir()
    lock = project / "requirements-lock.txt"
    lock.write_text("numpy==2.5.3\n", encoding="utf-8")
    wheel = project / "synthetic-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("insightpilot/__init__.py", "__version__ = '0.1.0'\n")
    work_dir = tmp_path / "validation"
    argv = ["check_distribution.py", "--wheel", str(wheel), "--work-dir", str(work_dir), *mode_args]
    wheelhouse = tmp_path / "wheelhouse"
    if offline:
        wheelhouse.mkdir()
        argv.extend(["--wheelhouse", str(wheelhouse)])
    environments = []
    commands = []

    class FakeEnvBuilder:
        def __init__(self, *, with_pip):
            assert with_pip is True

        def create(self, destination):
            environments.append(destination)

    def fake_run(command, **kwargs):
        commands.append(command)
        assert kwargs["cwd"] == work_dir
        assert "PYTHONPATH" not in kwargs["env"]
        assert "PYTHONHOME" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 1 if fail_lock and "-r" in command else 0, "", "")

    monkeypatch.setattr(distribution, "ROOT", project)
    monkeypatch.setattr(distribution, "required_package_files", lambda: ["insightpilot/__init__.py"])
    monkeypatch.setattr(distribution.venv, "EnvBuilder", FakeEnvBuilder)
    monkeypatch.setattr(distribution.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")
    monkeypatch.setenv("PYTHONHOME", "must-not-leak")
    exit_code = distribution.main()
    result = json.loads((work_dir / "validation.json").read_text(encoding="utf-8"))
    assert environments == [work_dir / "venv"]
    assert not (work_dir / "venv").exists()
    return exit_code, result, commands, lock, wheelhouse


@pytest.mark.parametrize("mode_args", [[], ["--dependency-mode", "locked"]])
def test_locked_mode_preserves_local_dependency_restore(tmp_path, monkeypatch, mode_args):
    code, result, commands, lock, _ = run_distribution(tmp_path, monkeypatch, mode_args)
    assert code == 0
    assert result["dependency_mode"] == "locked"
    assert [record["name"] for record in result["checks"]] == [
        "install_locked", "install_wheel", "outside_import", "dependencies", "semantic", "upstream_task_contracts"]
    assert commands[0][3:] == ["-m", "pip", "install", "-r", str(lock)]


def test_project_mode_uses_wheel_metadata_and_preserves_all_checks(tmp_path, monkeypatch):
    code, result, commands, _, wheelhouse = run_distribution(
        tmp_path, monkeypatch, ["--dependency-mode", "project"], offline=True)
    assert code == 0
    assert result["dependency_mode"] == "project"
    assert [record["name"] for record in result["checks"]] == [
        "install_wheel", "outside_import", "dependencies", "semantic", "upstream_task_contracts"]
    assert not any("-r" in command for command in commands)
    assert commands[0][3:6] == ["-m", "pip", "install"]
    assert commands[0][-3:] == ["--no-index", "--find-links", str(wheelhouse.resolve())]
    assert commands[-1][3:] == ["-I", "-m", "insightpilot.evaluation.cli", "--suite", "task", "--output-format", "json"]


def test_failed_lock_install_is_reported_without_silent_fallback(tmp_path, monkeypatch):
    code, result, commands, _, _ = run_distribution(tmp_path, monkeypatch, [], fail_lock=True)
    assert code == 1
    assert result["dependency_mode"] == "locked"
    assert [record["name"] for record in result["checks"]] == ["install_locked"]
    assert result["checks"][0]["exit_code"] == 1
    assert len(commands) == 1
