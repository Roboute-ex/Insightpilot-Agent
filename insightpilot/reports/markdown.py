"""Markdown report generation."""

from __future__ import annotations

from typing import Any


def _format_metric(metric: object) -> str:
    if isinstance(metric, dict):
        return f"- {metric.get('metric_name')}: {metric.get('display_name')}"
    return f"- {metric}"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


def _bullet_lines(items: Any, fallback: str = "- 暂无") -> str:
    values = _as_list(items)
    return "\n".join(f"- {item}" for item in values) if values else fallback


def _table_metadata_lines(metadata: Any) -> str:
    if not isinstance(metadata, dict) or not metadata:
        return "- 暂无表结构摘要"
    lines: list[str] = []
    for table_name, item in metadata.items():
        if not isinstance(item, dict):
            continue
        columns = item.get("columns", [])
        if isinstance(columns, list):
            column_preview = ", ".join(str(column) for column in columns[:8])
        else:
            column_preview = str(columns)
        lines.append(
            f"- {table_name}: rows={item.get('row_count', 'N/A')}, "
            f"columns={item.get('column_count', 'N/A')}, fields={column_preview}"
        )
    return "\n".join(lines) if lines else "- 暂无表结构摘要"


def _column_mapping_lines(mapping: Any, mapping_source: str, mapping_warnings: Any) -> str:
    if not isinstance(mapping, dict) or not mapping:
        return "\n".join(
            [
                f"- mapping_source: {mapping_source or 'none'}",
                "- 当前未提供手动字段映射，系统使用自动推断或通用分析 fallback。",
                _bullet_lines(mapping_warnings, "- mapping_warnings: 暂无"),
            ]
        )
    lines = [
        f"- mapping_source: {mapping_source or 'none'}",
        f"- table_name: {mapping.get('table_name')}",
        f"- date_column: {mapping.get('date_column')}",
        f"- metric_columns: {', '.join(_as_list(mapping.get('metric_columns')))}",
        f"- dimension_columns: {', '.join(_as_list(mapping.get('dimension_columns')))}",
        f"- group_column: {mapping.get('group_column')}",
        f"- treatment_column: {mapping.get('treatment_column')}",
        f"- outcome_column: {mapping.get('outcome_column')}",
        f"- time_grain: {mapping.get('time_grain', 'day')}",
        "- mapping_warnings:",
        _bullet_lines(mapping_warnings),
    ]
    return "\n".join(lines)


def _source_label(goal_mode_source: str) -> str:
    if goal_mode_source == "user_selected":
        return "用户选择"
    if goal_mode_source == "auto_detected":
        return "自动识别"
    return goal_mode_source or "自动识别"


def generate_markdown_report(result: dict[str, object]) -> str:
    """Generate a structured v0.2 markdown report from a workflow result."""

    question = str(result.get("question", ""))
    plan = result.get("plan", {})
    plan_dict = plan if isinstance(plan, dict) else {}
    trace = result.get("trace", {})
    trace_dict = trace if isinstance(trace, dict) else {}
    reviewer = result.get("reviewer", {})
    reviewer_dict = reviewer if isinstance(reviewer, dict) else {}

    goal_mode = str(result.get("goal_mode") or plan_dict.get("goal_mode") or "auto")
    goal_mode_display_name = str(
        result.get("goal_mode_display_name") or plan_dict.get("goal_mode_display_name") or "自动识别"
    )
    goal_mode_source = str(result.get("goal_mode_source") or plan_dict.get("goal_mode_source") or "auto_detected")
    workflow_backend = str(result.get("workflow_backend") or trace_dict.get("workflow_backend") or "rule_based")
    route_taken = _as_list(result.get("route_taken") or trace_dict.get("route_taken") or [])
    metrics = result.get("metrics", [])
    findings = result.get("findings", [])
    caveats = result.get("caveats") or result.get("limitations") or []
    next_steps = result.get("next_steps", [])
    data_source_type = str(result.get("data_source_type") or trace_dict.get("data_source_type") or "synthetic")
    table_metadata = result.get("table_metadata") or trace_dict.get("table_metadata_summary") or {}
    schema_warnings = result.get("schema_warnings") or trace_dict.get("schema_warnings") or []
    column_mapping = result.get("column_mapping") or trace_dict.get("column_mapping") or {}
    mapping_warnings = result.get("mapping_warnings") or trace_dict.get("mapping_warnings") or []
    mapping_source = str(result.get("mapping_source") or trace_dict.get("mapping_source") or "none")

    metric_lines = "\n".join(_format_metric(metric) for metric in _as_list(metrics)) or "- 未识别到明确指标"
    step_lines = _bullet_lines(plan_dict.get("analysis_steps", []))
    finding_lines = _bullet_lines(findings)
    caveat_lines = _bullet_lines(caveats, "- synthetic data only")
    next_step_lines = _bullet_lines(next_steps, "- 继续补充更细粒度的 synthetic 场景。")
    route_lines = _bullet_lines(route_taken)

    issues = _as_list(reviewer_dict.get("issues"))
    suggestions = _as_list(reviewer_dict.get("suggestions"))
    checks = reviewer_dict.get("checks", {})
    checks_dict = checks if isinstance(checks, dict) else {}
    reviewer_lines = [
        f"- status: {reviewer_dict.get('status', 'UNKNOWN')}",
        f"- score: {reviewer_dict.get('score', 'N/A')}",
    ]
    reviewer_lines.extend(f"- issue: {issue}" for issue in issues)
    reviewer_lines.extend(f"- suggestion: {suggestion}" for suggestion in suggestions)
    if checks_dict:
        reviewer_lines.append("- Reviewer 检查：")
        reviewer_lines.extend(f"- {name}: {passed}" for name, passed in checks_dict.items())

    trace_summary_lines = [
        f"- trace_id: {trace_dict.get('trace_id', 'N/A')}",
        f"- created_at: {trace_dict.get('created_at', 'N/A')}",
        f"- workflow_backend: {trace_dict.get('workflow_backend', workflow_backend)}",
        f"- route_taken_count: {len(route_taken)}",
        f"- errors_count: {len(_as_list(trace_dict.get('errors', [])))}",
        f"- data_source_type: {data_source_type}",
        f"- mapping_source: {mapping_source}",
    ]

    source_label = _source_label(goal_mode_source)
    plan_lines = [
        f"- 识别出的分析意图：{plan_dict.get('intent', result.get('intent', 'unknown'))}",
        f"- comparison_method: {plan_dict.get('comparison_method', 'unknown')}",
        f"- required_tables: {', '.join(_as_list(plan_dict.get('required_tables', []))) or 'N/A'}",
        "- 分析步骤：",
        step_lines,
    ]

    return "\n".join(
        [
            "# InsightPilot Agent Analysis Report",
            "",
            "## 1. 用户问题",
            question,
            "",
            "## 2. 分析目标模式",
            f"- 分析目标模式：{goal_mode_display_name} ({goal_mode})",
            f"- 来源：{source_label}",
            "",
            "## 3. Workflow Backend",
            f"- workflow_backend: {workflow_backend}",
            "",
            "## 4. Route Taken",
            route_lines,
            "",
            "## 5. 数据来源",
            f"- data_source_type: {data_source_type}",
            "",
            "## 6. 表结构摘要",
            _table_metadata_lines(table_metadata),
            "",
            "## 7. Schema Warnings",
            _bullet_lines(schema_warnings),
            "",
            "## 8. Column Mapping",
            _column_mapping_lines(column_mapping, mapping_source, mapping_warnings),
            "",
            "## 9. 识别指标",
            "涉及指标：",
            metric_lines,
            "",
            "## 10. 分析计划",
            "\n".join(plan_lines),
            "",
            "## 11. 核心发现",
            finding_lines,
            "",
            "## 12. Reviewer 结果",
            "\n".join(reviewer_lines),
            "",
            "## 13. Trace 摘要",
            "\n".join(trace_summary_lines),
            "",
            "## 14. 限制说明",
            caveat_lines,
            "",
            "## 15. 下一步建议",
            next_step_lines,
            "",
        ]
    )
