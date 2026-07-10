from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_readme_is_multiline_markdown() -> None:
    readme = _read("README.md")
    lines = readme.splitlines()
    assert len(lines) > 50
    assert readme.count("\n## ") >= 10
    assert "```powershell" in readme
    assert "# InsightPilot Agent" in readme


def test_pyproject_is_multiline_and_parseable() -> None:
    text = _read("pyproject.toml")
    assert len(text.splitlines()) > 10
    parsed = tomllib.loads(text)
    assert parsed["project"]["version"] == "0.5.0"


def test_ci_yaml_is_multiline_and_structured() -> None:
    text = _read(".github/workflows/ci.yml")
    assert len(text.splitlines()) > 10
    for keyword in ["name:", "on:", "jobs:", "steps:"]:
        assert keyword in text


def test_requirements_have_one_dependency_per_line() -> None:
    text = _read("requirements.txt")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert " " not in stripped
        assert "," not in stripped
        assert re.match(r"^[A-Za-z0-9_.-]+([<>=!~]=?.+)?$", stripped)


def test_docs_are_not_single_line_long_text() -> None:
    for path in [
        "docs/project_plan.md",
        "docs/demo_script.md",
        "docs/data_ingestion.md",
        "docs/database_connection.md",
        "docs/metric_mapping.md",
        "docs/analysis_playbooks.md",
        "docs/report_exports.md",
        "docs/run_manifest.md",
        "docs/releases/v0.5.md",
    ]:
        text = _read(path)
        assert len(text.splitlines()) > 10
        assert "\n## " in text
