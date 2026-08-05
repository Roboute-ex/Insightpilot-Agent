# InsightPilot Agent 项目路线图

当前代码版本为 `0.6.0`。路线图保持工程记录和学习实践口吻；所有能力继续遵守不接入在线模型、不要求密钥、不提交真实数据的边界。

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

## v0.5：可复用分析剧本与导出

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

## v0.6：当前完成目标

目标名称：中文优先体验、语义层、多表规划与质量治理

范围：

- 默认中文 Streamlit 界面，并提供简洁演示、专业分析和开发者模式。
- 使用 presenter 将 AnalysisPlan、JoinPlan 和 QueryPlan 转为中文摘要。
- 增加 SemanticCatalog、RelationshipGraph、JoinPlanner 和 MetricCompiler。
- 增加七表模拟数据与三个多表分析剧本。
- 增加 plan_only、fanout 风险提示和按 plan ID 审批。
- 增加 Data Contracts、LineageGraph 和本地 Observability。
- 增加 Core、Safety、Determinism 本地评估及 CI 质量门禁。
- CLI 默认中文文本，并保留稳定英文 JSON schema。
- 报告默认中文，Manifest 内部键继续保持英文。
- OpenTelemetry、LangGraph 和 MCP preview 保持可选，不影响默认依赖。

## v0.7 建议

- 多表 playbook 组合和结果依赖管理。
- 语义指标版本与兼容性治理。
- 更多确定性统计诊断与数据质量规则。
- 评估基线的本地差异比较。
- 导出模板版本治理和更细的大小限制提示。
