# InsightPilot Agent

## 1. 项目简介

InsightPilot Agent 是一个 synthetic-data-first 的本地数据分析自动化工作台。它支持内置 demo 数据、CSV / Excel 上传、只读数据库查询，并把自然语言问题转成可复核的本地分析流程。

项目默认使用 deterministic rule-based workflow，不接入在线 LLM，不要求 API key。它适用于学习研究、数据分析自动化、业务分析工作流实践和 Agent 工程化实践。

当前版本为 `0.4.0`，主题是 Usability, Metric Mapping UI and Documentation Polish。v0.4 在 v0.3 数据接入能力之上，增加 Metric / Column Mapping，用于手动指定日期列、指标列、维度列、实验分组列、处理变量和结果变量。

## 2. 项目目标

InsightPilot Agent 试图解决的问题是：如何把自然语言业务问题转换为可复盘、可测试、可解释的本地数据分析流程。

项目将数据读取、schema profiling、指标识别、分析计划、统计检验、归因分析、reviewer 检查和报告输出串成闭环。它强调本地可运行、deterministic、可复现和易于扩展。

在不接入真实外部服务的前提下，项目展示了一个数据分析 Agent 的工程化结构：从数据源进入，到 workflow state，再到 trace、reviewer 和 report。

## 3. 核心能力

- Synthetic demo data：内置三类可解释 synthetic 场景。
- CSV / Excel upload：支持 CSV、xlsx、xlsm、xls，Excel 可选择 sheet。
- Database query ingestion：支持 SQLite 和 SQLAlchemy URL，只允许只读 SELECT/WITH。
- Schema mapping and validation：识别日期列、数值列、维度列、候选指标列和 warnings。
- Metric / Column Mapping：手动选择 date、metric、dimension、group、treatment、outcome。
- Metric dictionary and resolver：维护指标定义、公式和关键词解析规则。
- Analysis Goal Mode：支持 auto 和手动目标模式。
- WorkflowState / route_taken：记录 workflow 的中心状态和节点路径。
- AnalysisTrace：记录 trace_id、created_at、backend、数据源、字段映射和错误。
- ReviewerResult with score：输出 status、score、checks、issues、suggestions。
- DuckDB tools：本地只读 SQL 查询和表注册。
- Anomaly detection：比较目标日期与前 7 日均值。
- Dimension attribution：按维度拆解变化贡献。
- A/B experiment analysis：输出 sample_size、p_value 和区间估计。
- Lightweight causal exploration：提供探索性调整分析。
- Markdown report：生成结构化分析报告。
- Streamlit UI：提供本地交互工作台。
- CLI demo：支持 synthetic、file、database 三种入口。
- GitHub Actions CI：Python 3.11 + pytest。

## 4. 项目组成部分

| 目录 | 职责 |
| --- | --- |
| `app/` | Streamlit 本地交互 UI。 |
| `examples/` | CLI demo 和本地运行入口。 |
| `insightpilot/data/` | synthetic demo data 生成。 |
| `insightpilot/ingestion/` | CSV/Excel/database 读取、字段映射、表注册和校验。 |
| `insightpilot/metrics/` | 指标字典和指标解析。 |
| `insightpilot/planning/` | deterministic planner 和 Analysis Goal Mode。 |
| `insightpilot/tools/` | DuckDB、本地 profiling 等工具。 |
| `insightpilot/analysis/` | 异常检测、归因、实验分析和轻量因果探索。 |
| `insightpilot/agents/` | WorkflowState、workflow、trace、reviewer 和 optional LangGraph fallback。 |
| `insightpilot/reports/` | Markdown report 和报告写出工具。 |
| `insightpilot/visualization/` | Plotly 图表辅助函数。 |
| `docs/` | 项目路线、demo、数据接入和字段映射文档。 |
| `tests/` | pytest 覆盖。 |
| `.github/workflows/` | GitHub Actions CI。 |

## 5. 工作流概览

```text
Data Source
  -> TableRegistry
  -> Schema Mapping / Validation
  -> Metric / Column Mapping
  -> Metric Resolver
  -> Planner
  -> Workflow Router
  -> Analysis Tools
  -> Reviewer
  -> Trace
  -> Markdown Report / Streamlit UI
```

Data Source 可以是 synthetic demo data、上传文件或数据库查询结果。TableRegistry 将表和 metadata 放入内存。Schema Mapping / Validation 给出字段候选和 warnings。Metric / Column Mapping 允许用户手动覆盖自动推断。Planner 根据问题和 goal_mode 生成计划。Workflow Router 根据 intent 和 goal_mode 选择分析路径。Analysis Tools 执行异常、归因、实验或通用 fallback。Reviewer 检查质量和边界。Trace 和 Report 输出可复核记录。

## 6. 数据来源

### Synthetic demo data

默认数据源是 synthetic demo data。它用于稳定演示和测试，不代表真实业务结论。

### Upload CSV / Excel

Streamlit 支持上传 CSV、xlsx、xlsm 和 xls。Excel 支持选择 sheet。上传文件默认只在当前会话内存中读取，项目不保存文件。Streamlit file upload 的大小限制由 Streamlit 运行配置控制，项目本身不承诺无限大小。

### Database query

Database query 通过 SQLAlchemy 和 pandas 读取查询结果。SQLite 可直接使用；其他数据库需要用户自行安装对应驱动。查询只允许 SELECT / WITH，并会阻断写操作和多语句。

## 7. Analysis Goal Mode

Analysis Goal Mode 是 workflow routing signal。默认值为 `auto`，系统使用 deterministic keyword rules 自动识别；如果用户手动选择目标模式，则手动选择优先。

- `auto`
- `metric_diagnosis`
- `growth_trend`
- `experiment_analysis`
- `content_performance`
- `live_quality`
- `causal_exploration`
- `periodic_report`

在 synthetic demo data 下，workflow 会优先走对应的专用分析路径。在 uploaded_files 或 database 下，workflow 会优先使用 Column Mapping；如果映射不完整，则进入 generic analysis fallback 并输出 caveat。

## 8. Metric / Column Mapping

v0.4 增加 Metric / Column Mapping。上传自定义数据或读取数据库查询结果后，用户可以手动指定：

- `date_column`
- `metric_columns`
- `dimension_columns`
- `group_column`
- `treatment_column`
- `outcome_column`
- `time_grain`

手动 mapping 优先于自动 schema 推断。mapping 会写入 WorkflowState、AnalysisTrace、ReviewerResult 和 Markdown Report。如果 mapping 不完整，系统会 fallback 到 generic analysis，并说明需要补充哪些字段。

## 9. 快速开始

```powershell
cd "C:\Users\1330718\Documents\insightpilot-agent"
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

如果已经存在 `.venv`，可以直接安装依赖并运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

## 10. CLI 示例

Synthetic：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis
```

CSV：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.csv --table-name uploaded_table --goal-mode growth_trend
```

Excel：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.xlsx --sheet-name Sheet1 --table-name uploaded_table --goal-mode growth_trend
```

SQLite：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source database --database-url sqlite:///local.db --query "SELECT * FROM metrics" --table-name db_table --goal-mode growth_trend
```

带字段映射的 CSV：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --data-source file --input-file data/sample.csv --table-name uploaded_table --goal-mode growth_trend --date-column date --metric-columns revenue,orders --dimension-columns city,channel
```

## 11. Streamlit 使用方式

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/ui_streamlit.py
```

页面区域包括：

- Data Source
- Demo Scenario
- Upload CSV / Excel
- Database query
- Analysis Goal Mode
- Workflow Backend
- Metric / Column Mapping
- Run Analysis
- Findings
- Reviewer
- Trace
- Report

在 Upload CSV / Excel 和 Database query 模式下，用户可以选择表、查看自动建议 mapping，并手动选择 date、metric、dimension、group、treatment、outcome 和 time grain。

## 12. 数据安全边界

- 不提交真实数据。
- 不提交上传文件。
- 不提交数据库查询结果。
- 不提交 database URL、密码、token 或 cookie。
- 不提交 `.streamlit/secrets.toml`。
- 数据默认在内存中处理。
- SQL 只读检查是保守字符串检查，不是完整 SQL parser。
- 自定义数据分析结果不应被描述为真实业务结论。

## 13. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖：

- synthetic data
- planner
- workflow routing
- trace
- reviewer
- ingestion
- column mapping
- SQL safety
- CLI
- Streamlit import
- formatting checks

## 14. 版本路线

- v0.1：基础分析能力合并版。
- v0.2：Agent workflow、trace、reviewer、optional LangGraph fallback 和 CI。
- v0.3：CSV / Excel / database ingestion、schema profiling、custom data workflow。
- v0.4：Metric Mapping UI、custom data usability、documentation polish、format normalization。
- next：metric mapping UI 继续打磨、user-selected SQL templates、report export polish。

## 15. 限制说明

- 当前不接入在线 LLM。
- 当前不做生产级数据库权限管理。
- 当前不保存用户上传数据。
- 自定义数据分析依赖字段 mapping 和数据质量。
- 轻量因果分析仅用于探索性分析。
- optional LangGraph 只做 workflow 编排，不改变 no API key 边界。

## 16. License / Notes

No license file has been added yet.
