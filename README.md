# InsightPilot Agent

面向有基础数据分析知识的经营、运营分析使用者，把结构化数据中的问题转为口径明确、可下钻、可复核的结果。当前版本 **0.1.0**，中文界面、本地运行。

优先完成一次指标分析：确认日期、指标和统计单位，比较当前值与基准，进入有效分组查看实际范围，再返回父分析并导出选定运行。支持内置模拟数据、CSV、Excel 多工作表和受支持的只读数据库查询结果；输出结构化结果表、证据与限制、图表及按需生成的六类报告。

城市当日探索只给出描述性汇总，不自动重做跨期原因诊断；规则解析限于支持的问题，回归调整也不证明因果。实验、因果、漏斗、留存等十项能力仍在“分析方法”中，按输入与前提选用。

## 1. 输入与输出

输入：内置模拟数据、CSV、Excel 多工作表或只读数据库查询结果。
输出：真实结构化结果、统计方法与限制、证据链、建议、图表、六种本地报告。
默认采用确定性规则 Planner，无在线 LLM、无 API key、无模型训练或权重下载。

## 2. 恢复状态与验收

项目来源及历史版本关系见 [迁移说明](docs/migration_notes.md)。详细能力矩阵与对应轮次记录见 [验收报告](docs/acceptance_report.md)，实施进度见 [实施计划](docs/implementation_plan.md)；历史记录不代表本轮复验成绩。
旧 README 的测试数量、评估得分和实验数字均不作为本次结果。
本地、快照恢复、PDF视觉和远程CI分开报告；CI配置存在不表示远程已运行。

本轮主任务闭环的状态、浏览器证据、性能对照与复测命令见[主任务闭环验收](docs/core_workflow_acceptance.md)。

## 3. Windows 安装

支持 Python 3.11 及以上，本次主环境是 Python 3.14.7，CI 配置 Python 3.11。Streamlit 最低1.63以匹配实际界面API。不要删除或降级系统 Python。
先确认可用解释器，以下 `py` 需已验证可用。命令在项目根目录执行。

```powershell
py --list-paths
py -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -e '.[app,test]' build
& ./.venv/Scripts/python.exe -m pip check
```

无需激活虚拟环境，不修改 PATH、执行策略、TLS 或全局 Git 配置。
安装依赖可能需要网络；安装完成后的默认分析、测试和导出无需网络或账号。
.xls 读取使用 xlrd，.xlsx/.xlsm 使用 openpyxl，不执行宏。

## 4. 启动中文界面

```powershell
./scripts/check_environment.ps1
./scripts/start_ui.ps1 -Port 8501
```

脚本受策略限制时直接执行等价命令，不绕过策略：

```powershell
& ./.venv/Scripts/python.exe -m streamlit run app/ui_streamlit.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

终端保持运行，手动打开 http://127.0.0.1:8501，Ctrl+C 停止。端口占用时改用 8502，不终止别人的进程。

## 5. 数据探索工作台

主导航是“分析工作台、数据探索、分析方法、历史比较”。工作台按“问题与示例 → 配置与预检 → 开始分析 → 分析结果”排列；配置摘要旁可展开“调整方法与参数”，方案预览也在其中。指标诊断按“发生了什么 → 变化集中在哪里 → 证据支持到哪一步 → 下一步”展示已有结果，保留最多两张关键图；实验、因果、留存等采用各自模板。

主导航“分析方法”是全部方法的统一入口。全部十个注册剧本默认可见，可显式搜索或按四类筛选；“清除方法筛选”恢复全部。每项显示用途、输出、当前适配状态与要求；不能执行的方法仍可配置。“配置”只进入已有设置，不隐式改变问题、目标或执行。因果路径：分析方法 → 配置：轻量因果探索 → 明确目标、真实处理/结果字段、两组方向与可选协变量 → 确认字段映射 → 应用参数并更新建议 → 开始分析。字段齐全不代表因果识别已成立。

“数据探索”支持字段概览、分布、分组图和单表二维交叉表。字段概览读取现有元数据；其余在选择表、字段、聚合方式、维度、日期和有限筛选后，明确确认并点击生成才计算。普通CSV/Excel不需要语义YAML。sum、mean、分子/分母加权比率与去重计数分别计算；行/列/总计在对应原始范围重新聚合。Top N/Others和显示上限不替代全量统计。“图表”中切换已支持图型只改变展示。细节见[数据探索说明](docs/data_exploration.md)。

订单诊断完成后，在“结论”的城市选择表选中真实分组，仅生成草稿；再点击“查看该城市当日表现”，通过预检创建父目标日的城市描述性汇总。结果旁显示当前分析路径、源表、已执行日期、筛选与统计单位，点击“返回上一级分析”只查看父运行，不计算。父完整结果已释放时显示真实历史摘要，点击“恢复该分析配置”，选择保留当前草稿或确认恢复，再经预检点击“重新运行该分析”。数据版本变化须明确应用到当前数据并重新确认，缺源表须先加载；旧审批不沿用。详细步骤见[使用手册](docs/user_manual.md#history)。

结果按“结论、图表、明细、报告”按需显示。报告绑定所选已成功运行；编辑草稿不改变旧报告。PDF排在Markdown、HTML、Excel、manifest JSON和ZIP之前，每种格式按请求生成。完整结果分页，技术详情和评估默认不构建。标题12pt、正文10.5pt。查看数据中的预览表不会改变分析范围。

工作台设计背景见[工作台设计](docs/workbench_design.md)、[设计参考](docs/workbench_design_references.md)。[工作台验收](docs/workbench_redesign_acceptance.md)、[方法入口验收](docs/method_discovery_acceptance.md)和[分析引导](docs/analysis_guidance.md)保留为对应轮次记录；当前操作以[使用手册](docs/user_manual.md)和[三项演示](docs/demo_script.md)为准。[人工任务观察表](docs/core_workflow_observation.md)尚待实际使用者执行。

## 6. 工作流

数据接入 → 质量与字段映射 → 指标解析 → 分析计划 → 剧本或规则分析 → 结构化结果与证据 → Reviewer → 报告。
共用Planner预检检查问题相关性、真实字段与精确准备摘要；缺输入、必要澄清或不支持请求在提交任务前阻断。方案预览不执行分析查询或统计工具；执行轨迹只记录真正发生的节点。
结果不足时说明缺失字段或限制，不制造完整成功。

## 7. 三个主场景

交易：订单、收入、漏斗、退款、城市/渠道/版本/新老客差异。
内容：完播、互动、分类、作者、发布时间与用户级实验。
直播：观看会话、观看时长、卡顿、崩溃、启动延迟、设备网络组合。

支持 small/standard/large、seed=42 和固定参考日期。界面默认 standard，单测可用 small。
“昨日”是数据参考日，不是运行电脑当天。只生成当前需要的场景。
实际规模、维度与注入信号见验收报告及 docs/data_recovery.md。

## 8. 示例问题与分析目标

至少39个问题：交易15、内容12、直播12，含推荐目标、剧本和字段。
目标模式：auto、metric_diagnosis、growth_trend、experiment_analysis、content_performance、live_quality、causal_exploration、periodic_report。
用户显式目标优先；问题解析限于明确支持的规则，不能视为通用自然语言理解。

## 9. 十个分析剧本

|剧本|用途|
|---|---|
|data_profile|类型、缺失、重复、分布|
|metric_trend|时间粒度、趋势、滚动和异常|
|period_comparison|前后周期与分组比较|
|dimension_contribution|当前范围的静态分组值、份额与Others；不作跨期归因|
|experiment_comparison|独立样本、检验、提升和区间|
|causal_exploration|朴素差与协变量回归调整|
|periodic_summary|概览、趋势、周期及主要维度|
|semantic_metric_query|受控语义指标查询|
|funnel_analysis|实体去重和时间顺序漏斗|
|cohort_retention|队列、成熟观察期与留存矩阵|

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --list-playbooks
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario transaction --scale small --playbook periodic_summary
```

## 10. 自定义文件与映射

CSV 支持 UTF-8-SIG、UTF-8、GBK；Excel 可选择工作表，页面支持多文件。
数据默认驻留会话内存，不上传、不保存源文件，不读取 pickle。
映射支持表、日期、指标、维度、分组、处理/结果变量、协变量、粒度和聚合方式。原始请求、有效映射和警告分别保留。

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --data-source file --input-file ./local_data/demo.csv --table-name custom --date-column 日期 --metric-columns 销售额 --dimension-columns 城市 --goal-mode growth_trend --export-dir ./reports/custom
```

上述文件需先提供，程序不会凭路径创建数据。ID 默认不应作为度量，比率按分子分母汇总。

## 11. 只读数据库

SQLite 必须是已存在的文件，通过只读连接访问，查询限流失败不会回退无限查询。
外部 SQLAlchemy 需要本机对应驱动及最小只读权限；应用校验不等于数据库权限隔离。
不在命令行直接输入真实密码，优先由本地环境变量 `INSIGHTPILOT_DATABASE_URL` 提供；shell历史可能保留命令。

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --data-source database --query 'SELECT * FROM metrics' --table-name metrics --goal-mode growth_trend
```

连接配置、token、密码与查询参数不得进入报告。外部数据库验证边界见 docs/engine_audit.md。

## 12. 指标与统计方法

计数/金额按口径求和，用户按实体去重，比率为分子总和/分母总和，零分母不可计算。
基准不包含目标日，不完整日期窗口需提示。异常阈值不等于统计显著性。
维度之间不能重复相加解释率，漏斗分解为固定顺序算术替换，不代表因果识别。
实验先确认独立随机化单位，连续型用户指标采用 Welch t 检验；二元指标采用对应比例检验。
概率差写百分点，相对提升写百分比；p-value、置信区间和有效样本保持同一比较方向。
回归调整是轻量因果探索，仍受混杂、重叠性、时序和未观测因素限制。

## 13. 多表与语义治理

商业场景包含 customers、sessions、orders、order_items、products、channels、calendar 与可用事件。
YAML 使用 safe_load 并作为 wheel package data。MetricCompiler 仅支持目录白名单和受限算术。
连接检查键、基数和粒度；无法安全计算的扇出请求拒绝。审批不能使重复累计正确。
计划审批绑定请求及目录/数据指纹，数据改变时需重建计划。

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario multi_table_commerce --metrics total_revenue,order_count --dimensions customer_city --sort total_revenue:desc --plan-only --output-format json
```

## 14. 结果、证据与质量

AnalysisResultPackage 统一实际指标、异常、漏斗、贡献、实验、结果表、图表、证据和建议。
建议引用存在的 evidence_id；统计结果派生摘要，不能反向解析文案生成假数据。
Reviewer 评分是规则检查分数，不是结论正确概率；未执行、等待审批与质量评分分开。

## 15. PDF优先六类导出

顺序固定：PDF → Markdown → HTML → Excel → 运行清单 JSON → ZIP。
PDF 使用 ReportLab A4 中文与跨页表头；HTML 离线内嵌 Plotly；Excel 默认中文工作表。
ZIP 包含 report.pdf、report.md、report.html、report.xlsx、manifest.json、受限 results/*.csv 和中文说明。
表、图、摘要保持相同数值口径。输入原表不进入 ZIP；单元格公式注入与用户文本均需处理。

```powershell
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario content --scale standard --goal-mode experiment_analysis --export-format pdf,markdown,html,excel,manifest,bundle --export-dir ./reports/content
```

CLI 只写指定目录或根 reports/，同名文件使用新后缀；界面在内存生成。视觉验收详情见 docs/ui_export_verification.md。

## 16. CLI兼容与退出码

稳定入口 `python -m insightpilot.cli`；旧入口 `python examples/run_demo.py` 继续调用相同实现。
支持规模、seed、数据来源、映射、目标、剧本、语义请求、配置、可选后端和六类导出；完整参数用 `--help`。
默认中文 text，verbose 才显示内部路由；JSON stdout 保持合法 JSON，错误输出到 stderr。
退出码：0成功，1分析/运行失败，2需要输入或无效参数，3等待审批，4导出失败。
CLI JSON 的 schema_version 是独立兼容协议标识，项目版本由包及 Manifest 的 project_version 表达。

## 17. Manifest、血缘与本地观测

Manifest 保存版本、输入指纹、映射、目标、剧本、语义请求、计划、执行路径、质量和治理摘要，不包含全量 DataFrame。
指纹覆盖全表内容、schema、行顺序和索引。配置导入需重新提供数据，指纹不同必须提示。
UUID、UTC时间和耗时允许变化，确定性比较排除这些字段。脱敏值需要重新填写。
Lineage 保存表→操作→结果，LocalTracer 保留本地 spans；没有在线 exporter。

## 18. 测试与评估

```powershell
& ./.venv/Scripts/python.exe -m pytest
& ./.venv/Scripts/python.exe -m insightpilot.evaluation.cli --suite core
& ./.venv/Scripts/python.exe -m insightpilot.evaluation.cli --suite safety
& ./.venv/Scripts/python.exe -m insightpilot.evaluation.cli --suite determinism
& ./.venv/Scripts/python.exe scripts/verify_project.py
```

评估结果来自本次实际运行和独立小表，不硬编码满分。测试包含UI实际预览、执行、高级设置及诊断展开；AppTest与浏览器视觉验收分别记录。

## 19. 打包与离线备份

```powershell
& ./.venv/Scripts/python.exe -m build
& ./.venv/Scripts/python.exe scripts/check_distribution.py
& ./.venv/Scripts/python.exe scripts/export_source_snapshot.py --output-dir ../recovery-backups
```

白名单快照包含未提交源码、配置、测试、文档和YAML，不含环境、报告、私有数据或凭据；不依赖 Git 索引。
备份位置、SHA256与实际恢复验证见 docs/backup_and_restore.md。依赖 wheelhouse 与源码分别保存。

## 20. 结构与扩展边界

insightpilot/ 下按 ingestion、data、metrics、planning、agents、analysis、playbooks、semantic、contracts、lineage、observability、evaluation、reports、visualization、ui 分层。
app/ 为 Streamlit 页面及组件；examples/ 保留兼容入口；scripts/ 提供检查、打包和备份。
LangGraph 可选，未安装回退规则路径；安装后真实节点错误必须暴露。
MCP Preview 仅本地 schema/API 原型，无传输层协议验收；不支持完整 MCP Server、远程 telemetry collector、通用 Text-to-SQL 或复杂多剧本 DAG。
原仓库未找到许可证文件，保留来源说明，不擅自授予新的开源许可证。

## 21. 大数据性能与响应

版本仍为 0.1.0。页面只在数据源或读取配置变化时重新摄入数据，只在提交分析请求时执行分析；切换展示模式、结果页和详情复用当前结果。表格按页展示，图表从聚合结果按需构建。PDF 优先的六类导出分别按请求生成，下载复用已生成文件。

默认使用受限后台任务：全局最多两个运行任务，每会话一个任务；页面显示真实执行阶段、已用时和协作取消。原生统计、解析或 SQL 调用结束后才能响应取消，改变来源或参数的旧任务不能覆盖新结果。设置 `INSIGHTPILOT_UI_SYNC=1` 并重启服务可显式使用同步兼容入口；CLI 保持同步执行。

数据、结果、展示对象与导出均有数量、内存估计及过期限制，不启用临时磁盘缓存。预算限制保留对象，不能视为进程 RSS 的硬上限。全量统计口径、独立样本量与审批检查保持不变。

性能测量方法、优化前后数据、实际测试结果及完整复测命令见 [性能验收](docs/performance_acceptance.md)；修改前记录见 [性能基线](docs/performance_baseline.md)，实现与边界见 [性能优化说明](docs/performance_optimization.md)。


## 0.1.0 本轮增量改造（2026-09-23）

在现有项目上保留三种中文界面、十剧本、39示例及三个Demo，新增必要口径澄清、中文口径卡、完整作用域SQL检查、会话内配置分支与可比性判断，以及独立任务评估。软件版本仍为0.1.0；RunManifest schema为1.1，并兼容读取1.0。

多个转化率、收入口径或实验方向未确认时不执行。自定义字段自动建议需明确确认；实验组/对照组默认不替用户选择。分支按钮只预填表单，“开始分析”才执行。历史元数据最多10条；原策略仅保留一份完整结果，旧大结果释放后显示需要重新执行。历史JSON仅做脱敏配置与schema核验，不恢复数据、密码或执行授权。PDF仍位于六类导出第一位，各格式按请求生成并绑定选定run_id。

受保护数据库查询本轮认证DuckDB/SQLite；PostgreSQL/MySQL/MariaDB会在连接前明确拒绝，不能视作已认证支持。流程检查评分保留，但不代表统计结论百分之百正确；统计前提未验证时如实显示。

本轮评估：`python -m insightpilot.evaluation.cli --suite task --output-format json`。完整本机命令、前后测量、失败修复记录、打包恢复和限制见 [增量验收](docs/upstream_improvement_acceptance.md)。设计与来源分别见 [差距表](docs/upstream_gap_analysis.md)、[指标与澄清](docs/metric_definitions_and_clarification.md)、[SQL策略](docs/sql_policy.md)、[分支对比](docs/analysis_threads_and_comparison.md)、[任务评估](docs/task_evaluation.md)、[固定版本上游研究](docs/upstream_references.md)。前面保留的历史验收数字仅代表对应历史轮次。

## 0.1.0 引导式分析修复（2026-09-29）

本轮只改推荐、适配性预检、状态与恢复流程和界面。订单下降问题优先推荐描述性指标诊断，不把“为什么”一律解释为因果推断。处理组/对照组取值不等于分组字段；缺分组、组值不存在、结果全空、必要日期不足等实际缺口会阻断。有效因果探索和用户级实验仍可执行，字段齐全不代表随机化、独立性或无混杂已经验证。

UI、CLI、workflow复用相同建议与原因。仅询问建议可用下列命令；`--advise-only`正常返回建议的退出码为0，即使建议指出不可执行，也不代表分析成功。实际执行缺输入返回2；真实执行失败返回1，审批与导出沿用原退出码。

```powershell
.\.venv\Scripts\python.exe -m insightpilot.cli --scenario transaction --scale standard --question '昨日订单量为什么下降？' --playbook auto --advise-only --output-format json
.\.venv\Scripts\python.exe -m insightpilot.cli --scenario transaction --scale standard --question '昨日订单量为什么下降？' --playbook auto --output-format json
```

规则解析覆盖已验证示例及有限同义/否定表达，不支持任意自然语言分析、未来预测或因果证明。未支持目标明确拒绝，不用无关画像冒充完成。数据、结果、导出预算和任务并发不变，全文指纹只在数据准备阶段生成，未请求报告不预生成。

本轮实际结果、失败日志、同机性能对照及恢复验证见 [引导式分析验收](docs/guided_analysis_acceptance.md)。前文2026-09-07、2026-09-23记录属于历史轮次，不能当作本轮成绩。


## 中文日常使用手册（0.1.0）

- [中文使用手册](docs/user_manual.md) · [操作速查卡](docs/quick_reference.md) · [教学 CSV 与字段说明](docs/examples/user_manual/README.md)
- [离线 HTML 手册](reports/user-manual/20260930-125203/InsightPilot_Agent_使用手册_0.1.0.html) · [A4 PDF 手册](reports/user-manual/20260930-125203/InsightPilot_Agent_使用手册_0.1.0.pdf) · [两页速查卡 PDF](reports/user-manual/20260930-125203/InsightPilot_Agent_日常操作速查卡_0.1.0.pdf)
- [文档事实与格式核对记录](docs/user_manual_verification.md)

Markdown 操作路径更新于 2026-10-08。以上 HTML、PDF、速查卡 PDF 和手册截图仍为 2026-09-30 构建，本轮未重建，不包含当前结果旁返回与恢复流程。需要重建时，在项目根目录运行 `python docs/tools/build_user_manual.py --output-dir reports/user-manual/<新的构建目录>`，再按实际输出核对排版，不覆盖旧构建。
