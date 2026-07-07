# InsightPilot Agent

InsightPilot Agent 是一个 synthetic-data-only 的分析自动化工作台，用于学习研究、数据分析自动化、业务分析工作流实践和 Agent 工程化实践。项目默认使用 deterministic rule-based workflow，把自然语言问题转成指标识别、分析计划、本地 SQL/Pandas 查询、异常检测、维度归因、A/B 实验分析、轻量调整分析、trace、reviewer 和 Markdown 报告。

所有 demo 数据均为 synthetic data，不接入真实外部业务数据，不需要 API key，也不依赖在线 LLM。分析结果只用于学习研究和工作流演示，不代表真实业务结论。

当前代码版本为 `0.2.0`。v0.1 是基础分析能力合并版；v0.2 是 Agent workflow、trace、reviewer 和 optional LangGraph integration 的工程化版本。未安装 LangGraph 时，项目会自动使用 rule-based fallback。

## 项目目标

- 用稳定规则实现自然语言问题到分析计划的转换。
- 用 DuckDB 和 pandas 在本地 synthetic data 上执行分析。
- 提供可复现的异常检测、维度归因、实验分析和轻量调整分析。
- 用 WorkflowState、AnalysisTrace 和 ReviewerResult 记录可复核过程。
- 提供命令行 demo、Streamlit 页面和 deterministic pytest 覆盖。
- 通过 GitHub Actions CI 在 Python 3.11 上运行 pytest。

## 核心能力

- Metric Dictionary：内置指标口径、公式、含义和所需字段。
- Analysis Planner：根据中文或英文关键词生成结构化分析计划。
- Analysis Goal Mode：支持 `auto` 自动识别或手动指定分析目标模式。
- WorkflowState：集中维护 workflow state、route_taken、caveats、errors 和 reviewer 摘要。
- workflow_backend：支持 `rule_based`、`langgraph`、`langgraph_unavailable_fallback`。
- SQL/Pandas Tools：注册 pandas DataFrame 到 DuckDB，并限制只读查询。
- Anomaly & Attribution：比较目标日期与前 7 日均值，按维度输出贡献度。
- A/B Experiment：支持均值类 t-test 和比例类 z-test fallback。
- Causal Light：提供探索性 regression adjustment 和简化 propensity score weighting。
- Agent Trace & Reviewer：记录 trace_id、created_at、route_taken、reviewer score、checks、issues 和 suggestions。

## 三个 Demo 场景

1. 交易转化异常分析：订单量、曝光、点击率、转化率、支付成功率和维度贡献度。
2. 内容消费与实验分析：完播率、观看时长、A/B 实验、p_value 和 confidence interval。
3. 体验质量分析：卡顿率、观看时长、互动率、设备、网络类型、地区和时段归因。

## 技术栈

- Python 3.10+
- pandas, numpy, duckdb
- scipy, statsmodels, scikit-learn
- streamlit, plotly
- pytest
- optional: langgraph，未安装时项目仍使用 rule-based fallback

## 版本语义

- v0.1：基础分析能力合并版，覆盖 synthetic demo data、metric dictionary、metric resolver、deterministic planner、DuckDB tools、profiling、anomaly detection、dimension attribution、A/B experiment analysis、basic markdown report、Streamlit basic demo 和 pytest coverage。
- v0.1.1：Analysis Goal Mode 与交互补丁，支持 `auto` 和用户手动选择。
- v0.2：Agent workflow、WorkflowState、route_taken、AnalysisTrace、ReviewerResult、workflow_backend、optional LangGraph fallback、Streamlit selector、CLI flag 和 GitHub Actions CI。

## Analysis Goal Mode

Streamlit 侧边栏和 CLI 都支持分析目标模式。默认值为 `auto`，系统会继续使用 deterministic keyword rules 自动识别；当用户手动选择目标模式时，Planner 和 Workflow 会优先尊重用户选择。

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

Windows PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction
.\.venv\Scripts\python.exe -m pytest
```

如果 PowerShell 不允许运行 `Activate.ps1`，可以直接使用 `.venv` 内的 Python：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 命令行运行方式

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis
.\.venv\Scripts\python.exe examples/run_demo.py --scenario content --goal-mode experiment_analysis
.\.venv\Scripts\python.exe examples/run_demo.py --scenario live --goal-mode live_quality
.\.venv\Scripts\python.exe examples/run_demo.py --scenario all
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis --use-langgraph
```

命令会把报告写入 `reports/` 目录。该目录中的生成报告不需要提交到仓库。

## Streamlit 运行方式

```powershell
.\.venv\Scripts\streamlit.exe run app/ui_streamlit.py
```

页面支持选择 demo 场景、Analysis Goal Mode、Workflow Backend、预览 synthetic data 表、查看 route_taken、Reviewer Score、Trace ID、Caveats、Trace JSON 和 Markdown Report。选择 Optional LangGraph 但未安装 LangGraph 时，页面不会崩溃，结果会显示 fallback backend。

## Optional LangGraph

默认 backend 是 `rule_based`。如果 CLI 使用 `--use-langgraph` 或 Streamlit 选择 Optional LangGraph：

- 已安装兼容 LangGraph 时，workflow_backend 为 `langgraph`。
- 未安装或 API 不兼容时，workflow_backend 为 `langgraph_unavailable_fallback`。
- `requirements.txt` 不包含 LangGraph。
- `requirements-langgraph.txt` 单独管理 optional dependency。

## GitHub Actions CI

仓库包含 `.github/workflows/ci.yml`：

- push 和 pull_request 时运行。
- 使用 Python 3.11。
- 安装 `requirements.txt`。
- 运行 `python -m pytest`。
- 不安装 `requirements-langgraph.txt`，用于验证 optional fallback 不依赖 LangGraph。

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
scenario=transaction intent=metric_drop_diagnosis goal_mode=metric_diagnosis goal_mode_source=user_selected workflow_backend=rule_based reviewer_status=PASS reviewer_score=100
report: reports\transaction_report.md
route_taken: resolve_metrics, create_plan, route_metric_diagnosis, run_anomaly, run_attribution, review, generate_report
```

## 限制说明

- 所有数据均为 synthetic data，不代表真实业务结论。
- 分析结果用于学习研究和工作流演示。
- 相关性不能直接解释为因果关系。
- rule-based planner 依赖关键词规则，复杂表达需要后续扩展。
- 轻量调整分析不替代严谨因果识别设计。
- Optional LangGraph 只负责 workflow 编排，不引入在线 LLM 或 API key。

## 后续计划

- v0.3：Streamlit visualization and report export polish。
- v0.4：metric dictionary expansion and SQL template hardening。
- 持续补充 synthetic 场景、goal_mode 同义词和 reviewer 检查覆盖。
