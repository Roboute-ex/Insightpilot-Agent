"""The overview explains computed evidence without changing a run or its values."""
from copy import deepcopy

import pandas as pd
import pytest

from app.components.diagnostic_summary import (
    diagnostic_projection, supplementary_findings, visible_quality_risks,
)


def _result():
    comparisons = [dict(metric_id="orders", metric_name="订单量", current_value=70.0,
        baseline_value=100.0, absolute_change=-30.0, relative_change=-0.3,
        current_period="昨日", baseline_period="前 7 日均值", unit="数量",
        severity="HIGH", confidence_note="基准日期完整性 7/7")]
    contributions = [dict(metric_id="orders", dimension=dimension, dimension_value=name,
        current_value=current, baseline_value=baseline, contribution_value=change,
        confidence_flag="可用") for dimension, name, current, baseline, change in (
            ("city", "西城", 20.0, 50.0, -30.0),
            ("city", "东城", 50.0, 50.0, 0.0),
            ("channel", "渠道甲", 70.0, 100.0, -30.0))]
    contributions.append(dict(metric_id="revenue", dimension="city", dimension_value="别城",
        current_value=1.0, baseline_value=10000.0, contribution_value=-9999.0))
    evidence = [dict(evidence_id="E-1", result_table="metric_comparisons", metric="orders",
        claim="订单量较前 7 日均值下降30.0%。", method="目标期与历史基准比较",
        supporting_values={"current": 70.0, "baseline": 100.0, "relative_change": -0.3},
        caveat="基准日期完整性 7/7")]
    return dict(execution_status="COMPLETED", goal_mode="metric_diagnosis",
        run_manifest={"run_id": "selected-run"}, column_mapping={"metric_columns": ["orders"]},
        analysis_result_package={"metric_comparisons": comparisons,
            "dimension_contributions": contributions, "evidence": evidence},
        result_tables={"metric_comparisons": pd.DataFrame(comparisons),
            "dimension_contributions": pd.DataFrame(contributions), "evidence": pd.DataFrame(evidence)},
        findings=[evidence[0]["claim"], evidence[0]["claim"] + "但缺少支付口径确认。",
            "基准不足，不能作因果解释。"])


def test_diagnosis_projection_keeps_values_and_separates_metric_and_dimension():
    result = _result()
    before = deepcopy(result)
    projection = diagnostic_projection(result)
    assert projection["comparisons"] == result["analysis_result_package"]["metric_comparisons"]
    assert projection["metric_id"] == "orders"
    assert [group["dimension"] for group in projection["contribution_groups"]] == ["city", "channel"]
    assert all(row["metric_id"] == "orders" for group in projection["contribution_groups"] for row in group["rows"])
    assert projection["contribution_groups"][0]["rows"][0]["contribution_value"] == -30.0
    assert result["analysis_result_package"] == before["analysis_result_package"]
    for key in result["result_tables"]:
        pd.testing.assert_frame_equal(result["result_tables"][key], before["result_tables"][key])


def test_structured_topic_dedup_preserves_mixed_risk_and_unknown_findings():
    result = _result()
    projection = diagnostic_projection(result)
    assert supplementary_findings(result, projection["covered_evidence"]) == result["findings"][1:]
    # A table topic alone cannot hide a different baseline or changed statistics.
    result["analysis_result_package"]["evidence"][0]["supporting_values"]["baseline"] = 120
    projection = diagnostic_projection(result)
    assert supplementary_findings(result, projection["covered_evidence"]) == result["findings"]


def test_evidence_claim_with_extra_risk_is_not_treated_as_a_plain_kpi():
    result = _result()
    evidence = result["analysis_result_package"]["evidence"][0]
    evidence["claim"] += "仍缺少支付口径确认。"
    result["findings"][0] = evidence["claim"]
    projection = diagnostic_projection(result)
    assert not projection["evidence"][0]["represented"]
    assert supplementary_findings(result, projection["covered_evidence"]) == result["findings"]


@pytest.mark.parametrize("kind", ["causal", "experiment", "exploration", "static", "funnel", "retention"])
def test_other_methods_do_not_acquire_diagnostic_claims(kind):
    result = _result()
    if kind == "causal":
        result["result_tables"]["adjusted_effect_summary"] = pd.DataFrame([{"adjusted_effect": 2.0}])
    elif kind == "experiment":
        result["analysis_result_package"]["experiment_results"] = [{"absolute_lift": 2.0}]
    elif kind == "exploration":
        result["analysis_result_package"]["metadata"] = {"exploration": {"scope_row_count": 12}}
    elif kind in {"funnel", "retention"}:
        result["selected_playbook_id"] = "funnel_analysis" if kind == "funnel" else "cohort_retention"
    else:
        result["analysis_result_package"]["metric_comparisons"] = []
        result["result_tables"] = {"dimension_contribution": pd.DataFrame([{"metric_value": 12}])}
    assert diagnostic_projection(result) is None


def test_missing_tables_do_not_create_evidence_destinations_or_hide_findings():
    result = _result()
    result["result_tables"].pop("metric_comparisons")
    projection = diagnostic_projection(result)
    assert not projection["evidence"]
    assert supplementary_findings(result, projection["covered_evidence"]) == result["findings"]


def test_severe_quality_failures_are_visible_without_opening_details():
    result = _result()
    result["contract_results"] = [{"status": "FAIL", "message": "有效支付分母缺失"}]
    result["reviewer"] = {"status": "FAIL", "issues": ["统计单位未确认"]}
    risks = visible_quality_risks(result)
    assert any("有效支付分母缺失" in text for text in risks)
    assert any("统计单位未确认" in text for text in risks)


def test_quality_failure_after_256_rows_is_still_visible():
    result = _result()
    result["result_tables"]["data_quality"] = pd.DataFrame({"status": ["PASS"] * 256 + ["FAIL"]})
    assert any("数据质量存在未通过检查" in text for text in visible_quality_risks(result))


def test_custom_rate_named_metric_uses_frozen_unit_not_its_name():
    from app.components.result_panel import _format_metric_value
    result = _result()
    comparison = result["analysis_result_package"]["metric_comparisons"][0]
    comparison.update(metric_id="score_rate", unit="比例")
    result["metric_definitions"] = [{"metric_id": "score_rate", "unit": "分", "format": "percent"}]
    projection = diagnostic_projection(result)
    assert projection["metric_unit"] == "分"
    assert _format_metric_value("score_rate", 0.2, unit=projection["metric_unit"]) == "0.20"
    assert _format_metric_value("ratio", 0.2, unit="比例") == "20.0%"


def test_overview_reading_order_buttons_and_exact_difference_units():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
from tests.test_core_result_focus import _result
from app.components.result_panel import _render_overview
result = _result()
result["analysis_result_package"]["metric_comparisons"][0].update(
    metric_id="conversion_rate", current_value=0.2, baseline_value=0.25,
    absolute_change=-0.05, relative_change=-0.2, unit="比例")
_render_overview(result, "demo")
''').run()
    assert not app.exception
    headings = [item.value for item in app.subheader]
    assert [title for title in headings if title in {"发生了什么", "变化集中在哪里", "证据支持到哪一步", "下一步"}] == [
        "发生了什么", "变化集中在哪里", "证据支持到哪一步", "下一步"]
    text = "\n".join(str(item.value) for collection in (app.markdown, app.caption) for item in collection)
    assert "25.0%" in text and "-5.00 个百分点" in text and "20.0%" in text
    assert "流程检查评分" not in text
    assert len(app.button) == 2
    app.button(key="overview_show_details").click().run()
    assert app.session_state["requested_result_tab"] == "结果明细"
    assert app.session_state["result_table_selector"] == "evidence"
