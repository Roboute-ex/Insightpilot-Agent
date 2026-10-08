"""Per-format, session-owned report exports tied to a completed result snapshot."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from insightpilot.performance import BoundedCache, MemoryBudgetExceeded, PerformanceConfig
from insightpilot.reports.bundle import generate_export_bundle
from insightpilot.reports.excel import generate_excel_report
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest, _safe_string
from insightpilot.reports.markdown import generate_markdown_report
from insightpilot.reports.pdf import generate_pdf_report
from insightpilot.ui.i18n import t

EXPORT_FORMATS = ("pdf", "markdown", "html", "excel", "manifest", "bundle")
_EXPORT_LABELS = {
    "pdf": ("PDF 报告", ".pdf", "application/pdf"),
    "markdown": ("Markdown 报告", ".md", "text/markdown"),
    "html": ("HTML 报告", ".html", "text/html"),
    "excel": ("Excel 报告", ".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "manifest": ("运行清单 JSON", "_manifest.json", "application/json"),
    "bundle": ("ZIP 报告包", ".zip", "application/zip"),
}
EXPORT_CACHE_KEY = "performance_export_cache"


def _validated_options(options: dict[str, Any] | None) -> dict[str, bool]:
    options = dict(options or {})
    unknown = set(options) - {"compatibility_mode", "include_csv_results"}
    if unknown:
        raise ValueError("未知导出选项：" + "、".join(sorted(unknown)))
    if any(not isinstance(value, bool) for value in options.values()):
        raise ValueError("导出兼容模式与CSV明细选项必须为布尔值。")
    return {"compatibility_mode": options.get("compatibility_mode", False),
            "include_csv_results": options.get("include_csv_results", True)}


def export_cache_key(result: dict[str, Any], format_name: str,
                     options: dict[str, Any] | None = None,
                     config: PerformanceConfig | None = None) -> tuple[str, str, str, str]:
    if format_name not in EXPORT_FORMATS:
        raise ValueError("不支持的导出格式。")
    run_id = str((result.get("run_manifest") or {}).get("run_id") or "")
    if not run_id:
        raise ValueError("缺少明确运行编号，请先执行分析。")
    config = config or PerformanceConfig.from_environment()
    # Presentation/navigation controls are deliberately absent. The completed
    # run_id owns the data/config snapshot, and export options have their own key.
    validated = _validated_options(options)
    effective = validated if format_name == "bundle" else (
        {"compatibility_mode": validated["compatibility_mode"]} if format_name == "excel" else {}
    )
    return run_id, config.export_template_version + ":" + str(result.get("presentation_fingerprint", "")), format_name, json.dumps(effective, sort_keys=True)


def _new_export_cache(config: PerformanceConfig) -> BoundedCache:
    return BoundedCache(config.export_max_entries, config.export_max_bytes, config.session_ttl_seconds)


def _export_snapshot(result: dict[str, Any]) -> tuple[dict[str, Any], RunManifest]:
    # Do not deepcopy result tables or mutate the analysis trace on download.
    snapshot = dict(result)
    route = list(dict.fromkeys([*result.get("route_taken", []), "generate_exports"]))
    snapshot["route_taken"] = route
    if isinstance(result.get("trace"), dict):
        snapshot["trace"] = {**result["trace"], "route_taken": list(route)}
    manifest_values = {**result["run_manifest"], "route_taken": list(route)}
    manifest = RunManifest.from_dict(manifest_values)
    snapshot["run_manifest"] = manifest.to_dict()
    return snapshot, manifest


def prepare_export_payload(result: dict[str, Any], format_name: str, *,
                           cache: BoundedCache | None = None,
                           options: dict[str, Any] | None = None,
                           config: PerformanceConfig | None = None) -> str | bytes:
    """Generate exactly the requested format; ZIP reuses cached dependencies.

    Callers must not mutate a completed result while keeping its run_id. The UI
    stores completed results as snapshots and discards this cache on replacement.
    Cache limits apply to retained objects, not transient generation RSS.
    """
    config = config or PerformanceConfig.from_environment()
    if cache is None:
        cache = _new_export_cache(config)
    options = _validated_options(options)
    key = export_cache_key(result, format_name, options, config)
    cached = cache.get(key)
    if cached is not None:
        return cached
    snapshot, manifest = _export_snapshot(result)
    if format_name == "pdf":
        payload = generate_pdf_report(snapshot, manifest)
    elif format_name == "markdown":
        payload = generate_markdown_report(snapshot)
    elif format_name == "html":
        payload = generate_html_report(snapshot, snapshot.get("charts", []), manifest)
    elif format_name == "excel":
        payload = generate_excel_report(snapshot, manifest, compatibility_mode=options["compatibility_mode"])
    elif format_name == "manifest":
        payload = manifest.to_json()
    else:
        # Each dependency uses the same result/template/options identity. Existing
        # PDF bytes are passed directly, so the bundled PDF is byte-identical.
        dependencies = {name: prepare_export_payload(result, name, cache=cache, options=options, config=config)
                        for name in EXPORT_FORMATS if name != "bundle"}
        payload = generate_export_bundle(
            dependencies["markdown"], dependencies["html"], dependencies["excel"],
            dependencies["manifest"], result.get("result_tables", {}),
            include_csv_results=options["include_csv_results"], pdf_bytes=dependencies["pdf"],
        )
    # Reject oversized payloads instead of retaining a second unbounded fallback.
    cache.put(key, payload)
    return payload


def prepare_export_payloads(result: dict[str, Any]) -> dict[str, str | bytes]:
    """Compatibility API for callers explicitly requesting all six formats."""
    config = PerformanceConfig.from_environment()
    cache = _new_export_cache(config)
    return {name: prepare_export_payload(result, name, cache=cache, config=config) for name in EXPORT_FORMATS}


def _retain_export_tab() -> None:
    st.session_state["requested_result_tab"] = t("tab.export")


def render_export_panel(result: dict[str, Any]) -> None:
    st.subheader(t("section.export"), anchor=False)
    config = PerformanceConfig.from_environment()
    run_id = export_cache_key(result, "pdf", config=config)[0]
    cache = st.session_state.get(EXPORT_CACHE_KEY)
    if (not isinstance(cache, BoundedCache) or st.session_state.get("export_run_id") != run_id
            or (cache.max_entries, cache.max_bytes, cache.ttl_seconds) !=
            (config.export_max_entries, config.export_max_bytes, config.session_ttl_seconds)):
        if isinstance(cache, BoundedCache):
            cache.clear()
        cache = _new_export_cache(config)
        st.session_state[EXPORT_CACHE_KEY] = cache
        st.session_state["export_run_id"] = run_id
        st.session_state.pop("export_payloads", None)
    cache.expire()
    requested = None
    with st.container(horizontal=True):
        for name in EXPORT_FORMATS:
            if st.button("生成 " + _EXPORT_LABELS[name][0], key="generate_export_" + name,
                         on_click=_retain_export_tab):
                requested = name
    if requested:
        try:
            with st.spinner("正在生成" + _EXPORT_LABELS[requested][0] + "…"):
                prepare_export_payload(result, requested, cache=cache, config=config)
        except MemoryBudgetExceeded as exc:
            st.warning("报告超过导出缓存预算，未保留下载文件；分析结果仍保留。" + _safe_string(str(exc))
                       + " 可显式调整 INSIGHTPILOT_PERF_EXPORT_MAX_BYTES 后重试。")
        except Exception as exc:
            st.warning("导出失败，分析结果仍可继续查看：" + _safe_string(str(exc)))
    prefix = f"insightpilot_{run_id[:8]}"
    with st.container(horizontal=True):
        for name in EXPORT_FORMATS:
            payload = cache.get(export_cache_key(result, name, config=config))
            if payload is not None:
                label, suffix, mime = _EXPORT_LABELS[name]
                st.download_button("下载 " + label, payload, prefix + suffix, mime,
                                   key="download_export_" + name, icon=":material/download:", on_click="ignore")
    st.caption("仅点击对应按钮才生成文件；ZIP复用本次运行已生成的报告。PDF每表最多40行、最多20表；"
               "HTML每表预览100行；Excel/CSV每表最多100,000行，CSV最多20表，超限均有说明。")
    st.caption(f"本会话导出缓存：{len(cache)}/{config.export_max_entries}项，估计{cache.size_bytes / 1024**2:.2f}/"
               f"{config.export_max_bytes / 1024**2:.0f} MiB；闲置{config.session_ttl_seconds:g}秒过期。"
               "缓存预算不是生成时的进程内存硬上限。")
