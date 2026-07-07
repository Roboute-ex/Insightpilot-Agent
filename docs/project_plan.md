# InsightPilot Agent 项目路线图

当前代码版本为 `0.3.0`。路线图保持工程记录和学习实践口吻；所有能力继续遵守 no online LLM、no API key、no committed real data 的边界。

## v0.1：基础分析能力合并版

- synthetic demo data
- metric dictionary
- metric resolver
- deterministic analysis planner
- DuckDB analysis tools
- profiling tools
- anomaly detection
- dimension attribution
- A/B experiment analysis
- basic markdown report
- Streamlit basic demo
- pytest coverage

## v0.2：Agent Workflow, Trace and Reviewer Hardening

- WorkflowState 作为中心 workflow state。
- route_taken 写入 workflow state、trace、report、CLI 和 Streamlit。
- workflow_backend 支持 rule_based、langgraph、langgraph_unavailable_fallback。
- optional LangGraph workflow 未安装或 API 不兼容时自动 fallback。
- AnalysisTrace 增强 trace_id、created_at、workflow_backend、route_taken、caveats 和 errors。
- ReviewerResult 增强 status、score、checks、issues 和 suggestions。
- CLI 增加 --use-langgraph。
- Streamlit 增加 Workflow Backend selector。
- GitHub Actions CI 使用 Python 3.11 和 pytest。

## v0.3：当前完成目标

目标名称：Data Ingestion and External Data Connectors

范围：

- 保留 synthetic demo data 作为默认数据源。
- 增加 CSV upload。
- 增加 Excel upload，支持 xlsx、xlsm、xls 和 sheet 选择。
- 增加 SQLite / SQLAlchemy read-only database query ingestion。
- 增加 schema mapping、validation 和 TableRegistry。
- WorkflowState、AnalysisTrace、ReviewerResult 和 report 增加 data_source_type、table_metadata、schema_warnings。
- 自定义数据缺少 demo 表结构时，使用 generic analysis fallback。
- CLI 增加 --data-source、--input-file、--sheet-name、--table-name、--database-url、--query。
- Streamlit 增加 Data Source selector、upload 模式和 database query 模式。

说明：

- 上传文件和数据库查询结果默认只在当前会话内存中处理。
- database query 只允许 SELECT/WITH。
- 自定义数据结果必须明确字段推断和限制说明。

## v0.4：建议方向

- metric mapping UI。
- user-selected date/metric/dimension columns。
- SQL template hardening。
- report export polish。
- 更清晰的 custom data workflow trace 可视化。
