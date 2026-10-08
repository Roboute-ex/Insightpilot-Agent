"""Default charts built from computed legacy result tables, without rereading input."""
from __future__ import annotations

from typing import Any
from copy import deepcopy
import pandas as pd

from insightpilot.visualization.factory import build_charts
from insightpilot.visualization.specs import ChartSpec


def build_result_chart_specs(result_tables: dict[str, pd.DataFrame]) -> list[ChartSpec]:
    specs: list[ChartSpec] = []
    comparisons = result_tables.get('metric_comparisons')
    if isinstance(comparisons, pd.DataFrame) and not comparisons.empty:
        # Each metric gets its own chart so counts, currency and rates never share one axis.
        if {'metric_id', 'current_period', 'baseline_period', 'current_value', 'baseline_value'}.issubset(comparisons.columns):
            for index, metric in enumerate(comparisons['metric_id'].dropna().drop_duplicates().head(6)):
                spec = ChartSpec(f'actual_metric_{index}', 'grouped_bar', f'{metric}：当前与基准', 'metric_comparisons', x='baseline_period', y=['current_value', 'baseline_value'], description='各对比窗口的当前值与基准值，数值直接来自指标对比结果。', metadata={'metric_filter': str(metric)})
                specs.append(spec)
    funnel = result_tables.get('funnel_decomposition')
    if isinstance(funnel, pd.DataFrame) and {'stage_name', 'current_count', 'baseline_count'}.issubset(funnel.columns) and not funnel.empty:
        specs.append(ChartSpec('actual_funnel', 'grouped_bar', '漏斗各阶段当前与基准', 'funnel_decomposition', x='stage_name', y=['current_count', 'baseline_count'], description='按原始阶段顺序展示。因阶段统计单位可能不同，不以百分比图暗示同一实体转化。'))
    contributions = result_tables.get('dimension_contributions')
    if isinstance(contributions, pd.DataFrame) and {'dimension', 'dimension_value', 'contribution_value'}.issubset(contributions.columns) and not contributions.empty:
        # Comparison is within one dimension; do not add independent dimensions together.
        dimension = 'city' if 'city' in set(contributions['dimension']) else str(contributions['dimension'].iloc[0])
        specs.append(ChartSpec('actual_contribution', 'contribution_bar', f'{dimension}维度变化', 'dimension_contributions', x='dimension_value', y=['contribution_value'], top_n=15, sort='ascending', metadata={'dimension_filter': dimension}, description='只比较同一维度内的有符号变化，维度之间不能相加。'))
    experiments = result_tables.get('experiment_comparison')
    if isinstance(experiments, pd.DataFrame) and {'metric_name', 'absolute_lift', 'confidence_interval_lower', 'confidence_interval_upper'}.issubset(experiments.columns) and not experiments.empty:
        specs.append(ChartSpec('actual_experiment', 'confidence_interval', '实验组减对照组：绝对差及置信区间', 'experiment_comparison', x='metric_name', y=['absolute_lift'], description='概率指标纵轴使用0至1比例单位；UI和报告文本转换为百分点。'))
    return specs


def build_result_charts(result_tables: dict[str, pd.DataFrame]) -> list[tuple[ChartSpec, Any]]:
    return build_charts(build_result_chart_specs(result_tables), result_tables)


class MaterializedCharts(list[tuple[ChartSpec, Any]]):
    """Backward-compatible chart pairs with explicit warnings for skipped specs."""
    def __init__(self, charts, warnings: tuple[str, ...] = ()):
        super().__init__(charts)
        self._warnings = warnings

    @property
    def warnings(self) -> tuple[str, ...]:
        return self._warnings


def materialize_charts(result: dict[str, Any], spec_ids: list[str] | None = None, max_points: int | None = None) -> MaterializedCharts:
    """Build requested charts read-only; inspect .warnings even when no pairs exist."""
    from insightpilot.performance import PerformanceConfig
    from insightpilot.observability.tracer import trace_stage
    config=PerformanceConfig.from_environment()
    budget=config.chart_max_points if max_points is None else int(max_points)
    if budget < 10:
        raise ValueError('图表点数预算至少为10。')
    selected=set(spec_ids) if spec_ids is not None else None
    specs=[]
    for raw in result.get('chart_specs',[]):
        spec=ChartSpec.from_dict(deepcopy(raw.to_dict() if isinstance(raw,ChartSpec) else raw))
        if selected is not None and spec.chart_id not in selected:
            continue
        spec.metadata['point_budget']=budget
        spec.metadata['series_budget']=config.chart_max_series
        specs.append(spec)
    with trace_stage('chart_materialization', chart_count=len(specs), point_budget=budget):
        charts=build_charts(specs,result.get('result_tables',{}))
    warnings=tuple(f'{spec.chart_id}：{spec.metadata["warning"]}' for spec in specs if spec.metadata.get('warning'))
    return MaterializedCharts(charts,warnings)
