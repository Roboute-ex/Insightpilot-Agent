from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.reports.html import generate_html_report
from insightpilot.reports.manifest import RunManifest


def test_html_export_contains_sections_and_embedded_plotly(playbook_tables, playbook_mapping) -> None:
    result = run_agent_analysis("<script>alert(1)</script>", playbook_tables, goal_mode="growth_trend", column_mapping=playbook_mapping, data_source_type="uploaded_files", playbook_id="metric_trend")
    html = generate_html_report(result, result["charts"], RunManifest.from_dict(result["run_manifest"]))
    assert "Interactive Plotly Charts" in html
    assert "plotly" in html.lower()
    assert 'src="https://cdn.plot.ly' not in html.lower()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
