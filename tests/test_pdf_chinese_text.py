from __future__ import annotations

from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.pdf import generate_pdf_report


def test_pdf_chinese_generation_does_not_raise(transaction_result) -> None:
    result = dict(transaction_result)
    result["question"] = "请生成包含中文指标、建议和风险说明的分析报告。"
    content = generate_pdf_report(result, RunManifest.from_dict(result["run_manifest"]))
    assert content.endswith(b"%%EOF\n") or b"%%EOF" in content[-20:]
