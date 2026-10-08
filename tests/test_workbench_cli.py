"""Real CLI config restoration keeps finite exploration and its shared gate."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pandas as pd
import pytest

from insightpilot import cli
from insightpilot.tools.duckdb_engine import AnalyticsEngine


def configuration(tmp_path, *, method="dimension_contribution", request=None, ratio=False):
    frame = pd.DataFrame({"city": ["A", "A", "B", "B"], "channel": ["X", "Y", "X", "Y"],
                          "amount": [10., 30., 20., 60.], "success": [9, 0, 1, 0], "eligible": [90, 0, 2, 0]})
    source = tmp_path / "sample.csv"
    frame.to_csv(source, index=False)
    mapping = {"table_name": "sample", "metric_columns": ["success" if ratio else "amount"],
               "dimension_columns": ["city", "channel"], "aggregation": "ratio_of_sums" if ratio else "mean"}
    if ratio:
        mapping.update(numerator_column="success", denominator_column="eligible", unit="比例")
    config = {"config_version": "0.1.0", "question": "查看城市渠道交叉表", "goal_mode": "periodic_report",
              "playbook_id": method, "column_mapping": mapping,
              "playbook_parameters": {"exploration_request": request if request is not None else
                                      {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}}}
    target = tmp_path / "config.json"
    target.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return ["--data-source", "file", "--input-file", str(source), "--config-in", str(target),
            "--output-format", "json", "--export-dir", str(tmp_path / "exports")]


@pytest.mark.parametrize("ratio, expected", [(False, 30), (True, 10 / 92)])
def test_real_cli_restored_pivot_has_actual_excel_mean_or_weighted_ratio(tmp_path, ratio, expected):
    arguments = configuration(tmp_path, ratio=ratio)
    process = subprocess.run([sys.executable, "-m", "insightpilot.cli", *arguments, "--export-format", "excel"],
        cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        text=True, encoding="utf-8", capture_output=True, timeout=90)
    assert process.returncode == 0, process.stderr + process.stdout
    result = json.loads(process.stdout)["runs"][0]
    assert result["execution_status"] == "COMPLETED"
    assert result["playbook_id"] == "dimension_contribution"
    workbook = next(Path(path) for path in result["export_paths"] if path.endswith(".xlsx"))
    sheets = pd.read_excel(workbook, sheet_name=None)
    totals = next(frame for name, frame in sheets.items() if "exploration_totals" in name)
    assert totals.loc[totals["scope"] == "all", "metric_value"].iloc[0] == pytest.approx(expected)
    cells = next(frame for name, frame in sheets.items() if "exploration_cells" in name)
    assert len(cells) == 4


@pytest.mark.parametrize("method, exploration", [
    ("dimension_contribution", {"kind": "pivot", "row_dimension": "missing", "column_dimension": "channel"}),
    ("metric_trend", {"kind": "grouped", "row_dimension": "city"}),
    ("data_profile", {"kind": "pivot", "row_dimension": "city", "column_dimension": "channel"}),
])
def test_cli_invalid_restored_exploration_never_executes_or_exports(tmp_path, capsys, method, exploration):
    arguments = configuration(tmp_path, method=method, request=exploration)
    with patch.object(sys, "argv", ["insightpilot", *arguments, "--export-format", "pdf"]), \
         patch.object(AnalyticsEngine, "run_parameterized_sql", side_effect=AssertionError("SQL executed")) as sql, \
         patch.object(cli, "_generate_requested_exports", side_effect=AssertionError("export generated")) as export, \
         patch.object(cli, "write_text_report", side_effect=AssertionError("report generated")) as report:
        code = cli.main()
    result = json.loads(capsys.readouterr().out)["runs"][0]
    assert code == 2
    assert result["execution_status"] in {"INVALID_INPUT", "NEEDS_INPUT", "UNSUPPORTED"}
    assert result["preflight"]["blocking_issues"]
    assert sql.call_count == export.call_count == report.call_count == 0
    assert result["report_path"] is None and result["export_paths"] == []


def test_actual_exported_filtered_manifest_cannot_execute_redacted_value(tmp_path, capsys):
    request = {"kind": "grouped", "row_dimension": "city",
               "filters": [{"column": "city", "operator": "eq", "value": "A"}]}
    arguments = configuration(tmp_path, request=request)
    manifest = tmp_path / "run-manifest.json"
    with patch.object(sys, "argv", ["insightpilot", *arguments, "--config-out", str(manifest)]):
        assert cli.main() == 0
    first = json.loads(capsys.readouterr().out)["runs"][0]
    assert first["execution_status"] == "COMPLETED"
    exported = json.loads(manifest.read_text(encoding="utf-8"))
    assert exported["playbook_parameters"]["exploration_request"]["filters"][0]["value"] == "<已脱敏，需重新输入>"
    arguments[arguments.index("--config-in") + 1] = str(manifest)
    with patch.object(sys, "argv", ["insightpilot", *arguments]), \
         patch("insightpilot.agents.workflow.execute_playbook", side_effect=AssertionError("analysis executed")) as execution, \
         patch.object(AnalyticsEngine, "run_parameterized_sql", side_effect=AssertionError("SQL executed")) as sql, \
         patch.object(cli, "_generate_requested_exports", side_effect=AssertionError("export generated")) as export:
        assert cli.main() == 2
    restored = json.loads(capsys.readouterr().out)["runs"][0]
    assert restored["execution_status"] == "INVALID_INPUT"
    assert any("已脱敏" in issue["message_zh"] for issue in restored["preflight"]["blocking_issues"])
    assert sql.call_count == execution.call_count == export.call_count == 0
    assert restored["report_path"] is None
