# 中文界面规范

## 目标

v0.6 默认界面面向中文分析流程，内部 schema 和枚举继续使用稳定英文键。

## 文案管理

- 通用文本集中维护在 `insightpilot/ui/i18n.py`。
- 枚举显示名集中维护在 `insightpilot/ui/formatters.py`。
- 专业术语帮助集中维护在 `insightpilot/ui/help_text.py`。
- 未知枚举返回原值，不因缺少翻译而崩溃。

## 展示规则

- 用户可见标签、按钮、警告、错误、空状态和表头使用中文。
- AnalysisPlan 先通过 presenter 转换，再由 renderer 展示。
- QueryPlan、JoinPlan 和 ReviewerResult 使用中文摘要，不改变源对象。
- JSON 只在开发者模式展示，并显式设置 `expanded=False`。
- 用户页面的指标通过 `format_metric_name()` 显示中文，开发者模式才附带英文 ID。
- 结果优先于分析方案、运行性能和评估中心。

## 字号与卡片

- 全局基础字号为 14px。
- 页面主标题为 26px，区块标题按 21px、18px 和 16px 递减。
- `.ip-summary-title` 使用 12pt、600 字重和 1.4 行高。
- `.ip-summary-content` 使用 10.5pt、400 字重和 1.55 行高。
- 分析目标、主要指标、对比方式和分析维度使用 2×2 紧凑卡片，不使用大字号 `st.metric`。
- 风险与限制在简洁演示模式显示数量摘要，并默认折叠详情。

## 内部兼容

CLI JSON、RunManifest、QueryPlan 和 WorkflowState 的键不翻译。报告可以使用中文标题，但机器读取的 schema 保持英文。

## 检查

运行 `tests/test_chinese_labels.py`、`tests/test_ui_formatters.py` 和三个 Streamlit AppTest，确认中文标签和模式边界。
