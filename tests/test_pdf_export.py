from __future__ import annotations

from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.pdf import generate_pdf_report


def test_pdf_export_is_valid_and_reasonably_sized(transaction_result) -> None:
    content = generate_pdf_report(transaction_result, RunManifest.from_dict(transaction_result["run_manifest"]))
    assert content.startswith(b"%PDF")
    assert len(content) > 8_000
