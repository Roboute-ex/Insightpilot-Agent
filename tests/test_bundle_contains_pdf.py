from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from app.components.export_panel import prepare_export_payloads


def test_bundle_contains_pdf(transaction_result) -> None:
    payloads = prepare_export_payloads(transaction_result)
    with ZipFile(BytesIO(payloads["bundle"])) as archive:
        assert "report.pdf" in archive.namelist()
        assert archive.read("report.pdf").startswith(b"%PDF")
