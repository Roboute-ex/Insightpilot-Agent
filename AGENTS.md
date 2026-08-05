# InsightPilot Agent 维护说明

## 项目边界

InsightPilot Agent 是 synthetic-data-first 的本地分析自动化工作台，用于学习研究、数据分析自动化、业务分析工作流实践和 Agent 工程化实践。默认工作流是 deterministic rule-based planner，不依赖在线 LLM。

## 数据与凭据边界

- 不允许提交真实用户数据或真实外部业务数据。
- 不允许提交上传文件、数据库查询结果、本地数据库文件或临时导出。
- 不允许提交 API key、token、cookie、私钥、数据库密码或 `.streamlit/secrets.toml`。
- 所有 demo、测试和文档示例必须使用 synthetic data 或测试内生成的 tiny synthetic fixture。
- 不要把 synthetic data 或用户自定义数据结果描述成真实业务结论。

## 测试要求

- 核心函数需要保持 deterministic，随机过程必须使用 seed。
- 修改 synthetic data、planner、workflow、reviewer、report、goal_mode 或 ingestion 时，需要运行 `pytest`。
- DuckDB 查询层和 database ingestion 必须保持只读安全检查，禁止写操作 SQL。
- 三个 synthetic demo 场景应保持可用，CLI 旧命令继续可用。

## 版本语义规则

- 当前 `0.6.0` 表示中文优先界面、Semantic Layer、多表规划与质量治理。
- v0.1 是基础分析能力合并版。
- v0.2 聚焦 WorkflowState、route_taken、AnalysisTrace、ReviewerResult、workflow_backend 和 optional LangGraph fallback。
- v0.3 聚焦 CSV / Excel upload、database query ingestion、schema mapping、validation 和 custom data fallback。
- v0.4 聚焦 ColumnMapping、Metric Mapping UI、custom data usability、documentation polish 和 format normalization。
- v0.5 聚焦 AnalysisPlaybook、safe SQL templates、ChartSpec、RunManifest 和 in-memory export bundles。
- v0.6 聚焦三种界面模式、SemanticCatalog、JoinPlanner、MetricCompiler、Data Contracts、Lineage、Observability 和 Evaluation Suites。

## 文本文件格式规则

- README、AGENTS、docs、pyproject.toml、requirements 和 CI YAML 不得单行化。
- Markdown 必须保持多行标题、列表和 fenced code block。
- pyproject.toml 必须保持标准多行 TOML。
- `.github/workflows/ci.yml` 必须保持标准多行 YAML。
- 修改文档或配置后，需要运行 `tests/test_text_file_formatting.py` 或全量 `pytest`。

## Data Ingestion 维护要求

- ingestion 代码集中维护在 `insightpilot/ingestion/`。
- 上传文件只在内存中读取，不默认写入仓库或磁盘。
- CSV/Excel 读取应给出友好错误，不影响 synthetic demo。
- Excel 依赖缺失只影响 Excel 模式，不影响 CSV、synthetic 或 workflow import。
- TableRegistry metadata 不得包含完整 DataFrame。
- 自定义数据必须记录 table metadata、schema mapping 和 warnings。

## ColumnMapping 维护要求

- ColumnMapping 定义维护在 `insightpilot/ingestion/mapping.py`。
- 手动 mapping 优先于自动 schema 推断。
- mapping 字段必须兼容旧 workflow 调用；未传 mapping 时应自动建议或 fallback。
- column_mapping、mapping_source 和 mapping_warnings 必须写入 workflow state、trace、reviewer 和 report。
- 无效 mapping 只能产生 warning 并移除无效列，不得导致 workflow 崩溃。
- synthetic demo 不强制要求 mapping。

## SQL Safety Rules

- database query 只允许单条 SELECT/WITH。
- 禁止 DROP、DELETE、INSERT、UPDATE、ALTER、CREATE、TRUNCATE、MERGE、REPLACE、GRANT、REVOKE、ATTACH、DETACH、COPY 等写操作。
- 禁止分号连接多语句。
- database_url 在 UI/report/log 中必须 mask password。
- 不要鼓励提交真实数据库连接信息。
- Playbook 不允许接收可执行 SQL fragment。
- Playbook SQL 的 table/column identifier 必须来自 TableRegistry 与 ColumnMapping allowlist。
- 日期、阈值、Top N、分组值等 scalar 必须使用参数绑定，不得直接拼接。
- SQL preview 只能展示占位符，不允许用户编辑后直接执行。

## Analysis Playbook 维护要求

- playbook 代码集中维护在 `insightpilot/playbooks/`。
- AnalysisPlaybook 必须声明 requirements、parameters、executor、chart types 和 output sections。
- Playbook 不得绕过 ColumnMapping validation。
- 推荐逻辑必须 deterministic，不使用在线模型。
- 新增 playbook 必须同步增加 tests 和中文 docs。
- 不传 playbook_id 时必须保持 v0.4 自动工作流兼容。
- playbook 执行失败优先返回 structured WARN/FAIL、caveats 和 errors，不得让 UI 崩溃。

## ChartSpec 与 Export 维护要求

- ChartSpec 必须 JSON serializable，trace 只保存 spec，不保存 Figure。
- 空结果、缺列或绘图失败不得阻断 findings。
- HTML 不依赖在线 CDN，Excel 和 ZIP 默认在内存生成。
- exports 不得包含 secrets、上传源文件或数据库连接信息。
- result CSV、HTML preview 和 Excel result sheet 必须保留行数上限。
- PDF 必须使用中文 CID 字体并返回内存 bytes，不提交字体文件。
- PDF 下载按钮必须排在所有报告下载按钮第一位，ZIP 必须包含 `report.pdf`。

## 结果优先分析要求

- 不得用 AnalysisPlan 代替 AnalysisResult；方案预览不能冒充已经执行的计算。
- legacy workflow 必须输出非空结构化 result tables，并适配 AnalysisResultPackage。
- 所有用户可见结论必须有结构化结果或 AnalysisEvidence 支撑。
- ActionRecommendation 必须引用存在的 evidence_id。
- 用户页面默认不得显示原始指标 ID，开发者模式才可以附带稳定英文 ID。
- 不使用训练模型或生成式文字填补分析逻辑、结果表或证据链缺口。
- 内置模拟数据异常必须在生成逻辑中注入，结果层不得读取 scenario metadata 硬编码结论。
- PDF、Markdown、HTML 和 Excel 必须包含实际分析结果章节。

## RunManifest 维护要求

- manifest 不得包含完整原始数据、DataFrame、明文密码、完整 database URL 或上传文件绝对路径。
- dataset fingerprint 必须 deterministic，用于核对输入变化，不用于恢复原始数据。
- config import 必须检查 manifest 主版本兼容性。
- manifest 仅用于复现配置，不保证恢复原始输入。

## WorkflowState 维护要求

- WorkflowState 定义集中维护在 `insightpilot/agents/state.py`。
- workflow 内部节点应通过 WorkflowState 传递 user_question、goal_mode、intent、selected_metrics、analysis_plan、route_taken、caveats、errors、data_source_type、table_metadata、schema_warnings、selected_playbook_id、playbook_parameters、chart_specs 和 run_manifest。
- `route_taken` 必须记录实际节点路径，例如 `load_data_source`、`validate_tables`、`infer_schema`、`generic_analysis_fallback`、`review`、`generate_report`。
- `to_dict()` 不得直接序列化完整 pandas DataFrame，只能输出安全摘要。

## Custom Data Fallback

- 对 `uploaded_files` / `database` 数据源，缺少 demo 表结构时不要崩溃。
- 自定义数据优先使用 ColumnMapping；缺失时才使用 schema 推断。
- metric_diagnosis / growth_trend 尽量使用日期列 + 数值列做通用趋势或异常检测。
- experiment_analysis 缺少 control/treatment 分组和 outcome 时，应输出说明，不要硬跑。
- causal_exploration 缺少 treatment/outcome 时，应输出 caveat，不要硬跑。
- live_quality / content_performance 缺少相关字段时，转为 generic summary。

## Analysis Goal Mode 维护要求

- goal_mode 定义集中维护在 `insightpilot/planning/goal_modes.py`。
- `auto` 模式必须继续使用 deterministic keyword rules。
- 用户手动选择的 goal_mode 优先于关键词识别。
- 无效 goal_mode 必须回退到 `auto`，不能让程序崩溃。

## 可选依赖 Fallback

- LangGraph 只能作为 optional dependency。
- 缺少 LangGraph 时项目必须继续使用 rule-based workflow。
- `requirements.txt` 不要加入 LangGraph；`requirements-langgraph.txt` 单独管理。
- `requirements.txt` 包含 v0.3 默认能力所需的 openpyxl 和 SQLAlchemy。
- OpenTelemetry 与 MCP preview 不得成为默认依赖，不得配置在线 exporter。

## 中文界面维护要求

- 默认 ViewMode 必须为 `demo`，原始 JSON 仅在 `developer` 模式展示。
- 用户可见标签、按钮、错误、警告、空状态、表头和报告以中文为主。
- 内部 dataclass、枚举、QueryPlan、Manifest 和 CLI JSON key 保持稳定英文。
- 所有 `st.json` 必须显式设置 `expanded=False`。
- UI 文案集中维护在 `insightpilot/ui/`，不得在主页面重复维护映射。
- 紧凑摘要卡片标题使用 12pt，正文使用 10.5pt，不使用 `st.metric` 充当大字号正文卡片。

## Semantic Layer 维护要求

- 语义模型集中维护在 `insightpilot/semantic/models/`，只使用 `yaml.safe_load`。
- 表名、字段名、指标和维度必须经过 SemanticCatalog allowlist。
- MetricCompiler 不接受 SQL fragment，所有 scalar 使用参数绑定。
- QueryPlan ID 和 JoinPlan ID 对相同输入必须 deterministic。
- fanout 风险必须进入 Plan Review；many-to-many 默认禁止。
- 高风险批准必须匹配当前 plan ID，计划变化后旧批准失效。

## Governance 与 Evaluation

- Data Contract、Lineage 和 Observability 只保存安全摘要，不保存完整源数据或凭据。
- 本地 trace 不连接网络；可选 OpenTelemetry 未安装时自动回退。
- Core overall 必须不低于 0.95，数值正确性不低于 0.98。
- SQL Safety 和 Determinism 必须为 1.0。
- CI 必须运行语义模型校验、全量 pytest、三套评估、中文 UI 冒烟和 JSON schema 稳定性测试。

## Reviewer Score 维护要求

- ReviewerResult 定义维护在 `insightpilot/agents/reviewer.py`。
- ReviewerResult 包含 `status`、`score`、`checks`、`issues`、`suggestions`。
- 正常 demo 不应被误判为 FAIL。
- 自定义数据应检查 data_source、table_metadata、schema_validation 和 custom data limitations。
- errors 非空时至少 WARN，严重缺失时 FAIL。

## GitHub Actions CI 维护要求

- CI 文件维护在 `.github/workflows/ci.yml`。
- push 和 pull_request 时运行。
- 使用 Python 3.11。
- 安装 `requirements.txt` 并运行 `python -m pytest`。
- CI 不连接外部数据库，不安装真实数据库专用驱动，不安装 `requirements-langgraph.txt`。

## 文档风格

- 中文为主，表达面向学习研究和工程化实践。
- 不写具体组织或品牌名称。
- 不写与真实数据入库相冲突的示例。
- 所有限制说明要明确 synthetic data、相关性和不确定性边界。
- Release 说明主体使用中文。

## 后续版本建议

- v0.7：多表 playbook 组合、语义指标版本治理、更多本地统计诊断和评估基线比较。
