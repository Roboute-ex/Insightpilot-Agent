from __future__ import annotations

from pathlib import Path


def test_result_panel_has_all_structured_sections_and_no_legacy_empty_copy() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "components" / "result_panel.py").read_text(encoding="utf-8")
    for title in ("指标对比", "异常检测", "漏斗拆解", "维度贡献", "证据链", "建议清单", "数据质量明细"):
        assert title in source
    assert "当前工作流没有结构化结果表" not in source
