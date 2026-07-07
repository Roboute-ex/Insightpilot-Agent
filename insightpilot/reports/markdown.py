"""Markdown report generation."""

from __future__ import annotations


def _format_metric(metric: object) -> str:
    if isinstance(metric, dict):
        return f"- {metric.get('metric_name')}: {metric.get('display_name')}"
    return f"- {metric}"


def generate_markdown_report(result: dict[str, object]) -> str:
    """Generate a compact markdown report from a workflow result."""

    question = str(result.get("question", ""))
    plan = result.get("plan", {})
    plan_dict = plan if isinstance(plan, dict) else {}
    goal_mode = str(result.get("goal_mode") or plan_dict.get("goal_mode") or "auto")
    goal_mode_display_name = str(
        result.get("goal_mode_display_name") or plan_dict.get("goal_mode_display_name") or "自动识别"
    )
    goal_mode_source = str(result.get("goal_mode_source") or plan_dict.get("goal_mode_source") or "auto_detected")
    metrics = result.get("metrics", [])
    findings = result.get("findings", [])
    reviewer = result.get("reviewer", {})
    reviewer_dict = reviewer if isinstance(reviewer, dict) else {}
    limitations = result.get("limitations", [])
    next_steps = result.get("next_steps", [])

    metric_lines = "\n".join(_format_metric(metric) for metric in metrics) or "- 未识别到明确指标"
    step_lines = "\n".join(f"- {step}" for step in plan_dict.get("analysis_steps", [])) or "- 暂无"
    finding_lines = "\n".join(f"- {finding}" for finding in findings) or "- 暂无"
    limitation_lines = "\n".join(f"- {item}" for item in limitations) or "- synthetic data only"
    next_step_lines = "\n".join(f"- {item}" for item in next_steps) or "- 继续补充更细粒度的 synthetic 场景。"

    issues = reviewer_dict.get("issues") or []
    suggestions = reviewer_dict.get("suggestions") or []
    reviewer_lines = [f"- 状态：{reviewer_dict.get('status', 'UNKNOWN')}"]
    reviewer_lines.extend(f"- 问题：{issue}" for issue in issues)
    reviewer_lines.extend(f"- 建议：{suggestion}" for suggestion in suggestions)
    source_label = "用户选择" if goal_mode_source == "user_selected" else "自动识别"
    goal_mode_lines = "\n".join(
        [
            f"- 分析目标模式：{goal_mode_display_name}（{goal_mode}）",
            f"- 来源：{source_label}",
        ]
    )

    return "\n".join(
        [
            "# InsightPilot Agent 分析报告",
            "",
            "## 用户问题",
            question,
            "",
            "## 分析目标模式",
            goal_mode_lines,
            "",
            "## 识别出的分析意图",
            str(plan_dict.get("intent", result.get("intent", "unknown"))),
            "",
            "## 涉及指标",
            metric_lines,
            "",
            "## 分析步骤",
            step_lines,
            "",
            "## 核心发现",
            finding_lines,
            "",
            "## Reviewer 检查",
            "\n".join(reviewer_lines),
            "",
            "## 限制说明",
            limitation_lines,
            "",
            "## 下一步建议",
            next_step_lines,
            "",
        ]
    )
