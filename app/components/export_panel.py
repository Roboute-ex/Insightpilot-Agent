"""In-memory export preparation and download controls."""

from __future__ import annotations

from typing import Any

import streamlit as st

from insightpilot.reports.bundle import generate_export_bundle
from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.reports.pdf import generate_pdf_report
from insightpilot.ui.i18n import t


def prepare_export_payloads(result: dict[str, Any]) -> dict[str, str | bytes]:
    result["route_taken"] = list(dict.fromkeys([*result.get("route_taken", []), "generate_exports"]))
    if isinstance(result.get("trace"), dict):
        result["trace"]["route_taken"] = list(result["route_taken"])
    result["export_formats"] = ["pdf", "markdown", "html", "excel", "manifest", "bundle"]
    manifest_values = dict(result["run_manifest"])
    manifest_values["route_taken"] = list(result["route_taken"])
    manifest = RunManifest.from_dict(manifest_values)
    result["run_manifest"] = manifest.to_dict()
    result["report_markdown"] = generate_markdown_report(result)
    html_report = generate_html_report(result, result.get("charts", []), manifest)
    excel_bytes = generate_excel_report(result, manifest)
    pdf_bytes = generate_pdf_report(result, manifest)
    manifest_json = manifest.to_json()
    bundle = generate_export_bundle(
        result["report_markdown"],
        html_report,
        excel_bytes,
        manifest_json,
        result.get("result_tables", {}),
        pdf_bytes=pdf_bytes,
    )
    return {
        "pdf": pdf_bytes,
        "markdown": result["report_markdown"],
        "html": html_report,
        "excel": excel_bytes,
        "manifest": manifest_json,
        "bundle": bundle,
    }


def render_export_panel(result: dict[str, Any]) -> None:
    st.subheader(t("section.export"), anchor=False)
    run_id = str(result.get("run_manifest", {}).get("run_id") or "analysis")
    if st.button(t("action.prepare_exports"), icon=":material/package_2:"):
        try:
            st.session_state["export_payloads"] = prepare_export_payloads(result)
            st.session_state["export_run_id"] = run_id
        except Exception as exc:
            st.warning(f"导出准备失败，分析结果仍可继续查看：{exc}")
    payloads = st.session_state.get("export_payloads") if st.session_state.get("export_run_id") == run_id else None
    if not isinstance(payloads, dict):
        st.caption("按需准备导出文件；所有文件均在内存中生成。Excel 以中文工作表为主，并保留英文兼容别名。")
        return
    prefix = f"insightpilot_{run_id[:8]}"
    with st.container(horizontal=True):
        st.download_button("下载 PDF 报告", payloads["pdf"], f"{prefix}.pdf", "application/pdf", icon=":material/download:")
        st.download_button(t("action.download_markdown"), payloads["markdown"], f"{prefix}.md", "text/markdown", icon=":material/download:")
        st.download_button(t("action.download_html"), payloads["html"], f"{prefix}.html", "text/html", icon=":material/download:")
        st.download_button(t("action.download_excel"), payloads["excel"], f"{prefix}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")
        st.download_button(t("action.download_manifest"), payloads["manifest"], f"{prefix}_manifest.json", "application/json", icon=":material/download:")
        st.download_button(t("action.download_bundle"), payloads["bundle"], f"{prefix}.zip", "application/zip", icon=":material/download:")
