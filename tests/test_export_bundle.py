from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pandas as pd

from insightpilot.reports.bundle import generate_export_bundle


def test_export_bundle_contains_expected_safe_files() -> None:
    content = generate_export_bundle("# Report", "<html></html>", b"xlsx", "{}", {"result table": pd.DataFrame({"x": [1]})})
    with ZipFile(BytesIO(content)) as archive:
        names = set(archive.namelist())
    assert {"report.md", "report.html", "report.xlsx", "manifest.json", "README.txt", "results/result_table.csv"}.issubset(names)
