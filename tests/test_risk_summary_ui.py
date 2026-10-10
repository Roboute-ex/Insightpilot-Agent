from __future__ import annotations

from pathlib import Path


def test_demo_risks_are_summarized_in_collapsed_expander() -> None:
    source = (Path(__file__).resolve().parents[1] / "insightpilot" / "ui" / "renderers.py").read_text(encoding="utf-8")
    assert "当前分析包含" not in source
    assert 'st.expander("查看风险与限制", expanded=False' in source
