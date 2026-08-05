from __future__ import annotations

from insightpilot.analysis.package_builder import deduplicate_findings
from insightpilot.reports import pdf as pdf_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest


REQUIRED_EXPERIMENT_FIELDS = {
    "control_group",
    "treatment_group",
    "control_value",
    "treatment_value",
    "control_sample_size",
    "treatment_sample_size",
    "total_sample_size",
    "absolute_lift",
    "relative_lift",
    "p_value",
    "confidence_interval_lower",
    "confidence_interval_upper",
    "is_significant",
    "significance_conclusion",
}


def test_experiment_package_contains_complete_statistics(experiment_result) -> None:
    package = experiment_result["analysis_result_package"]
    assert package["scenario"] == "experiment"
    assert len(package["experiment_results"]) == 1
    assert REQUIRED_EXPERIMENT_FIELDS.issubset(package["experiment_results"][0])
    assert 0 < package["experiment_results"][0]["p_value"] < 0.05
    assert not experiment_result["result_tables"]["experiment_comparison"].empty
    assert "run_experiment" in experiment_result["route_taken"]
    assert "实验组" in package["executive_summary"]
    assert "对照组" in package["executive_summary"]
    assert "p-value" in package["executive_summary"]
    assert package["executive_summary"] not in experiment_result["findings"]
    assert not any("completion_rate=" in finding for finding in experiment_result["findings"])


def test_experiment_markdown_and_html_show_complete_statistics(experiment_result) -> None:
    manifest = RunManifest.from_dict(experiment_result["run_manifest"])
    markdown = experiment_result["report_markdown"]
    html = generate_html_report(experiment_result, [], manifest)
    for output in (markdown, html):
        for marker in ("实验分析结果", "实验组", "对照组", "样本量", "lift", "p-value", "95% 置信区间", "显著性结论"):
            assert marker in output
        assert "completion_rate" not in output


def test_experiment_pdf_receives_complete_statistics(experiment_result, monkeypatch) -> None:
    captured: list[object] = []
    original = pdf_report._table

    def capture_table(headers, rows, styles, widths=None):
        captured.extend(headers)
        captured.extend(value for row in rows for value in row)
        return original(headers, rows, styles, widths)

    monkeypatch.setattr(pdf_report, "_table", capture_table)
    content = pdf_report.generate_pdf_report(
        experiment_result,
        RunManifest.from_dict(experiment_result["run_manifest"]),
    )
    rendered_values = " ".join(str(value) for value in captured)
    assert content.startswith(b"%PDF")
    for marker in ("实验组", "对照组", "样本量", "lift", "p-value", "95% 置信区间", "显著性结论"):
        assert marker in rendered_values


def test_structured_finding_deduplication_uses_metric_baseline_and_change() -> None:
    summary = "订单量较前 7 日均值下降 12.3%。"
    findings = [
        "订单量相对前 7 日均值下降 12.34%。",
        "支付成功率较前 7 日均值下降 3.1%。",
        "支付成功率较前 7 日均值下降 3.10%。",
    ]
    assert deduplicate_findings(summary, findings) == ["支付成功率较前 7 日均值下降 3.1%。"]
