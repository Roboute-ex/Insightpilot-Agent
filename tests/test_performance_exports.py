"""Per-format behavior, bounded rendering and unchanged output safety."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import openpyxl
import pandas as pd
import plotly.graph_objects as go
import pytest
from streamlit.testing.v1 import AppTest

from app.components import export_panel as panel
from insightpilot.performance import BoundedCache, MemoryBudgetExceeded, PerformanceConfig
from insightpilot.reports import excel, html, markdown, pdf, safety
from insightpilot.reports.manifest import RunManifest


@pytest.fixture
def export_result():
    manifest = RunManifest(
        manifest_version="1.0", project_version="0.1.0", run_id="export-test-run-1",
        created_at="2026-06-30T12:00:00+00:00", data_source_type="synthetic",
        source_summary={}, table_summaries=[], dataset_fingerprints={}, question="本地模拟实验",
        goal_mode="experiment_analysis", goal_mode_source="user_selected", workflow_backend="rule_based",
        playbook_id=None, playbook_parameters={}, column_mapping={}, route_taken=["execute"],
        reviewer_status="PASS", reviewer_score=100,
    )
    return {"run_manifest": manifest.to_dict(), "question": "本地模拟实验", "data_source_type": "synthetic",
            "goal_mode": "experiment_analysis", "route_taken": ["execute"], "trace": {"route_taken": ["execute"]},
            "analysis_result_package": {"executive_summary": "订单量为12，模拟数据。"},
            "result_tables": {"test": pd.DataFrame({"label": ["甲", "乙"], "value": [5.25, 6.75]})},
            "charts": [], "chart_specs": [], "caveats": [], "reviewer": {"status": "PASS", "score": 100}}


def generator_spies(monkeypatch):
    calls = Counter()
    real = {name: getattr(panel, name) for name in ["generate_pdf_report", "generate_html_report", "generate_excel_report", "generate_markdown_report", "generate_export_bundle"]}
    for name, function in real.items():
        def wrapper(*args, _name=name, _function=function, **kwargs):
            calls[_name] += 1
            return _function(*args, **kwargs)
        monkeypatch.setattr(panel, name, wrapper)
    return calls


def test_pdf_is_independent_cache_hit_and_zip_reuses_exact_bytes(export_result, monkeypatch):
    calls = generator_spies(monkeypatch)
    cache = BoundedCache(6, 64 * 1024**2)
    before = deepcopy(export_result)
    first = panel.prepare_export_payload(export_result, "pdf", cache=cache)
    assert calls == {"generate_pdf_report": 1}
    assert panel.prepare_export_payload(export_result, "pdf", cache=cache) is first
    assert calls == {"generate_pdf_report": 1}
    zipped = panel.prepare_export_payload(export_result, "bundle", cache=cache)
    assert calls == {"generate_pdf_report": 1, "generate_html_report": 1, "generate_excel_report": 1,
                     "generate_markdown_report": 1, "generate_export_bundle": 1}
    with ZipFile(BytesIO(zipped)) as archive:
        assert archive.read("report.pdf") == first
        assert set(["report.pdf", "report.md", "report.html", "report.xlsx", "manifest.json", "README.txt"]).issubset(archive.namelist())
    without_csv = panel.prepare_export_payload(export_result, "bundle", cache=cache, options={"include_csv_results": False})
    with ZipFile(BytesIO(without_csv)) as archive:
        assert archive.read("report.pdf") == first
        assert not any(name.startswith("results/") for name in archive.namelist())
    assert calls["generate_pdf_report"] == calls["generate_html_report"] == calls["generate_excel_report"] == 1
    assert export_result["run_manifest"] == before["run_manifest"]
    assert export_result["trace"] == before["trace"]
    assert export_result["route_taken"] == before["route_taken"]
    assert "report_markdown" not in export_result
    pd.testing.assert_frame_equal(export_result["result_tables"]["test"], before["result_tables"]["test"])


def test_cache_identity_ttl_and_budget_have_no_unbounded_fallback(export_result, monkeypatch):
    calls = generator_spies(monkeypatch)
    now = [0.0]
    cache = BoundedCache(6, 64 * 1024**2, 1, clock=lambda: now[0])
    config = PerformanceConfig()
    panel.prepare_export_payload(export_result, "pdf", cache=cache, config=config)
    panel.prepare_export_payload(export_result, "pdf", cache=cache, config=replace(config, export_template_version="changed"))
    assert calls["generate_pdf_report"] == 2
    now[0] = 2
    panel.prepare_export_payload(export_result, "pdf", cache=cache, config=config)
    assert calls["generate_pdf_report"] == 3
    other = {**export_result, "run_manifest": {**export_result["run_manifest"], "run_id": "different-result"}}
    panel.prepare_export_payload(other, "pdf", cache=cache, config=config)
    assert calls["generate_pdf_report"] == 4
    assert panel.export_cache_key(export_result, "excel") != panel.export_cache_key(export_result, "excel", {"compatibility_mode": True})
    tiny = BoundedCache(6, 1024)
    with pytest.raises(MemoryBudgetExceeded):
        panel.prepare_export_payload(export_result, "pdf", cache=tiny)
    assert tiny.size_bytes == 0 and len(tiny) == 0


def test_single_format_ui_does_no_work_until_requested_and_ignores_download_rerun(export_result, monkeypatch):
    calls = generator_spies(monkeypatch)
    app = AppTest.from_string("from app.components.export_panel import render_export_panel\nimport streamlit as st\nrender_export_panel(st.session_state['input_result'])", default_timeout=30)
    app.session_state["input_result"] = export_result
    app.run()
    assert not app.exception and not calls
    assert [button.label for button in app.button] == ["生成 PDF 报告", "生成 Markdown 报告", "生成 HTML 报告", "生成 Excel 报告", "生成 运行清单 JSON", "生成 ZIP 报告包"]
    app.button(key="generate_export_pdf").click().run()
    assert not app.exception and calls == {"generate_pdf_report": 1}
    downloads = app.get("download_button")
    assert len(downloads) == 1 and downloads[0].proto.ignore_rerun
    app.run()
    assert calls == {"generate_pdf_report": 1}
    assert app.session_state["input_result"]["trace"] == {"route_taken": ["execute"]}
    app.session_state["input_result"] = {**export_result, "run_manifest": {**export_result["run_manifest"], "run_id": "new-run"}}
    app.run()
    assert not app.get("download_button")
    assert len(app.session_state["performance_export_cache"]) == 0


def test_output_limits_apply_before_redaction_without_losing_total_rows(export_result, monkeypatch):
    result = {**export_result, "result_tables": {"many": pd.DataFrame({"label": ["正常"] * 2000, "value": range(2000)})}}
    original = result["result_tables"]["many"].copy()
    visits = []
    safe = safety.safe_report_result
    def measured(value, key="", *, synthetic=False):
        if isinstance(value, pd.DataFrame): visits.append(len(value))
        return safe(value, key, synthetic=synthetic)
    monkeypatch.setattr(safety, "safe_report_result", measured)
    manifest = RunManifest.from_dict(result["run_manifest"])
    markdown.generate_markdown_report(result)
    assert visits == []
    captured = []
    paragraph = pdf._paragraph
    def capture(value, *args, **kwargs):
        captured.append(str(value)); return paragraph(value, *args, **kwargs)
    monkeypatch.setattr(pdf, "_paragraph", capture)
    pdf.generate_pdf_report(result, manifest)
    assert visits == [40]
    assert any("共 2000 行，展示前 40 行" in item for item in captured)
    visits.clear()
    content = html.generate_html_report(result, [], manifest)
    assert visits == [100] and "共 2000 行" in content
    visits.clear()
    monkeypatch.setattr(excel, "MAX_EXCEL_RESULT_ROWS", 3)
    workbook = openpyxl.load_workbook(BytesIO(excel.generate_excel_report(result, manifest)))
    assert visits == [3]
    assert workbook["结果_many"].max_row == 4
    assert list(workbook["截断说明"].values)[1] == ("many", 2000, 3)
    pd.testing.assert_frame_equal(result["result_tables"]["many"], original)


def test_only_html_materializes_deferred_charts(export_result, monkeypatch):
    import insightpilot.visualization.result_charts as module
    calls = []
    def materialize(result, spec_ids=None, max_points=3000):
        calls.append(max_points)
        return [(None, go.Figure(go.Bar(x=["甲"], y=[12])))]
    monkeypatch.setattr(module, "materialize_charts", materialize, raising=False)
    result = {**export_result, "presentation_mode": "deferred", "chart_specs": [{"spec_id": "test"}]}
    cache = BoundedCache(6, 64 * 1024**2)
    panel.prepare_export_payload(result, "pdf", cache=cache)
    assert not calls
    content = panel.prepare_export_payload(result, "html", cache=cache)
    assert calls == [3000] and "plotly.js v" in content
    panel.prepare_export_payload(result, "html", cache=cache)
    assert calls == [3000]


def test_compatibility_all_formats_remains_explicit_and_safe(export_result):
    payloads = panel.prepare_export_payloads(export_result)
    assert list(payloads) == list(panel.EXPORT_FORMATS)
    assert payloads["pdf"].startswith(b"%PDF")
    with ZipFile(BytesIO(payloads["bundle"])) as archive:
        assert archive.read("report.pdf") == payloads["pdf"]
        assert archive.read("report.xlsx") == payloads["excel"]
    assert export_result["route_taken"] == ["execute"]


def test_ui_rejects_oversize_download_without_retaining_fallback(export_result, monkeypatch):
    monkeypatch.setenv("INSIGHTPILOT_PERF_EXPORT_MAX_BYTES", "1024")
    monkeypatch.setattr(panel, "generate_pdf_report", lambda *args: b"x" * 2048)
    app = AppTest.from_string("from app.components.export_panel import render_export_panel\nimport streamlit as st\nrender_export_panel(st.session_state['input_result'])", default_timeout=30)
    app.session_state["input_result"] = export_result
    app.run()
    app.button(key="generate_export_pdf").click().run()
    assert not app.exception
    assert any("超过导出缓存预算" in item.value for item in app.warning)
    assert not app.get("download_button")
    assert app.session_state["performance_export_cache"].size_bytes == 0
    assert app.session_state["input_result"]["run_manifest"]["run_id"] == "export-test-run-1"



def test_html_and_zip_explain_actual_chart_budget_rejection(export_result, monkeypatch):
    monkeypatch.setenv("INSIGHTPILOT_PERF_CHART_MAX_POINTS", "10")
    frame = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=30),
                          "value": range(30), "is_anomaly": [True] * 30})
    result = {**export_result, "presentation_mode": "deferred",
              "chart_specs": [{"chart_id": "overflow", "chart_type": "time_series",
                               "title": "趋势", "table_key": "trend", "x": "date", "y": ["value"]}],
              "result_tables": {"trend": frame}}
    original = deepcopy(result)
    cache = BoundedCache(6, 64 * 1024**2)
    content = panel.prepare_export_payload(result, "html", cache=cache)
    assert "异常点超过当前绘图预算" in content and "未删除统计样本" in content
    assert "共 30 行" in content and "plotly.js v" not in content
    with ZipFile(BytesIO(panel.prepare_export_payload(result, "bundle", cache=cache))) as archive:
        assert archive.read("report.html").decode("utf-8") == content
    assert result["caveats"] == original["caveats"]
    assert result["chart_specs"] == original["chart_specs"]
    assert result["trace"] == original["trace"]
    pd.testing.assert_frame_equal(frame, original["result_tables"]["trend"])
