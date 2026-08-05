from __future__ import annotations

from insightpilot.analysis.results import AnalysisResultPackage


def test_workflow_analysis_result_package_validates(transaction_result) -> None:
    package = transaction_result["analysis_result_package"]
    assert package["has_structured_results"] is True
    assert package["result_tables"]["metric_comparisons"]["row_count"] > 0
    assert package["executive_summary"] not in transaction_result["findings"]
    assert transaction_result["findings"]
    assert any("前 7 日均值" in finding for finding in transaction_result["findings"])


def test_empty_package_reports_validation_issues() -> None:
    package = AnalysisResultPackage("", "transaction", "", "")
    assert package.validate()
    assert package.has_structured_results() is False
