from __future__ import annotations

from insightpilot.agents.workflow import run_agent_analysis
from insightpilot.data.synthetic import generate_all_demo_data
from insightpilot.reports.markdown import generate_markdown_report


def test_markdown_report_contains_required_sections() -> None:
    result = {
        "question": "为什么昨天某城市订单量下降？",
        "plan": {
            "intent": "metric_drop_diagnosis",
            "goal_mode": "metric_diagnosis",
            "goal_mode_display_name": "指标波动诊断",
            "goal_mode_source": "user_selected",
            "analysis_steps": ["检查基准对比"],
        },
        "goal_mode": "metric_diagnosis",
        "goal_mode_display_name": "指标波动诊断",
        "goal_mode_source": "user_selected",
        "metrics": [{"metric_name": "orders", "display_name": "订单量"}],
        "findings": ["限制说明：synthetic data only。"],
        "reviewer": {"status": "PASS", "issues": [], "suggestions": []},
        "limitations": ["仅使用 synthetic data。"],
        "next_steps": ["继续拆解维度。"],
    }
    report = generate_markdown_report(result)
    for section in ["用户问题", "分析目标模式", "识别出的分析意图", "涉及指标", "分析步骤", "核心发现", "Reviewer 检查", "限制说明", "下一步建议"]:
        assert section in report
    assert "指标波动诊断" in report
    assert "来源：用户选择" in report


def test_workflow_returns_trace_and_report() -> None:
    tables = generate_all_demo_data(seed=42)
    result = run_agent_analysis("为什么昨天某城市订单量下降？", tables, goal_mode="metric_diagnosis")
    assert result["reviewer"]["status"] == "PASS"
    assert result["trace"]["identified_intent"] == "metric_drop_diagnosis"
    assert result["goal_mode"] == "metric_diagnosis"
    assert result["trace"]["goal_mode"] == "metric_diagnosis"
    assert "Markdown" not in result["report_markdown"]
    assert "核心发现" in result["report_markdown"]


def test_workflow_goal_mode_auto_and_experiment_are_compatible() -> None:
    tables = generate_all_demo_data(seed=42)
    auto_result = run_agent_analysis("为什么昨天某城市订单量下降？", tables, goal_mode="auto")
    experiment_result = run_agent_analysis("请分析订单下降", tables, goal_mode="experiment_analysis")
    assert auto_result["goal_mode"] == "metric_diagnosis"
    assert auto_result["goal_mode_source"] == "auto_detected"
    assert experiment_result["intent"] == "experiment_analysis"
    assert experiment_result["goal_mode"] == "experiment_analysis"
