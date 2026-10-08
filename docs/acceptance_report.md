# InsightPilot Agent 0.1.0 本次恢复与验收

本报告只引用本轮实际读取、修改和运行结果。原始基线、历史说明与当前整合版分开保留。最终源码快照已经在全新目录/venv中独立恢复，安装、项目外导入和全部验收退出码均为0。准确证据见外层 `recovery-notes/clean_restore_validation.json`。源码ZIP保留打包时文档状态；本报告是后续真实验收补充，执行源码未改变。

## 路径与来源

- 新工作项目：`D:/InsightPilot Agent/insightpilot-agent`，版本 **0.1.0**，未初始化 .git、未关联旧远程。
- 原始基线：`D:/InsightPilot Agent/source-original`，保留 .git，HTTPS公开只读来源 `https://github.com/Roboute-ex/Insightpilot-Agent.git`。
- main 提交：`2532e4665eda9fe16dee98994691a3e6ddbec0e8`，与原 v0.6 标签相同；共恢复222个受跟踪文件，原 v0.1–v0.6 标签未改动。
- 恢复日志/清单：外层 recovery-notes/；原始ZIP、Git bundle、源码快照、离线依赖：外层 recovery-backups/。
- 原始源码ZIP SHA256：`4f16e4c0dbf542936202d075c90867bfc6c5e87097d9de59c60035e19829f4e5`。
- 新工作文件与建议暂存清单见 `suggested_staging_files.txt`；此清单只是建议，未执行暂存。

## 恢复、修复与补建矩阵

|规范能力|来源审计|本次状态与实际证据|
|---|---|---|
|基础指标、规划、统计、因果|主体已恢复但需修复|已保留并修复加权比率、四类日历基准、七阶段守恒、贡献、实验单位/CI、回归限制|
|工作流、Trace、Reviewer|主体已恢复但需修复|规则路径可运行；真实LangGraph三场景逐表一致；未执行/缺输入/待审批与评分分开|
|CSV/Excel/只读数据库|主体已恢复但需修复|真实CSV三编码、xls/xlsm/xlsx、多sheet、SQLite只读/限流/释放、手动映射通过|
|规模场景、39问题|scenarios与example_questions远程全部历史未找到|补建；标准/large实测、种子确定、主外键/时间/明细对账、39配置逐条执行|
|十剧本与统一实际结果|主体已恢复|十剧本有效small输入实际完成，均有结果；空输入明确不适用；证据和建议引用真实结果|
|语义、多表、审批|主体已恢复但需修复|包内YAML；安全单事实/多表维度，受限跨事实独立聚合，分组累计和结构化排序，指纹绑定审批|
|三种中文页面|组件已恢复但需修复|AppTest实际预览/执行/切换/旧结果/导出；Chrome独立上下文实际浏览、切换、下载|
|PDF优先六导出|PDF远程全部历史未找到，其余已恢复|补PDF；标准三场景18个文件，PDF共31页实际渲染，Excel/ZIP/HTML读回通过|
|Manifest/契约/血缘/spans/评估|主体已恢复但需修复|脱敏、严格JSON、已脱敏配置要求重新输入、本地实际血缘/计时与独立expected评估|
|打包/源码备份|旧仓库没有完整恢复交付链|新增检查、启动、打包/快照/恢复脚本；wheel独立离线安装通过；源码快照独立离线恢复、281项测试及三场景六导出通过|

文档宣称但未作为本轮成绩的部分：旧测试数量/满分、历史实验数值、远程CI，以及未连接的外部数据库服务。无完整MCP传输或远程collector，不当作已完成产品能力。详细缺口复核见 spec_gap_review.md。

## 保留与新增模块

保留原 ingestion、metrics、planning、agents、analysis、playbooks、semantic、contracts、lineage、observability、evaluation、ui、visualization、app/components 和原报告实现。
新增重点为 reports/pdf.py、data/scenarios/、data/example_questions.py、tools/sql_safety.py、semantic/cross_fact.py、分析/结果展示适配与安全辅助、包内cli.py、examples/generate_demo_files.py、scripts/ 下的启动/环境/打包/快照/恢复检查。旧examples/run_demo.py继续调用同一CLI。
原 .gitignore 裸 data/、reports/ 改为根目录规则；合法隐藏配置、YAML、模拟xls测试夹具保留。
未找到原许可证文件，保留来源/作者信息，不擅自选择新许可证。迁移关系见 migration_notes.md。

## 环境

本机 Python **3.14.7**，项目 `.venv/Scripts/python.exe`；支持声明为Python>=3.11，Streamlit>=1.63匹配本次实际UI API。无需激活环境或改变执行策略。

|库|本次实际版本|
|---|---|
|pandas / numpy|3.0.5 / 2.5.3|
|duckdb / scipy / statsmodels|1.5.5 / 1.18.1 / 0.15.0|
|scikit-learn / Streamlit / Plotly|1.9.0 / 1.63.0 / 7.0.0|
|openpyxl / xlrd / SQLAlchemy|3.1.5 / 2.0.2 / 2.0.52|
|PyYAML / ReportLab / sqlglot / pytest|6.0.3 / 5.0.1 / 30.18.0 / 9.1.1|

requirements-lock.txt记录本次Windows/Python3.14核心实际依赖，不冒充跨平台锁；外层environment-freeze记录环境。独立可选 `.venv-langgraph` 使用LangGraph1.2.11，主环境未安装LangGraph，回退和真实后端分别验收。安装可联网或用本地wheelhouse，默认分析无需网络/账号/API key。

## 标准场景实际规模

|场景|规模|日期/维度/问题|
|---|---|---|
|交易|36,000日分组；316,035逐订单；3,000商户；20,000用户|180天；14类维度；15问题|
|内容|20,000内容；43,200日分组；108,042播放；12,000实验分配/实验用户|120天；11类维度；12问题|
|直播|50,400独立开播；8,000主播；54,000观看会话；53,695日分组|90天；10类维度；12问题|

每场景6个常用问题，共39个；35显式剧本与4自动流程，全部执行有实际结果。比率分组不可相加时保留合理WARN。总体实验和分层实验配置不同，订单与支付问题指标/摘要不同，直播体验与转化输出真实配对关联。
large也实际生成并检验：交易146,000日分组/1,283,484订单；内容172,800日分组/432,023播放/24,000实验用户；直播216,000观看会话。注册时间早于观测，外键有效。
内置固定seed42/参考日期，不依赖电脑当天。开播场次、观看会话、观测去重观众与交易旅程计数均分别定义，不混充UV或独立样本。

## 十剧本实际运行

|剧本|实测主要结果|结果|
|---|---|---|
|data_profile|字段/数值分布/缺失重复|COMPLETED/PASS|
|metric_trend|35个实际日期聚合|COMPLETED/PASS|
|period_comparison|维度与整体周期对比|COMPLETED/PASS|
|dimension_contribution|5个维度项|COMPLETED/PASS|
|experiment_comparison|组摘要、检验与统一实验表|COMPLETED/PASS|
|causal_exploration|真实回归与朴素差|COMPLETED/PASS|
|periodic_summary|概览、趋势、周期及维度|COMPLETED/PASS|
|semantic_metric_query|101行语义日期聚合|COMPLETED/PASS|
|funnel_analysis|5阶段有序去重会话|COMPLETED/PASS|
|cohort_retention|88队列周期、11行矩阵|COMPLETED/PASS|

以上为独立small有效输入的实际执行，不是所有业务数据的适用性承诺。具体行数/SQL次数见 engine_audit.md 与 reports/verification/engine-audit-20260907T073337/playbooks.json。

## 实验统计

标准内容实验统计单位为 **user_id**，每组6,000个独立用户。连续型用户完播率使用Welch t-test，置信区间使用同一有效样本、同一处理减对照方向及Welch–Satterthwaite自由度。

- 对照均值0.5396165962665143；实验均值0.5683954406137294。
- 绝对差0.028778844347215116，即 **2.8778844347215116个百分点**；相对提升 **5.333202230311199%**。
- p-value **1.4098989398539446e-25**；95%绝对差CI **[0.023394925759012024, 0.03416276293541821]**，即约 **[2.33949,3.41628]个百分点**。
- CLI/结果表/PDF/Markdown/HTML/Excel数值保持一致。显著性不等于直接上线，仍需复核随机化、长期稳定性和多重比较。

## 本轮测试与评估

- 原始基线：import退出1、pytest收集退出4、Demo退出1，均真实报缺失reports.pdf；原始文件未修改。
- 中间全量：196通过、4失败；按实际行为修复/更新兼容契约，未删失败测试。
- 集成全量：**276 passed in155.22s，退出0**，原日志为外层 integration-pytest.log。这是该次实际统计，不与重叠子集相加。
- core：5案例通过，overall1.0；safety：4案例（其中含7种外部访问攻击）通过，1.0；determinism：2案例通过，1.0。expected来自独立小表/手算/独立聚合，非硬编码。
- 扩展安全套件第一次实测0.964286，暴露字符串路径表访问；修复后才得到上述成绩，失败案例保留。
- **最终独立快照环境：281 passed in 136.24s，0失败、0错误、0跳过，退出0**。完整pytest、3套评估、3场景CLI/六导出和语义预览均退出0。实际证据见外层 clean_restore_validation.json；这次统计由新环境重新产生。
- 真实LangGraph三个场景的业务表/data_quality逐表一致；预览实际trace查询列表存在且长度0。初次丢失schema warnings问题已修复，最终冻结后复验见外层langgraph-final-frozen.json；完整多指标跨事实CLI见final-cross-fact-cli.json。

## 六类导出与视觉

本轮标准报告位于 `reports/verified-standard-20260907/`，三场景各PDF/Markdown/HTML/Excel/Manifest/ZIP，共18文件；final_artifact_inventory.json记录字节数与哈希。
PDF页数交易16、内容4、直播11；全部31页渲染并逐页联络图检查，另放大读三份首页及实验区。实际中文可读，无裁切/重叠，跨页表头/页码/版本通过。一次分页修改产生过大空白已回退修正并重新验收。
Excel读回无公式注入、默认无重复英文sheet，实验数值一致；ZIP逐项匹配独立文件；HTML各仅一份内嵌Plotly，无在线CDN。
最终冻结后Chrome独立上下文重新执行实际分析与六按钮导出，下载PDF为46,720字节且page_errors为空；证据为 `.tmp_tests/browser_visual/final_frozen/validation.json`。
Chrome独立临时浏览器上下文实际完成预览/分析/三模式切换/结果明细/导出，修复导出tab跳走后确认PDF按钮第一并实际下载。截图与事件为 `.tmp_tests/browser_visual/`；AppTest交互另有回归，不拿health=200代替验收。
PDF CID字体在本机由SimSun替代渲染；没有分发字体，不宣称所有阅读器平台已验证。PDF每表40行、最多20表且有截断说明；完整结果通过其他受限导出查看。详情见 ui_export_verification.md。

## 打包与源码恢复凭据

wheel/sdist已实际构建，包含PDF、scenarios、example_questions、semantic YAML、包内CLI及app。独立wheel环境离线安装后在源码目录之外导入0.1.0和YAML通过；首次wheelhouse相对路径错误已修，失败环境日志保留。
源码快照白名单包含未提交源码、合法隐藏配置、模拟xls夹具、测试/文档；排除旧Git、环境、输出/业务数据和凭据，并检查链接/reparse point、解析路径边界和敏感文件名/格式。SHA256清单逐文件校验。

已验源码快照：`insightpilot-agent-0.1.0-source-20260907T081238059190Z.zip`，268文件，SHA256 `56c69668a57eb7a7f865450eed7d3db2e9f1448f0d3d6c171dc0a4eb99d57b8e`。
本次原222个文件全部保留，其中149未改、73修复/更新，新增46个文件；最终基线222文件哈希和Git状态均未变。快照内文档是打包时状态；随附验证资料记录之后真实通过，工作副本仅补记本文及进度/缺口/备份说明，执行源码与已验快照逐字节一致。
最终恢复通过：外层 `recovery-notes/clean_restore_validation.json` 记录实际快照、独立新venv、安装/导入/完整验收退出码，全部为0。源码恢复目录为 `recovery-backups/source-restore-validation-final/`；最终wheel在另一个新venv安装及项目外CLI六导出也通过。备份恢复流程见 backup_and_restore.md。

## 实际使用命令

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
./scripts/check_environment.ps1
./scripts/start_ui.ps1 -Port 8501
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario transaction --scale standard
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario content --scale standard --goal-mode experiment_analysis --export-format pdf,markdown,html,excel,manifest,bundle --export-dir ./reports/new-content
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario multi_table_commerce --metrics total_revenue,session_count,revenue_per_session --dimensions customer_city --sort revenue_per_session:desc --plan-only --output-format json
& ./.venv/Scripts/python.exe -m pytest
& ./.venv/Scripts/python.exe -m insightpilot.evaluation.cli --suite all
& ./.venv/Scripts/python.exe scripts/verify_project.py
& ./.venv/Scripts/python.exe scripts/export_source_snapshot.py --output-dir ../recovery-backups
```

如PowerShell策略限制脚本，直接运行README中的等价python命令，不绕过策略。Streamlit仅绑定127.0.0.1，终端持续运行，Ctrl+C停止；占用端口改用8502，不结束他人进程。

## 环境与能力边界

- 未运行远程GitHub CI，也未在本机实际运行Linux/Python3.11；CI已配置这两类系统。不能把配置当运行成绩。
- SQLite已实测；真实外部PostgreSQL/MySQL需对应驱动、服务与最小只读账号，未连接真实外部数据库。
- 跨事实支持整体与共同非时间维度的独立聚合；不支持的日期/事实粒度/不安全维度明确拒绝，不宣称通用多表Text-to-SQL。
- MCP仅本地schema/API Preview，无transport；OpenTelemetry可选、无远程exporter；复杂多剧本DAG非本版能力。
- 所有演示为模拟数据，关联/回归不是无条件因果结论，PDF跨阅读器字体兼容仍取决于本地CJK支持。
- 未自动git add、commit、tag、push，未重写原历史/标签、未配置新推送目标，未上传数据、数据库、报告或凭据。
