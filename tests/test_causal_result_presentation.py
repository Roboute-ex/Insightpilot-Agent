"""Causal presentation reads independently checked estimates, never invents them."""
from copy import deepcopy
from io import BytesIO
from unittest.mock import patch

import pandas as pd
import pytest
from pypdf import PdfReader

from insightpilot.agents.dataset import PreparedDataset
from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.analysis.package_builder import _causal_result_summary
from insightpilot.analysis.results import AnalysisResultPackage
from insightpilot.planning.planner import UNRESOLVED_METRIC_STEP, create_analysis_plan
from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.reports.pdf import generate_pdf_report


def _run(*, controls=True, legacy=False):
    # Independent oracle: identical x=1..12 in both arms, y=10+3*x+2*t.
    # Means are 29.5 and 31.5; the full-rank regression coefficient on t is 2.
    frame = pd.DataFrame({
        "group": ["control"] * 12 + ["treatment"] * 12,
        "baseline": list(range(1, 13)) * 2,
        "outcome": [10 + 3 * x + 2 * t for t in (0, 1) for x in range(1, 13)],
    })
    dataset = PreparedDataset.from_tables({"sample": frame})
    return run_agent_analysis(
        "控制基线后，两组结果的关联差异是多少？", {},
        goal_mode="causal_exploration", playbook_id=None if legacy else "causal_exploration",
        prepared_dataset=dataset, data_source_type="csv", presentation_mode="deferred",
        column_mapping={"table_name": "sample", "treatment_column": "group",
                        "outcome_column": "outcome", "metric_columns": ["outcome"],
                        "dimension_columns": ["baseline"] if controls else [], "aggregation": "mean"},
        playbook_parameters={"control_value": "control", "treatment_value": "treatment",
                             "covariates": ["baseline"] if controls else []},
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_causal_summary_contains_actual_estimates_and_limits(legacy):
    result = _run(legacy=legacy)
    assert result["execution_status"] == "COMPLETED"
    row = result["result_tables"]["adjusted_effect_summary"].iloc[0]
    assert row["naive_difference"] == pytest.approx(2)
    assert row["adjusted_effect"] == pytest.approx(2)
    assert row["sample_size"] == 24
    summary = result["analysis_result_package"]["executive_summary"]
    assert "两组原始均值差（处理组−对照组）=2.0000" in summary
    assert "回归调整估计=2.0000" in summary
    assert "有效样本量 n=24" in summary
    assert "不是因果证明" in summary and "前提尚未验证" in summary
    assert result["summary"] == summary
    assert UNRESOLVED_METRIC_STEP not in result["plan"]["analysis_steps"]
    assert "仅能提供数据概览" not in str(result["plan"])
    assert "倾向评分加权默认关闭" in str(result["plan"])
    assert not result["report_markdown"]  # Display does not pre-generate reports.


def test_causal_without_covariates_does_not_invent_adjusted_value():
    result = _run(controls=False)
    row = result["result_tables"]["adjusted_effect_summary"].iloc[0]
    assert row["naive_difference"] == 2
    assert pd.isna(row["adjusted_effect"])
    assert "未生成回归调整估计" in result["summary"]
    assert "回归调整估计=0" not in result["summary"]
    assert "未经调整的差异" in result["summary"]


def test_causal_reports_contain_same_estimates_and_no_stale_fallback():
    result = _run()
    original = result["result_tables"]["adjusted_effect_summary"].copy(deep=True)
    manifest = RunManifest.from_dict(result["run_manifest"])
    with patch("insightpilot.playbooks.executor.estimate_adjusted_effect", side_effect=AssertionError("no refit")):
        markdown = generate_markdown_report(result)
        pdf = generate_pdf_report(result, manifest)
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for text in (markdown, pdf_text):
        assert "回归调整估计=2.0000" in text
        assert "n=24" in text
        assert "不是因果证明" in text
        assert "仅能提供数据概览" not in text
        assert UNRESOLVED_METRIC_STEP not in text
    pd.testing.assert_frame_equal(original, result["result_tables"]["adjusted_effect_summary"])


def test_no_causal_estimates_preserve_existing_summary_instead_of_zero():
    for frame in (pd.DataFrame(), pd.DataFrame([{"naive_difference": float("nan"), "adjusted_effect": None}])):
        package = AnalysisResultPackage("fixture", "causal", "探索", "没有已计算结果", result_tables={"adjusted_effect_summary": frame})
        assert _causal_result_summary(package) == "没有已计算结果"


def test_unresolved_request_remains_blocked_and_other_playbook_summary_unchanged():
    assert UNRESOLVED_METRIC_STEP in create_analysis_plan("探索两组结果关联", "causal_exploration").analysis_steps
    data = PreparedDataset.from_tables({"sample": pd.DataFrame({"label": ["a", "b"] * 6})})
    with patch("insightpilot.agents.workflow.execute_playbook", side_effect=AssertionError("must not execute")) as execution:
        result = run_agent_analysis("探索两组结果关联", {}, goal_mode="causal_exploration", playbook_id="causal_exploration", prepared_dataset=data, data_source_type="csv")
    assert result["execution_status"] == "NEEDS_INPUT"
    assert execution.call_count == 0
    assert not result["result_tables"]
    profile = run_agent_analysis("检查数据质量", {}, playbook_id="data_profile", prepared_dataset=data, data_source_type="csv", presentation_mode="deferred")
    assert profile["execution_status"] == "COMPLETED"
    assert profile["summary"].startswith("数据概览与质量检查执行完成，状态为")
    assert "回归调整估计" not in profile["summary"]


@pytest.mark.parametrize("source", ["user_selected", "automatic_suggestion"])
@pytest.mark.parametrize("cleared_value", [None, ""])
def test_explicit_empty_builtin_outcome_cannot_be_refilled_or_executed(cleared_value, source):
    from contextlib import ExitStack
    from insightpilot.data.scenarios import generate_scenario
    from insightpilot.planning.planner import prepare_analysis_request
    from insightpilot.playbooks.executor import execute_playbook

    tables = generate_scenario("transaction", scale="small", seed=42).tables
    dataset = PreparedDataset.from_tables(tables)
    mapping = {"table_name": "daily_metrics", "metric_columns": ["orders"],
               "outcome_column": cleared_value, "source": source}
    request = {"question": "昨日订单量为什么下降？", "goal_mode": "metric_diagnosis",
               "playbook_id": "causal_exploration", "selection_source": "user_selected",
               "column_mapping": mapping,
               "playbook_parameters": {"control_value": "control", "treatment_value": "treatment"}}
    prepared = prepare_analysis_request(**request, table_metadata=dataset.metadata, dataset_revision=dataset.revision)
    codes = {item["code"] for item in prepared["preflight"]["blocking_issues"]}
    if source == "automatic_suggestion":
        assert prepared["normalized_request"]["column_mapping"]["source"] == "automatic_suggestion"
        assert all(card["definition_status"] != "user_confirmed" for card in prepared["metric_definitions"])
    assert {"MISSING_OUTCOME_COLUMN", "MISSING_TREATMENT_COLUMN"} <= codes
    assert not prepared["preflight"]["can_submit"]
    targets = ["insightpilot.agents.workflow.execute_playbook",
               "insightpilot.tools.duckdb_engine.AnalyticsEngine.run_sql",
               "insightpilot.tools.duckdb_engine.AnalyticsEngine.run_parameterized_sql",
               "insightpilot.playbooks.executor.estimate_adjusted_effect",
               "insightpilot.agents.workflow.generate_markdown_report"]
    with ExitStack() as stack:
        calls = [stack.enter_context(patch(target, side_effect=AssertionError("must not execute"))) for target in targets]
        result = run_agent_analysis(**request, tables={}, prepared_dataset=dataset, data_source_type="synthetic")
        # Direct executor validation independently rejects the same missing role.
        direct = execute_playbook("causal_exploration", tables, mapping, request["playbook_parameters"])
    assert result["execution_status"] == "NEEDS_INPUT"
    assert all(call.call_count == 0 for call in calls)
    assert result["trace"]["executed_queries"] == []
    assert "MISSING_OUTCOME_COLUMN" in {item["code"] for item in result["preflight"]["blocking_issues"]}
    assert direct.status == "FAIL"
    assert any("outcome_column" in warning for warning in direct.warnings)
    assert not direct.result_tables and not direct.executed_queries


def test_builtin_causal_without_mapping_retains_valid_default_outcome():
    from insightpilot.data.scenarios import generate_scenario
    from insightpilot.planning.planner import prepare_analysis_request

    data = PreparedDataset.from_tables(generate_scenario("content", scale="small", seed=42).tables)
    request = {"question": "请做轻量因果探索", "goal_mode": "causal_exploration",
               "playbook_id": "causal_exploration", "selection_source": "user_selected"}
    prepared = prepare_analysis_request(**request, table_metadata=data.metadata, dataset_revision=data.revision)
    assert prepared["preflight"]["can_submit"], prepared["preflight"]
    assert prepared["normalized_request"]["column_mapping"] is None
    result = run_agent_analysis(**request, tables={}, prepared_dataset=data, presentation_mode="deferred")
    assert result["execution_status"] == "COMPLETED"
    assert result["column_mapping"]["outcome_column"] == "completion_rate"
    assert not result["result_tables"]["adjusted_effect_summary"].empty


@pytest.mark.parametrize("controls", [True, False])
def test_causal_estimate_chart_uses_parallel_computed_estimates_not_stacked_sum(controls):
    from insightpilot.visualization.factory import build_chart
    result = _run(controls=controls)
    spec = next(spec for spec in result["chart_specs"] if spec["chart_id"] == "adjusted_effect")
    assert spec["chart_type"] == "grouped_bar"
    assert "propensity_weighted_effect" not in spec["y"]
    assert spec["y"] == (["naive_difference", "adjusted_effect"] if controls else ["naive_difference"])
    figure = build_chart(spec, result["result_tables"])
    assert figure.layout.barmode == "group"
    assert len(figure.data) == (2 if controls else 1)
    assert [float(trace.y[0]) for trace in figure.data] == pytest.approx([2] * len(figure.data))
    assert "不可相加" in spec["description"]
