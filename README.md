# InsightPilot Agent

InsightPilot Agent 是 synthetic-data-first 的本地分析自动化工作台，用于学习研究、数据分析自动化、业务分析工作流实践和 Agent 工程化实践。项目默认使用 deterministic rule-based workflow，不接入在线 LLM，不要求 API key。

当前版本为 `0.3.0`：Data Ingestion and External Data Connectors。v0.1 是基础分析能力合并版；v0.2 聚焦 Agent workflow、trace、reviewer、optional LangGraph fallback 和 CI；v0.3 增加 CSV / Excel upload、database query ingestion、schema profiling 和 custom data workflow。

## 核心能力

- Synthetic demo data：继续作为默认数据源，三个 demo 场景保持可用。
- CSV / Excel upload：支持 CSV、xlsx、xlsm、xls，Excel 可选择 sheet。
- Database query ingestion：支持 SQLite 和 SQLAlchemy URL，只允许只读 SELECT/WITH 查询。
- Schema mapping：自动识别日期列、数值列、维度列、候选指标列和 warnings。
- TableRegistry：统一管理内存表、metadata 和 DuckDB 可注册表。
- Generic analysis fallback：自定义数据缺少 demo 表结构时，自动退化为通用 profile、趋势或限制说明。
- WorkflowState / AnalysisTrace / ReviewerResult：记录 data_source_type、table_metadata、schema_warnings、route_taken、reviewer score。

## 数据安全边界

- 不要提交真实数据、上传文件、数据库查询结果或本地数据库文件。
- 不要提交 database URL、账号、密码、token、cookie 或 `.streamlit/secrets.toml`。
- 上传文件和数据库查询结果默认只在当前会话内存中处理，不写入仓库。
- Database query 仅允许单条 SELECT/WITH，禁止写操作 SQL。
- 报告中只展示 masked database URL 或 source_name，不展示明文密码。
- 自定义数据分析结果不应被描述为真实业务结论。

## 快速开始

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

## CLI 示例

Synthetic：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis
.\.venv\Scripts\python.exe examples/run_demo.py --scenario content --goal-mode experiment_analysis
.\.venv\Scripts\python.exe examples/run_demo.py --scenario live --goal-mode live_quality
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

Optional LangGraph：

```powershell
.\.venv\Scripts\python.exe examples/run_demo.py --scenario transaction --goal-mode metric_diagnosis --use-langgraph
```

## Streamlit

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/ui_streamlit.py
```

页面支持三种 Data Source：

- Synthetic demo data：选择 demo 场景、goal_mode 和 workflow backend。
- Upload CSV / Excel：上传多个文件，选择 Excel sheet，编辑 table name，查看 preview、schema mapping 和 warnings。
- Database query：输入 SQLAlchemy URL 和只读 SQL，加载 SQLite 或其他已安装驱动支持的数据源。

## Database Connector

- SQLite 可直接使用：`sqlite:///path/to/local.db`。
- 其他 SQLAlchemy URL 需要用户自行安装对应数据库驱动。
- README、报告和日志不鼓励保存真实连接信息。
- SQL safety 会拒绝 DROP、DELETE、INSERT、UPDATE、ALTER、CREATE、TRUNCATE、MERGE、REPLACE、GRANT、REVOKE、ATTACH、DETACH、COPY 等写操作。

## Analysis Goal Mode

默认 `goal_mode=auto`，系统使用 deterministic keyword rules 自动识别；用户手动选择时优先于自动识别。

可用枚举值：

- `auto`
- `metric_diagnosis`
- `growth_trend`
- `experiment_analysis`
- `content_performance`
- `live_quality`
- `causal_exploration`
- `periodic_report`

## CI

`.github/workflows/ci.yml` 使用 Python 3.11，安装 `requirements.txt` 并运行 `python -m pytest`。CI 不安装 `requirements-langgraph.txt`，继续验证 optional LangGraph fallback。

## 限制说明

- synthetic demo data 仍是默认安全演示路径。
- 自定义数据通用分析依赖字段名和 dtype 推断，复杂口径需要后续手动映射 UI。
- v0.3 不保存上传文件或数据库查询结果。
- 轻量因果探索不替代严谨识别设计。

## 后续计划

- v0.4：metric mapping UI、user-selected date/metric/dimension columns、SQL template hardening、report export polish。
