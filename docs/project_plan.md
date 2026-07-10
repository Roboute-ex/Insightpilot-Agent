# InsightPilot Agent 项目路线图

当前代码版本为 `0.5.0`。路线图保持工程记录和学习实践口吻；所有能力继续遵守 no online LLM、no API key、no committed real data 的边界。

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
- GitHub Actions CI 使用 Python 3.11 和 pytest。

## v0.3：Data Ingestion and External Data Connectors

- 保留 synthetic demo data 作为默认数据源。
- 增加 CSV upload。
- 增加 Excel upload，支持 xlsx、xlsm、xls 和 sheet 选择。
- 增加 SQLite / SQLAlchemy read-only database query ingestion。
- 增加 schema mapping、validation 和 TableRegistry。
- WorkflowState、AnalysisTrace、ReviewerResult 和 report 增加 data_source_type、table_metadata、schema_warnings。
- 自定义数据缺少 demo 表结构时，使用 generic analysis fallback。

## v0.4：Usability, Metric Mapping UI and Documentation Polish

目标名称：Usability, Metric Mapping UI and Documentation Polish

范围：

- 修复 README、pyproject、CI YAML、requirements 和 docs 的多行格式可读性。
- 重写 README，补充项目目标、组成部分、架构、数据流、运行方式和限制说明。
- 增加 ColumnMapping / Metric Mapping 模块。
- Streamlit 上传文件和数据库模式增加 Metric / Column Mapping 面板。
- CLI 增加 date、metric、dimension、group、treatment、outcome、time_grain 参数。
- workflow、trace、reviewer 和 report 记录 mapping_source、column_mapping、mapping_warnings。
- custom data workflow 优先使用手动 mapping，不完整时 fallback 而不崩溃。
- 增加文本文件格式测试，防止关键文档被单行化。

## v0.5：当前完成目标

目标名称：Reusable Analysis Playbooks, Visual Diagnostics and Export Bundles

范围：

- 增加 AnalysisPlaybook、AnalysisParameter、PlaybookRequirements 和确定性 registry。
- 提供七个内置 playbook，并以 ColumnMapping 作为输入契约。
- 增加 allowlist identifier、绑定参数和只读检查组成的 SQL template 层。
- 增加 ChartSpec 和自动 Plotly visual diagnostics。
- 增加 RunManifest 与 deterministic dataset fingerprint。
- 增加 Markdown、离线 HTML、Excel、Manifest JSON 和 ZIP Bundle。
- Streamlit 增加 playbook、参数 form、结果 tabs 和内存下载。
- CLI 增加 playbook、参数、config 和 export 参数，保留旧命令。
- rule-based workflow 继续作为默认，LangGraph 继续保持 optional fallback。

## next

- 多表 playbook 编排和结果依赖管理。
- 更多确定性统计诊断与数据质量规则。
- 可配置但仍受 allowlist 约束的本地 SQL template catalog。
- 导出模板版本治理和更细的大小限制提示。
