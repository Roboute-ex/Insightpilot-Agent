"""Single-file offline HTML report export."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd

from insightpilot.reports.manifest import RunManifest


MAX_HTML_TABLE_ROWS = 100


def _items(values: Any) -> str:
    if not values:
        return "<p>暂无</p>"
    return "<ul>" + "".join(f"<li>{escape(str(value))}</li>" for value in values) + "</ul>"


def _definition(values: dict[str, Any]) -> str:
    return "<dl>" + "".join(
        f"<dt>{escape(str(key))}</dt><dd>{escape(str(value))}</dd>" for key, value in values.items()
    ) + "</dl>"


def _table_sections(result_tables: dict[str, pd.DataFrame]) -> str:
    sections: list[str] = []
    for name, frame in result_tables.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        preview = frame.head(MAX_HTML_TABLE_ROWS).copy()
        sections.append(
            f"<h3>{escape(str(name))}</h3>"
            f"<p>{len(frame)} rows, {len(frame.columns)} columns; preview capped at {MAX_HTML_TABLE_ROWS} rows.</p>"
            + preview.to_html(index=False, escape=True, border=0)
        )
    return "".join(sections) or "<p>暂无结果表。</p>"


def generate_html_report(
    result: dict[str, Any],
    figures: list[Any],
    manifest: RunManifest,
) -> str:
    """Generate an offline HTML report with embedded Plotly figures."""

    chart_fragments: list[str] = []
    for index, item in enumerate(figures):
        figure = item[1] if isinstance(item, tuple) and len(item) == 2 else item
        if not hasattr(figure, "to_html"):
            continue
        chart_fragments.append(
            figure.to_html(full_html=False, include_plotlyjs=not chart_fragments)
        )
    reviewer = result.get("reviewer", {}) if isinstance(result.get("reviewer"), dict) else {}
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    mapping = result.get("column_mapping") if isinstance(result.get("column_mapping"), dict) else {}
    route = result.get("route_taken") or []
    result_tables = result.get("result_tables") if isinstance(result.get("result_tables"), dict) else {}
    source_summary = manifest.source_summary
    style = """
body{font-family:Arial,sans-serif;max-width:1180px;margin:0 auto;padding:28px;color:#202124;line-height:1.5}
h1,h2{color:#15324a}section{border-top:1px solid #d9e0e5;padding:18px 0}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #d9e0e5;padding:6px;text-align:left}th{background:#f4f7f9}dt{font-weight:700}dd{margin:0 0 8px}
"""
    return "".join(
        [
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">",
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
            f"<title>{escape(str(selected.get('display_name') or 'InsightPilot Analysis Report'))}</title>",
            f"<style>{style}</style></head><body>",
            "<h1>InsightPilot Agent Analysis Report</h1>",
            f"<p>运行时间：{escape(manifest.created_at)}</p>",
            f"<section><h2>数据来源摘要</h2>{_definition(source_summary)}</section>",
            f"<section><h2>用户问题</h2><p>{escape(str(result.get('question', '')))}</p></section>",
            f"<section><h2>Analysis Goal Mode</h2><p>{escape(str(result.get('goal_mode', 'auto')))}</p></section>",
            f"<section><h2>Analysis Playbook</h2>{_definition(selected or {'playbook_id': manifest.playbook_id or 'none'})}</section>",
            f"<section><h2>Column Mapping</h2>{_definition(mapping)}</section>",
            f"<section><h2>Playbook Parameters</h2>{_definition(manifest.playbook_parameters)}</section>",
            f"<section><h2>Workflow Route</h2>{_items(route)}</section>",
            f"<section><h2>核心发现</h2>{_items(result.get('findings'))}</section>",
            f"<section><h2>Reviewer</h2>{_definition({'status': reviewer.get('status', 'UNKNOWN'), 'score': reviewer.get('score', 'N/A')})}</section>",
            f"<section><h2>Caveats</h2>{_items(result.get('caveats'))}</section>",
            f"<section><h2>Result Tables</h2>{_table_sections(result_tables)}</section>",
            f"<section><h2>Interactive Plotly Charts</h2>{''.join(chart_fragments) or '<p>暂无可用图表。</p>'}</section>",
            f"<section><h2>Run Manifest</h2>{_definition({'run_id': manifest.run_id, 'project_version': manifest.project_version, 'workflow_backend': manifest.workflow_backend, 'reviewer_score': manifest.reviewer_score})}</section>",
            "</body></html>",
        ]
    )
