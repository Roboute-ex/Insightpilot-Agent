"""Chinese examples with executable, explicit field and playbook selections."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from insightpilot.config import SYNTHETIC_END_DATE


@dataclass(frozen=True)
class ExampleQuestion:
    question_id: str
    scenario: str
    category: str
    question_zh: str
    recommended_goal_mode: str
    recommended_playbook: str | None
    required_fields: tuple[str, ...]
    explanation: str
    difficulty: str = "基础"
    common: bool = False
    table_name: str = ""
    metric_columns: tuple[str, ...] = ()
    dimension_columns: tuple[str, ...] = ()
    aggregation: str = "sum"
    parameter_overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.question_id

    @property
    def selection_config(self) -> dict[str, Any]:
        experiment = self.table_name == "experiments"
        parameters: dict[str, Any] = {}
        if self.recommended_playbook in {"metric_trend", "period_comparison", "dimension_contribution", "periodic_summary"}:
            parameters["aggregation"] = self.aggregation
        if self.recommended_playbook in {"dimension_contribution", "experiment_comparison"}:
            parameters["metric"] = self.metric_columns[0]
            if self.dimension_columns:
                parameters["dimension"] = self.dimension_columns[0]
        covariates = ["historical_activity", "historical_revenue", "city", "channel", "user_segment"] if experiment else []
        if self.recommended_playbook == "causal_exploration":
            parameters["covariates"] = covariates
        if self.question_id == "tx02":
            end = pd.Timestamp(SYNTHETIC_END_DATE)
            parameters["date_range"] = [str((end - pd.Timedelta(days=29)).date()), str(end.date())]
        if self.question_id == "tx11":
            end = pd.Timestamp(SYNTHETIC_END_DATE)
            parameters.update({"current_start": str((end - pd.Timedelta(days=6)).date()), "current_end": str(end.date()), "previous_start": str((end - pd.Timedelta(days=13)).date()), "previous_end": str((end - pd.Timedelta(days=7)).date())})
        parameters.update(deepcopy(self.parameter_overrides))
        return {
            "question": self.question_zh, "goal_mode": self.recommended_goal_mode,
            "playbook_id": self.recommended_playbook,
            "column_mapping": {
                "table_name": self.table_name, "date_column": "date",
                "metric_columns": list(self.metric_columns), "dimension_columns": list(self.dimension_columns),
                "group_column": "group" if experiment else None,
                "treatment_column": "group" if experiment else None,
                "outcome_column": self.metric_columns[0] if self.metric_columns else None,
                "covariates": covariates, "aggregation": self.aggregation, "time_grain": "day",
            },
            "parameters": parameters,
        }

    def apply_settings(self) -> dict[str, Any]:
        return deepcopy(self.selection_config)


def _question(identifier: str, scenario: str, category: str, text: str, goal: str, playbook: str | None,
              table: str, metric: str | tuple[str, ...], dimension: str | tuple[str, ...], explanation: str, *, aggregation: str = "sum",
              common: bool = False, parameters: dict[str, Any] | None = None) -> ExampleQuestion:
    metrics = (metric,) if isinstance(metric, str) else metric
    dimensions = ((dimension,) if dimension else ()) if isinstance(dimension, str) else dimension
    fields = ("date", *metrics, *dimensions)
    if table == "experiments":
        fields += ("user_id", "group")
    return ExampleQuestion(identifier, scenario, category, text, goal, playbook, fields, explanation,
        "进阶" if playbook in {"causal_exploration", "experiment_comparison"} else "基础", common,
        table, metrics, dimensions, aggregation, parameters or {})


QUESTIONS: tuple[ExampleQuestion, ...] = (
    _question("tx01", "transaction", "异常诊断", "昨日订单量为什么下降？", "metric_diagnosis", None, "daily_metrics", "orders", "city", "昨日按数据参考日解释，检查前7日/28日和上周同日。", common=True),
    _question("tx02", "transaction", "趋势与周期", "近一个月收入趋势如何？", "growth_trend", "metric_trend", "daily_metrics", "revenue", "channel", "金额求和；滚动窗口为7个日期。", common=True),
    _question("tx03", "transaction", "维度贡献", "各城市分别贡献了多少订单量？", "metric_diagnosis", "dimension_contribution", "daily_metrics", "orders", "city", "按城市展示整个观察期订单构成；日期下降归因见异常诊断。", common=True),
    _question("tx04", "transaction", "维度贡献", "各渠道贡献了多少访问量？", "metric_diagnosis", "dimension_contribution", "daily_metrics", "visitors", "channel", "访问为转化旅程数量，不能当全站UV。", common=True),
    _question("tx05", "transaction", "异常诊断", "Android 6.2 版本支付成功率是否异常？", "metric_diagnosis", None, "daily_metrics", "payment_success_rate", "app_version", "先看支付尝试加权成功率，再看设备与版本交叉贡献。", aggregation="mean", common=True),
    _question("tx06", "transaction", "客群分析", "新老客的订单量构成有何差异？", "metric_diagnosis", "dimension_contribution", "daily_metrics", "orders", "customer_type", "按新老客拆分订单计数。", common=True),
    _question("tx07", "transaction", "退款与价值", "每日退款订单数量是否持续增加？", "growth_trend", "metric_trend", "daily_metrics", "refund_orders", "city", "退款数从逐订单退款标记汇总。"),
    _question("tx08", "transaction", "趋势与周期", "生成本周期交易表现摘要。", "periodic_report", "periodic_summary", "daily_metrics", "orders", "channel", "组合趋势、周期比较和渠道构成。"),
    _question("tx09", "transaction", "维度贡献", "哪类商户贡献了更多收入？", "metric_diagnosis", "dimension_contribution", "daily_metrics", "revenue", "merchant_type", "以支付订单金额求和。"),
    _question("tx10", "transaction", "退款与价值", "各支付方式的订单客单价是多少？", "periodic_report", "dimension_contribution", "transaction_detail", "revenue", "payment_method", "逐订单金额均值等于总收入/总订单数。", aggregation="mean"),
    _question("tx11", "transaction", "趋势与周期", "本周订单量与前一周相比如何？", "periodic_report", "period_comparison", "daily_metrics", "orders", "city", "比较两个不重叠的七天窗口。"),
    _question("tx12", "transaction", "维度贡献", "各时段交易收入分别是多少？", "metric_diagnosis", "dimension_contribution", "daily_metrics", "revenue", "hour_bucket", "按时段汇总订单金额。"),
    _question("tx13", "transaction", "客群分析", "不同活动的新客订单构成如何？", "metric_diagnosis", "dimension_contribution", "daily_metrics", "orders", "campaign_customer_type", "活动与新老客组合维度；显示全部组供对比。"),
    _question("tx14", "transaction", "退款与价值", "各城市订单退款率是多少？", "periodic_report", "dimension_contribution", "transaction_detail", "refund_rate", "city", "每行一单，退款标记均值就是订单退款率。", aggregation="mean"),
    _question("tx15", "transaction", "数据质量", "交易明细是否存在缺失字段或重复订单？", "periodic_report", "data_profile", "transaction_detail", "revenue", "city", "概览检查缺失和整行重复；主键唯一性另由数据契约验证。"),
    _question("ct01", "content", "内容消费", "不同内容分类的完播率如何？", "content_performance", "dimension_contribution", "content_events", "completion_rate", "content_category", "一行一次播放，二元完播标记均值为播放完播率。", aggregation="mean", common=True),
    _question("ct02", "content", "实验效果", "新策略是否提升了内容完播率？", "experiment_analysis", "experiment_comparison", "experiments", "completion_rate", "", "用户随机分组，以用户为独立样本比较总体观测完播比例；分层另选ct09。", aggregation="mean", common=True),
    _question("ct03", "content", "内容消费", "不同作者层级的平均观看时长有何差异？", "content_performance", "dimension_contribution", "content_events", "watch_time", "author_tier", "逐播放观看秒数的均值。", aggregation="mean", common=True),
    _question("ct04", "content", "内容消费", "哪个发布时段的完播率更高？", "content_performance", "dimension_contribution", "content_events", "completion_rate", "publish_hour", "发布时段差异是描述性关联，不证明发布时间的因果效果。", aggregation="mean", common=True),
    _question("ct05", "content", "互动与传播", "内容互动率随日期如何变化？", "growth_trend", "metric_trend", "content_events", "interaction_rate", "content_category", "每次播放是否发生至少一种互动；按播放数加权。", aggregation="mean", common=True),
    _question("ct06", "content", "内容消费", "长内容在不同设备上的完播率有何差异？", "content_performance", "dimension_contribution", "content_events", "completion_rate", "length_device", "使用内容长度与设备组合维度，保留短内容对照组。", aggregation="mean", common=True),
    _question("ct07", "content", "互动与传播", "哪类内容获得了最多点赞？", "content_performance", "dimension_contribution", "content_events", "likes", "content_category", "点赞为逐播放二元事件，按分类求和。"),
    _question("ct08", "content", "互动与传播", "不同内容形式的分享量有什么差异？", "content_performance", "dimension_contribution", "content_events", "shares", "content_format", "展示分享事件数量。"),
    _question("ct09", "content", "实验效果", "实验对不同用户分层的完播效果是否一致？", "experiment_analysis", "experiment_comparison", "experiments", "completion_rate", "user_segment", "总体和用户分层检验，分层结果作为探索并保留多重比较限制。", aggregation="mean"),
    _question("ct10", "content", "实验效果", "控制用户历史活跃度后，策略与完播率的关联如何？", "causal_exploration", "causal_exploration", "experiments", "completion_rate", "user_segment", "比较朴素差与调整差；不扩大为普遍因果结论。", aggregation="mean"),
    _question("ct11", "content", "趋势与周期", "汇总近期内容观看时长表现。", "periodic_report", "periodic_summary", "content_events", "watch_time", "content_category", "按播放观测汇总平均观看时长及分类差异。", aggregation="mean"),
    _question("ct12", "content", "数据质量", "内容数据的缺失、类型和分布是否正常？", "periodic_report", "data_profile", "content_events", "watch_time", "content_category", "检查观测数据质量，不把模拟结果当真实运营结果。"),
    _question("lv01", "live", "体验异常", "请定位直播卡顿异常的主要维度。", "live_quality", None, "live_sessions", "buffering_rate", "device_network", "固定600秒观测窗；按设备和网络交叉查看最近三天。", aggregation="mean", common=True),
    _question("lv02", "live", "体验异常", "平板与移动网络组合的卡顿率有何差异？", "live_quality", "dimension_contribution", "live_sessions", "buffering_rate", "device_network", "组合维度保留其他设备网络作为对照。", aggregation="mean", common=True),
    _question("lv03", "live", "体验异常", "哪个版本的直播崩溃率更高？", "live_quality", "dimension_contribution", "live_sessions", "crash_rate", "app_version", "崩溃标记按独立会话取均值。", aggregation="mean", common=True),
    _question("lv04", "live", "体验异常", "不同网络的启动延迟是多少？", "live_quality", "dimension_contribution", "live_sessions", "startup_latency", "network_type", "单位毫秒，逐会话平均。", aggregation="mean", common=True),
    _question("lv05", "live", "观看与转化", "直播平均观看时长最近是否下降？", "growth_trend", "metric_trend", "live_sessions", "watch_time", "device", "单位秒，按会话平均；不以预览样本计算。", aggregation="mean", common=True),
    _question("lv06", "live", "观看与转化", "设备网络体验与观看转化存在怎样的关联？", "live_quality", None, "live_daily_metrics", ("stutter_rate", "conversion_rate"), ("device", "network_type"), "按唯一观看会话配对卡顿率与转化，展示Pearson相关及设备网络分组；重复用户会话不当独立用户检验，相关不代表因果。", aggregation="mean", common=True),
    _question("lv07", "live", "观看与转化", "各直播类别的互动率有什么差异？", "live_quality", "dimension_contribution", "live_sessions", "interaction_rate", "live_category", "每会话至少一次互动的比例。", aggregation="mean"),
    _question("lv08", "live", "体验异常", "不同运营商的平均卡顿率是多少？", "live_quality", "dimension_contribution", "live_sessions", "buffering_rate", "carrier", "各会话等长观测窗，均值与总卡顿时长/总观测时长相等。", aggregation="mean"),
    _question("lv09", "live", "观看与转化", "不同主播层级的平均观看时长如何？", "live_quality", "dimension_contribution", "live_sessions", "watch_time", "host_tier", "会话粒度统计，不能冒充独立主播级效果。", aggregation="mean"),
    _question("lv10", "live", "观看与转化", "各时段有多少直播观看会话？", "periodic_report", "dimension_contribution", "live_sessions", "sessions", "hour_bucket", "每行一个观众观看会话，不等同主播开播数量。"),
    _question("lv11", "live", "趋势与周期", "生成本期直播体验质量摘要。", "periodic_report", "periodic_summary", "live_sessions", "buffering_rate", "device_network", "组合会话卡顿趋势和设备网络构成。", aggregation="mean"),
    _question("lv12", "live", "数据质量", "直播会话数据是否存在缺失或重复？", "periodic_report", "data_profile", "live_sessions", "watch_time", "device", "检查会话观测完整性。"),
)


def get_example_questions(scenario: str | None = None, common_only: bool = False) -> list[ExampleQuestion]:
    return [item for item in QUESTIONS if (scenario is None or item.scenario == scenario) and (not common_only or item.common)]


def get_question_categories(scenario: str, common_only: bool = False) -> list[str]:
    return list(dict.fromkeys(item.category for item in get_example_questions(scenario, common_only)))


def get_example_question(question_id: str) -> ExampleQuestion:
    for item in QUESTIONS:
        if item.question_id == question_id:
            return item
    raise KeyError(f"未找到示例问题：{question_id}")
