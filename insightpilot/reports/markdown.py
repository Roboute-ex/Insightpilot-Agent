"""Chinese-first Markdown report generation over stable English schemas."""

from __future__ import annotations

from typing import Any

from insightpilot.ui.formatters import (
    format_enum_value,
    format_metric_name,
    format_metric_text,
    format_reviewer_check_name,
    format_route_steps,
    format_status,
)
from insightpilot.ui.presenters import (
    METRIC_DISPLAY_NAMES,
    present_analysis_plan,
    present_join_plan,
    present_query_plan,
    translate_caveat,
)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value] if value not in (None, "") else []


def _bullets(values: Any, fallback: str = "- 暂无") -> str:
    items = _as_list(values)
    return "\n".join(f"- {item}" for item in items) if items else fallback


def _metadata_lines(metadata: Any) -> str:
    if not isinstance(metadata, dict) or not metadata:
        return "- 暂无表结构摘要"
    lines = []
    for table_name, item in metadata.items():
        if not isinstance(item, dict):
            continue
        columns = item.get("columns", [])
        preview = "、".join(format_metric_name(column) for column in columns[:8]) if isinstance(columns, list) else format_metric_text(columns)
        lines.append(f"- {table_name}：{item.get('row_count', '未知')} 行，{item.get('column_count', '未知')} 个字段；字段示例：{preview}")
    return "\n".join(lines) or "- 暂无表结构摘要"


def _mapping_lines(result: dict[str, object]) -> str:
    mapping = result.get("column_mapping") if isinstance(result.get("column_mapping"), dict) else {}
    if not mapping:
        return "- 当前未提供手动字段映射，系统使用自动识别或通用回退。"
    return "\n".join(
        [
            f"- 映射来源：{result.get('mapping_source', 'none')}",
            f"- 数据表：{mapping.get('table_name')}",
            f"- 日期字段：{mapping.get('date_column') or '未选择'}",
            f"- 指标字段：{'、'.join(format_metric_name(item) for item in _as_list(mapping.get('metric_columns'))) or '未选择'}",
            f"- 维度字段：{'、'.join(_as_list(mapping.get('dimension_columns'))) or '未选择'}",
            f"- 分组字段：{mapping.get('group_column') or '未选择'}",
            f"- 处理字段：{mapping.get('treatment_column') or '未选择'}",
            f"- 结果字段：{mapping.get('outcome_column') or '未选择'}",
        ]
    )


def _metric_lines(result: dict[str, object]) -> str:
    request = result.get("metric_request") if isinstance(result.get("metric_request"), dict) else {}
    if request.get("metrics"):
        return _bullets([METRIC_DISPLAY_NAMES.get(str(item), str(item)) for item in request["metrics"]])
    values = []
    for metric in _as_list(result.get("metrics")):
        if isinstance(metric, dict):
            values.append(metric.get("display_name") or metric.get("metric_name"))
        else:
            values.append(METRIC_DISPLAY_NAMES.get(str(metric), str(metric)))
    return _bullets(values, "- 未识别到明确指标")


def _plan_lines(plan: dict[str, Any]) -> str:
    view = present_analysis_plan(plan)
    return "\n".join(
        [
            f"- 分析目标模式：{view.goal_name}",
            f"- 识别出的分析意图：{view.intent_name}",
            f"- 目标来源：{view.goal_source_text}",
            f"- 对比方式：{view.comparison_method_text}",
            f"- 分析维度：{'、'.join(view.dimension_names)}",
            f"- 所需数据表：{'、'.join(view.required_table_names) or '未明确'}",
            "- 分析步骤：",
            *[f"  {index}. {step}" for index, step in enumerate(view.step_descriptions, start=1)],
        ]
    )


def _join_lines(plan: Any) -> str:
    if not isinstance(plan, dict) or not plan:
        return "- 本次未使用语义多表连接计划。"
    view = present_join_plan(plan)
    lines = [
        f"- 使用数据表数量：{view.table_count}",
        f"- 连接步骤数量：{view.step_count}",
        f"- 风险等级：{view.risk_text}",
        f"- 是否需要审批：{view.requires_approval_text}",
        f"- 输出粒度：{view.output_grain}",
    ]
    lines.extend(
        f"- {row['起始表']} → {row['目标表']}；{row['连接字段']}；{row['关系类型']}；{row['风险']}"
        for row in view.step_rows
    )
    return "\n".join(lines)


def _query_lines(plan: Any) -> str:
    if not isinstance(plan, dict) or not plan:
        return "- 本次未生成语义查询计划。"
    view = present_query_plan(plan)
    return "\n".join(
        [
            f"- 查询计划编号：{view.plan_id}",
            f"- 查询指标：{'、'.join(view.metric_names)}",
            f"- 分析维度：{'、'.join(view.dimension_names) or '整体'}",
            f"- 时间范围：{view.date_range_text}",
            f"- 时间粒度：{view.time_grain_text}",
            f"- 风险等级：{view.risk_text}",
            f"- 执行状态：{view.executable_text}",
            f"- 参数数量：{view.parameter_count}",
        ]
    )


def _reviewer_lines(reviewer: Any) -> str:
    values = reviewer if isinstance(reviewer, dict) else {}
    lines = [f"- 状态：{format_status(str(values.get('status', 'WARN')))}", f"- 质量评分：{values.get('score', '未知')}"]
    lines.extend(f"- 问题：{item}" for item in _as_list(values.get("issues")))
    lines.extend(f"- 建议：{item}" for item in _as_list(values.get("suggestions")))
    checks = values.get("checks", {}) if isinstance(values.get("checks"), dict) else {}
    lines.extend(f"- {format_reviewer_check_name(name)}：{'通过' if passed else '未通过'}" for name, passed in checks.items())
    return "\n".join(lines)


def _contract_lines(results: Any) -> str:
    if not isinstance(results, list) or not results:
        return "- 本次没有结构化数据契约结果。"
    passed = sum(item.get("status") == "PASS" for item in results if isinstance(item, dict))
    warned = sum(item.get("status") == "WARN" for item in results if isinstance(item, dict))
    failed = sum(item.get("status") == "FAIL" for item in results if isinstance(item, dict))
    return f"- 检查总数：{len(results)}\n- 通过：{passed}\n- 警告：{warned}\n- 错误：{failed}"


def _lineage_lines(lineage: Any) -> str:
    if not isinstance(lineage, dict) or not lineage:
        return "- 本次没有结构化数据血缘。"
    return "\n".join(
        [
            f"- 输入与输出数据节点：{len(lineage.get('datasets', []))}",
            f"- 执行操作：{len(lineage.get('operations', []))}",
            f"- 派生关系：{len(lineage.get('edges', []))}",
            f"- 数据血缘指纹：{lineage.get('lineage_fingerprint', '暂无')}",
        ]
    )


def _observability_lines(result: dict[str, object]) -> str:
    telemetry = result.get("telemetry") if isinstance(result.get("telemetry"), dict) else {}
    summary = telemetry.get("summary", {}) if isinstance(telemetry.get("summary"), dict) else {}
    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    return "\n".join(
        [
            f"- 运行编号：{result.get('run_manifest', {}).get('run_id', trace.get('trace_id', '未知')) if isinstance(result.get('run_manifest'), dict) else trace.get('trace_id', '未知')}",
            f"- 工作流后端（Workflow Backend）：{format_enum_value('backend', result.get('workflow_backend'))}",
            f"- 内部后端标识：{result.get('workflow_backend', 'rule_based')}",
            f"- 总耗时：{summary.get('total_duration_ms', 0)} 毫秒",
            f"- 查询次数：{summary.get('query_count', len(trace.get('executed_queries', [])))}",
            f"- 最慢步骤：{format_enum_value('route_step', summary.get('slowest_step'))}",
            f"- 警告数量：{summary.get('warning_count', 0)}",
            f"- 错误数量：{summary.get('error_count', len(_as_list(result.get('errors'))))}",
            f"- Trace 摘要：{trace.get('trace_id', '未知')}，共 {len(_as_list(result.get('route_taken')))} 个路由节点",
        ]
    )


def _package_records(result: dict[str, object], key: str) -> list[dict[str, Any]]:
    package = result.get("analysis_result_package") if isinstance(result.get("analysis_result_package"), dict) else {}
    values = package.get(key, []) if isinstance(package, dict) else []
    return [item for item in values if isinstance(item, dict)]


def _comparison_lines(result: dict[str, object]) -> str:
    rows = _package_records(result, "metric_comparisons")
    return _bullets([
        f"{format_metric_name(item.get('metric_id'))}："
        f"当前 {float(item.get('current_value', 0)):,.4g}，基准 {float(item.get('baseline_value', 0)):,.4g}，"
        f"变化 {float(item.get('relative_change', 0)):.1%}，等级 {item.get('severity')}"
        for item in rows[:20]
    ], "- 暂无指标对比结果")


def _experiment_lines(result: dict[str, object]) -> str:
    rows = _package_records(result, "experiment_results")
    if not rows:
        return "- 当前分析不包含实验组与对照组比较。"
    lines: list[str] = []
    for item in rows:
        metric_id = str(item.get("metric_id", ""))
        is_rate = metric_id.endswith("_rate") or metric_id in {"ctr", "cvr", "conversion_rate"}
        value = lambda number: f"{float(number or 0):.2%}" if is_rate else f"{float(number or 0):,.4g}"
        lines.extend(
            [
                f"- 分析指标：{format_metric_name(metric_id)}",
                f"- 实验组：{value(item.get('treatment_value'))}，样本量 {int(item.get('treatment_sample_size', 0)):,}",
                f"- 对照组：{value(item.get('control_value'))}，样本量 {int(item.get('control_sample_size', 0)):,}",
                f"- lift：绝对 {value(item.get('absolute_lift'))}，相对 {float(item.get('relative_lift', 0)):.2%}",
                f"- p-value：{float(item.get('p_value', 1)):.6g}",
                f"- 95% 置信区间：[{value(item.get('confidence_interval_lower'))}, {value(item.get('confidence_interval_upper'))}]",
                f"- 显著性结论：{item.get('significance_conclusion')}",
            ]
        )
    return "\n".join(lines)


def _structured_lines(result: dict[str, object], key: str, formatter: Any, fallback: str) -> str:
    return _bullets([formatter(item) for item in _package_records(result, key)[:20]], fallback)


def generate_markdown_report(result: dict[str, object]) -> str:
    """Generate a Chinese-first report without changing result or manifest keys."""

    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    caveats = [translate_caveat(item) for item in _as_list(result.get("caveats") or result.get("limitations"))]
    route = format_route_steps([str(item) for item in _as_list(result.get("route_taken"))])
    selected = result.get("selected_playbook") if isinstance(result.get("selected_playbook"), dict) else {}
    export_lines = (
        "- 可按需生成 Markdown、离线 HTML、Excel、运行清单 JSON 和完整压缩包。"
        if selected
        else "- 选择分析剧本后可按需准备完整导出文件。"
    )
    return "\n".join(
        [
            "# InsightPilot Agent 中文分析报告",
            "<!-- InsightPilot Agent Analysis Report: v0.5 compatibility marker -->",
            "",
            "## 执行摘要",
            format_metric_text((result.get("analysis_result_package") or {}).get("executive_summary") if isinstance(result.get("analysis_result_package"), dict) else result.get("summary", "")),
            "",
            "## 实验分析结果",
            _experiment_lines(result),
            "",
            "## 核心指标表现",
            _comparison_lines(result),
            "",
            "## 异常检测结果",
            _structured_lines(result, "anomalies", lambda item: f"{format_metric_name(item.get('metric_id'))}：实际值 {float(item.get('actual_value', 0)):,.4g}，预期值 {float(item.get('expected_value', 0)):,.4g}，等级 {item.get('severity')}", "- 暂无异常检测结果"),
            "",
            "## 漏斗拆解",
            _structured_lines(result, "funnel_results", lambda item: f"{item.get('stage_name')}：转化率变化 {float(item.get('rate_change_pp', 0)):.2f} 个百分点，估算订单影响 {float(item.get('estimated_order_impact', 0)):.2f}，贡献占比 {float(item.get('contribution_pct', 0)):.1%}", "- 当前分析类型不适用交易漏斗拆解"),
            "",
            "## 维度贡献",
            _structured_lines(result, "dimension_contributions", lambda item: f"{item.get('dimension')}={item.get('dimension_value')}：贡献值 {float(item.get('contribution_value', 0)):.3g}，贡献占比 {float(item.get('contribution_pct', 0)):.1%}", "- 暂无维度贡献结果"),
            "",
            "## 证据链",
            _structured_lines(result, "evidence", lambda item: f"{item.get('evidence_id')}：{item.get('claim')}", "- 暂无结构化证据"),
            "",
            "## 建议清单",
            _structured_lines(result, "recommendations", lambda item: f"[{item.get('priority')}] {item.get('action')}；证据：{'、'.join(item.get('supporting_evidence_ids', []))}", "- 暂无证据绑定建议"),
            "",
            "## 1. 分析问题（用户问题）",
            str(result.get("question", "")),
            "",
            "## 2. 数据来源",
            f"- 数据来源：{format_enum_value('data_source', result.get('data_source_type'))}",
            _metadata_lines(result.get("table_metadata")),
            "",
            "## 3. 分析目标（分析目标模式）",
            f"- 分析目标模式：{format_enum_value('goal_mode', result.get('goal_mode'))}",
            f"- 来源：{'用户选择' if result.get('goal_mode_source') == 'user_selected' else '自动识别'}",
            "",
            "## 4. 分析方案（分析计划）",
            _plan_lines(plan),
            "",
            "### 字段映射",
            _mapping_lines(result),
            "",
            "### 执行路径（Route Taken）",
            _bullets(route),
            "",
            "## 5. 语义指标（识别指标）",
            _metric_lines(result),
            "",
            "### 查询计划",
            _query_lines(result.get("query_plan")),
            "",
            "## 6. 多表连接方案",
            _join_lines(result.get("join_plan")),
            "",
            "## 7. 核心发现",
            _bullets([format_metric_text(item) for item in _as_list(result.get("findings"))]),
            "",
            "## 8. 可视化诊断（Visual Diagnostics）",
            _bullets([str(item.get("title")) for item in _as_list(result.get("chart_specs")) if isinstance(item, dict)], "- 暂无可用图表规格。"),
            "",
            "## 9. 分析质量检查（Reviewer 结果）",
            _reviewer_lines(result.get("reviewer")),
            "",
            "## 10. 数据质量与 Contract",
            _contract_lines(result.get("contract_results")),
            "",
            "## 11. 风险与限制（限制说明）",
            _bullets(caveats, "- 当前未提供额外限制说明。"),
            "",
            "## 12. 数据血缘",
            _lineage_lines(result.get("lineage")),
            "",
            "## 13. 运行摘要（Trace 摘要）",
            _observability_lines(result),
            "",
            "## 14. 可复现配置（Run Manifest）",
            f"- 运行清单版本：{result.get('run_manifest', {}).get('manifest_version', '暂无') if isinstance(result.get('run_manifest'), dict) else '暂无'}",
            f"- 分析剧本：{format_enum_value('playbook', selected.get('playbook_id') or '未选择')}",
            f"- 导出说明：{export_lines.removeprefix('- ')}",
            "",
            "## 15. 后续建议（下一步建议）",
            _bullets(result.get("next_steps"), "- 继续复核指标口径、数据质量和不确定性边界。"),
            "",
        ]
    )
