"""Built-in playbook definitions."""

from __future__ import annotations

from insightpilot.playbooks.models import AnalysisParameter, AnalysisPlaybook, PlaybookRequirements


def _parameter(
    name: str,
    display_name: str,
    parameter_type: str,
    *,
    required: bool = False,
    default: object | None = None,
    choices: list[object] | None = None,
    description: str = "",
) -> AnalysisParameter:
    return AnalysisParameter(
        name=name,
        display_name=display_name,
        parameter_type=parameter_type,
        required=required,
        default=default,
        choices=choices or [],
        description=description,
    )


BUILTIN_PLAYBOOKS: list[AnalysisPlaybook] = [
    AnalysisPlaybook(
        playbook_id="data_profile",
        display_name="数据概览与质量检查",
        description="检查表规模、字段类型、缺失率、唯一值、数值分布和重复行。",
        supported_goal_modes=["periodic_report", "metric_diagnosis", "growth_trend"],
        requirements=PlaybookRequirements(requires_table=True),
        parameters=[_parameter("high_missing_threshold", "高缺失阈值", "float", default=0.5)],
        executor_name="execute_data_profile",
        chart_types=["missingness_bar", "histogram"],
        output_sections=["profile", "quality", "numeric_summary"],
        tags=["profile", "quality"],
    ),
    AnalysisPlaybook(
        playbook_id="metric_trend",
        display_name="指标趋势分析",
        description="按日、周或月聚合指标，计算环比、滚动均值并标记异常点。",
        supported_goal_modes=["growth_trend", "metric_diagnosis", "periodic_report"],
        requirements=PlaybookRequirements(requires_date_column=True, requires_metric_columns=True),
        parameters=[
            _parameter("date_range", "日期范围", "date_range"),
            _parameter("time_grain", "时间粒度", "choice", default="day", choices=["day", "week", "month"]),
            _parameter("aggregation", "聚合方式", "choice", default="sum", choices=["sum", "mean", "count", "min", "max"]),
            _parameter("rolling_window", "滚动窗口", "integer", default=7),
            _parameter("anomaly_threshold", "异常阈值", "float", default=2.0),
        ],
        executor_name="execute_metric_trend",
        chart_types=["time_series", "line"],
        output_sections=["trend", "change", "anomalies"],
        tags=["trend", "metric"],
    ),
    AnalysisPlaybook(
        playbook_id="period_comparison",
        display_name="周期对比分析",
        description="比较两个日期区间的指标绝对变化、相对变化和主要维度贡献。",
        supported_goal_modes=["metric_diagnosis", "growth_trend", "periodic_report"],
        requirements=PlaybookRequirements(requires_date_column=True, requires_metric_columns=True),
        parameters=[
            _parameter("comparison_type", "对比方式", "choice", default="previous_period", choices=["previous_period", "custom"]),
            _parameter("current_start", "当前周期开始", "date"),
            _parameter("current_end", "当前周期结束", "date"),
            _parameter("previous_start", "对比周期开始", "date"),
            _parameter("previous_end", "对比周期结束", "date"),
            _parameter("top_n", "Top N", "integer", default=10),
            _parameter("aggregation", "聚合方式", "choice", default="sum", choices=["sum", "mean", "count", "min", "max"]),
        ],
        executor_name="execute_period_comparison",
        chart_types=["grouped_bar", "contribution_bar"],
        output_sections=["comparison", "change", "dimensions"],
        tags=["comparison", "period"],
    ),
    AnalysisPlaybook(
        playbook_id="dimension_contribution",
        display_name="维度贡献分析",
        description="按所选维度拆解指标，输出贡献值、贡献占比、排名及 Others。",
        supported_goal_modes=["metric_diagnosis", "content_performance", "live_quality", "periodic_report"],
        requirements=PlaybookRequirements(requires_metric_columns=True, requires_dimension_columns=True),
        parameters=[
            _parameter("metric", "指标", "column"),
            _parameter("dimension", "维度", "column"),
            _parameter("top_n", "Top N", "integer", default=10),
            _parameter("sort_order", "排序", "choice", default="descending", choices=["descending", "ascending"]),
            _parameter("include_others", "合并 Others", "boolean", default=True),
            _parameter("aggregation", "聚合方式", "choice", default="sum", choices=["sum", "mean", "count", "min", "max"]),
        ],
        executor_name="execute_dimension_contribution",
        chart_types=["contribution_bar", "table"],
        output_sections=["ranking", "contribution"],
        tags=["dimension", "attribution"],
    ),
    AnalysisPlaybook(
        playbook_id="experiment_comparison",
        display_name="实验组对照组比较",
        description="比较对照组与实验组的均值或比例，输出 lift、p-value 与置信区间。",
        supported_goal_modes=["experiment_analysis"],
        requirements=PlaybookRequirements(requires_group_column=True, requires_metric_columns=True, minimum_rows=4),
        parameters=[
            _parameter("control_value", "对照组值", "string", default="control"),
            _parameter("treatment_value", "实验组值", "string", default="treatment"),
            _parameter("metric", "指标", "column"),
            _parameter("metric_type", "指标类型", "choice", default="mean", choices=["mean", "proportion"]),
            _parameter("confidence_level", "置信水平", "float", default=0.95),
            _parameter("dimension", "分层维度", "column"),
        ],
        executor_name="execute_experiment_comparison",
        chart_types=["grouped_bar", "confidence_interval"],
        output_sections=["experiment", "significance", "confidence_interval"],
        tags=["experiment", "comparison"],
    ),
    AnalysisPlaybook(
        playbook_id="causal_exploration",
        display_name="轻量因果探索",
        description="输出 naive difference、回归调整结果和明确的适用边界。",
        supported_goal_modes=["causal_exploration"],
        requirements=PlaybookRequirements(requires_treatment_column=True, requires_outcome_column=True, minimum_rows=10),
        parameters=[
            _parameter("covariates", "控制变量", "dimension_columns", default=[]),
            _parameter("treatment_value", "处理组值", "string", default="treatment"),
            _parameter("control_value", "对照组值", "string", default="control"),
        ],
        executor_name="execute_causal_exploration",
        chart_types=["bar"],
        output_sections=["naive", "adjusted", "caveats"],
        tags=["causal", "exploration"],
    ),
    AnalysisPlaybook(
        playbook_id="periodic_summary",
        display_name="周期分析摘要",
        description="组合数据概览、趋势、周期变化和主要维度，生成一页式摘要。",
        supported_goal_modes=["periodic_report", "growth_trend", "metric_diagnosis"],
        requirements=PlaybookRequirements(requires_table=True),
        parameters=[
            _parameter("time_grain", "时间粒度", "choice", default="day", choices=["day", "week", "month"]),
            _parameter("aggregation", "聚合方式", "choice", default="sum", choices=["sum", "mean", "count", "min", "max"]),
            _parameter("rolling_window", "滚动窗口", "integer", default=7),
            _parameter("top_n", "Top N", "integer", default=5),
        ],
        executor_name="execute_periodic_summary",
        chart_types=["metric_card", "time_series", "contribution_bar"],
        output_sections=["profile", "trend", "comparison", "top_dimensions"],
        tags=["periodic", "summary"],
    ),
]


def get_builtin_playbooks() -> list[AnalysisPlaybook]:
    return list(BUILTIN_PLAYBOOKS)
