from __future__ import annotations

from insightpilot.ui.presenters import present_route_timeline


def test_route_timeline_compacts_demo_and_keeps_full_chinese_professional_steps() -> None:
    route = [
        "load_data_source",
        "validate_tables",
        "resolve_metrics",
        "create_plan",
        "execute_playbook",
        "review",
        "generate_report",
    ]
    compact = present_route_timeline(route, compact=True)
    assert [item["name"] for item in compact] == ["数据准备", "指标与字段识别", "分析方案生成", "分析计算", "质量检查", "报告输出"]
    assert all(item["step_ids"] is None for item in compact)
    full = present_route_timeline(route, compact=False, show_ids=False)
    assert full[0]["name"] == "加载数据来源"
    assert all(item["step_id"] is None for item in full)
