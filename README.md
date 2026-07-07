# InsightPilot Agent

InsightPilot Agent 是一个面向互联网业务数据场景的数据分析自动化工作台。项目使用 deterministic rule-based workflow，把自然语言问题转成指标识别、分析计划、SQL/Pandas 查询、异常检测、维度归因、A/B 实验分析、轻量调整分析、可视化和 Markdown 报告。

本项目仅用于学习研究、数据分析自动化、业务分析工作流实践和 Agent 工程化实践。所有 demo 数据均为 synthetic data，不接入真实外部业务数据，不需要 API key，也不依赖在线 LLM。

当前代码版本为 `0.1.0`，语义上表示 consolidated v0.1：基础分析能力合并版。代码中已经包含 workflow、trace、reviewer 等 v0.2 preview 能力，后续 v0.2 会围绕这些能力继续打磨。

## 项目目标

- 用稳定规则实现自然语言问题到分析计划的转换。
- 用 DuckDB 和 pandas 在本地 synthetic data 上执行分析。
- 提供可复现的异常检测、维度归因、实验分析和轻量调整分析。
- 输出 trace、reviewer 检查和 Markdown 报告，便于复核分析过程。
- 提供命令行 demo、Streamlit 页面和 deterministic pytest 覆盖。

## 核心能力

- Metric Dictionary：内置指标口径、公式、业务含义和所需字段。
- Analysis Planner：根据中文或英文关键词生成结构化分析计划。
- Analysis Goal Mode：支持自动识别或手动指定分析目标模式。
- SQL/Pandas Tools：注册 pandas DataFrame 到 DuckDB，并限制只读查询。
- Anomaly & Attribution：比较目标日期与前 7 日均值，按维度输出贡献度。
- A/B Experiment：支持均值类 t-test 和比例类 z-test fallback。
- Causal Light：提供探索性 regression adjustment 和简化 propensity score weighting。
- Agent Trace & Reviewer：记录问题、意图、指标、计划、查询、发现和检查结果。

## 三个 Demo 场景

1. 交易转化异常分析：订单量、曝光、点击率、转化率、支付成功率和维度贡献度。
2. 内容消费与实验分析：完播率、观看时长、A/B 实验、p-value 和 confidence interval。
3. 直播体验质量分析：卡顿率、观看时长、互动率、设备、网络类型、地区和时段归因。

## 技术栈

- Python 3.10+
- pandas, numpy, duckdb
- scipy, statsmodels, scikit-learn
- streamlit, plotly
- pytest
- optional: langgraph，未安装时项目仍使用 rule-based fallback

## 版本路线

- v0.1：基础分析能力合并版，覆盖 synthetic demo data、metric dictionary、metric resolver、deterministic planner、DuckDB tools、profiling、anomaly detection、dimension attribution、A/B experiment analysis、basic markdown report、Streamlit basic demo 和 pytest coverage。
- v0.1.1：补充 Analysis Goal Mode，让用户可以在自动识别之外手动指定分析目标。
- v0.2：聚焦 Agent workflow、analysis trace、reviewer 与 optional LangGraph integration；当前实现已包含这些能力的 preview，可作为后续打磨基础。

## 分析目标模式

Streamlit 侧边栏和 CLI 都支持分析目标模式。默认值为 `auto`，系统会继续使用关键词规则自动识别；当用户手动选择目标模式时，Planner 和 Workflow 会优先尊重用户选择。

可用枚举值：

- `auto`：自动识别
- `metric_diagnosis`：指标波动诊断
- `growth_trend`：增长/趋势分析
- `experiment_analysis`：A/B 实验评估
- `content_performance`：内容表现分析
- `live_quality`：体验质量分析
- `causal_exploration`：轻量因果探索
- `periodic_report`：周期性分析报告

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python examples/run_demo.py --scenario transaction
streamlit run app/ui_streamlit.py
pytest
```

## 命令行运行方式

```bash
python examples/run_demo.py --scenario transaction
python examples/run_demo.py --scenario content
python examples/run_demo.py --scenario live
python examples/run_demo.py --scenario all
python examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis
python examples/run_demo.py --scenario content --goal-mode experiment_analysis
python examples/run_demo.py --scenario live --goal-mode live_quality
```

命令会把报告写入 `reports/` 目录。该目录中的生成报告不需要提交到仓库。

## Streamlit 运行方式

```bash
streamlit run app/ui_streamlit.py
```

页面支持选择 demo 场景、选择分析目标模式、预览 synthetic data 表、运行示例问题、查看 Analysis Plan、Metrics、Findings、Reviewer Result、Trace JSON 和 Markdown Report。

## 项目结构

```text
app/
insightpilot/
  agents/
  analysis/
  data/
  metrics/
  planning/
  reports/
  tools/
  visualization/
examples/
docs/
tests/
```

## 示例输出

```text
[transaction] intent=metric_drop_diagnosis reviewer=PASS
- orders 当前值为 ...，相对前 7 日均值变化 ...
- 维度贡献排序显示 South City 是主要变化来源之一...
```

## 限制说明

- 所有数据均为 synthetic data，不代表真实业务结论。
- 分析结果用于学习研究和工作流演示。
- 相关性不能直接解释为因果关系。
- rule-based planner 依赖关键词规则，复杂表达需要后续扩展。
- 轻量调整分析不替代严谨因果识别设计。

## 后续计划

- 打磨 v0.2 preview 中的 workflow、trace 和 reviewer 检查项。
- 扩展指标字典、goal_mode 同义词和更多可解释 synthetic 场景。
- 加强 SQL template 管理和报告导出格式。
- 为 Streamlit 页面补充更多图表与筛选控件。
- 可选接入 LangGraph 编排，但必须保留 deterministic fallback。
