# 工作台、探索与结果交互验收

日期：2026-09-29。项目与目标版本均为0.1.0，未发布。执行依据完整读取的父目录 `D:\InsightPilot Agent\WORKBENCH_REDESIGN_SPEC.md`。项目根没有另一个同名规格；没有用旧验收报告代替本轮源码和运行检查。

## 基线、备份与范围

工作项目 `D:\InsightPilot Agent\insightpilot-agent`；原始恢复目录 `D:\InsightPilot Agent\source-original` 只读。修改前采用原源码快照工具保存335文件，包括未提交源码：`recovery-backups/insightpilot-agent-0.1.0-source-20260929T111238207905Z.zip`，SHA256 `6ccf7589fa5e7b3d7cfc7e9aee9e89db559162873c0adb48085a84122cf89b13`。报告、用户数据、凭据和环境不在快照中，没有覆盖旧备份。

原始目录逐个复核222文件SHA256均未变化；main仍为 `2532e4665eda9fe16dee98994691a3e6ddbec0e8`，只读Git状态为空。证据 `reports/workbench/original-baseline-check.json`。未执行git add、commit、tag、push，未改旧remote或系统安全配置。

Python3.14.7；Streamlit1.63.0、pandas3.0.5、numpy2.5.3、DuckDB1.5.5、SQLGlot30.18.0、Plotly7.0.0、SciPy1.18.1、ReportLab5.0.1、openpyxl3.1.5。没有升级依赖。来源研究限于Metabase、Superset、Lightdash、JASP第一方页面及本机接口；URL、可见版本、实际截图和未核实内容见[设计参考](workbench_design_references.md)。未安装外部平台或复制产品资产。

## 实际新增与复用

|内容|实际实现与入口|复用边界|
|---|---|---|
|四主导航|分析工作台、数据探索、分析方法、历史比较|Streamlit条件渲染，旧三模式入口未恢复|
|工作台|真实元数据摘要、问题、推荐/缺口、配置草稿、明确开始动作；六常用方法快捷卡|自动推荐、必要澄清、Planner、字段映射保持|
|方法库|查看全部分析方法 → 默认显示Registry十项；显式搜索/分类并可清除；各项用途、输出、状态、配置和要求|因果/实验不因当前数据缺字段而消失；配置不改目标、不自动执行|
|单表探索|数据探索 → 字段概览/分布/分组图/交叉表；确认表、指标、聚合、维度、日期和有限筛选 → 生成|原data_profile或dimension_contribution、AnalyticsEngine与结果包；无自由SQL/Python/公式入口，无YAML前置要求|
|结果交互|结论优先展示实际摘要、适用KPI、最多两张图、小表及动作；图型只改变已有聚合展示|同一结果引用、分页、五维质量、延迟技术详情与报告|
|城市下钻|订单结论 → 城市表选一行（仅草稿） → 基于选中分组继续分析|run_id/修订/结果表/指标/真实键校验，原预检与后台链创建子分支|
|历史与导出|历史比较中恢复/返回/比较；报告页按PDF、Markdown、HTML、Excel、manifest、ZIP顺序显式生成|小摘要、不可变配置、原单份完整结果预算，导出绑定选定成功运行|

十个方法实际保留：data_profile、metric_trend、period_comparison、dimension_contribution、experiment_comparison、causal_exploration、periodic_summary、semantic_metric_query、funnel_analysis、cohort_retention。自动原工作流仍是合法推荐目标，不计为第十一个剧本。39示例与三个主Demo保留。

因果功能原本存在；本轮没有把“功能被删除”当作根因，也没有新写因果算法。新目录复用原配置callback，原daily_metrics/orders映射、明确清空outcome、组值与处理字段分离、用户手动身份均保留。有效24行案例仍是原始差2、OLS调整估计2、n24；随机化、独立性和无混杂前提没有被自动认证。

## 数值与协议

独立手算检查覆盖sum120、mean30和组均值20/40、加权比率10/92、跨格去重整体2而格子和3，以及Top N余集均值20而不是组均值平均30。二维透视行/列/总计从对应原始范围独立聚合；未观测组合不补0，真实缺失与Others使用不同身份。完整高基数55×35=1925格保留，显示上限50×30不替代统计。详见[探索说明](data_exploration.md)和核心测试。

独立进程分别加载修改前快照和工作项目，对订单、用户级实验、直播质量、24行因果四组比较：全部结果表schema/index/value指纹、结构化统计及证据完全相同，见 `reports/workbench/consistency-01/comparison.json`。运行时间与新run_id不作为数值差异。

有意协议变化：ColumnMapping新增可选分子/分母；既有两剧本接收有限exploration_request；结果包增加metadata.exploration；历史上下文增加探索范围和真实分组身份；SQL白名单只补精确分位数函数，不放宽外部访问/写操作/作用域；因果ChartSpec改为并列图，两项估计不再视觉相加。旧统计算法、p-value、置信区间、独立样本单位与百分点口径未更换。

浏览器实际发现并修复：首次下钻成功后探索控件初始化清掉恢复视图；筛选value在报告脱敏后破坏口径定义一致性；因果两项2被堆叠成4；1366首屏摘要换行挤掉开始动作。修复分别为恢复时绑定数据修订、口径卡保留筛选身份指纹并保持原严格校验、并列图、摘要布局与动作优先。失败现场保留，不靠关闭校验、删除测试或缩小正文通过。

## 性能与资源

同机Windows11、Ryzen9 9900X（12核/24线程）、33,984,663,552字节内存。标准交易数据seed42：users20,000行、merchants3,000行、daily_metrics36,000×39、transaction_detail316,035×27、orders同源别名、traffic_events36,000×19。没有把别名当不同独立样本。

前后各三次全新Python/AppTest进程，原生RSS每20ms采样，源表指纹与结果证据指纹分开计数；同步UI用于分离渲染成本，真实浏览器另验受限后台路径。结果与范围见[完整性能对照](workbench_performance.md)。新探索的全量查询成本单列，不当成旧静态切页。

数据1项/1024MiB、结果1项/256MiB（含最多512KiB历史预留）、历史最多10小节点、图缓存1项/16MiB、导出6项/64MiB等预算均未增加；全局2worker、每会话1任务保持。取消沿原协作检查和DuckDB中断边界，不能保证抢占所有第三方原生计算。旧任务身份与数据修订不符时不接纳结果。

## 验收记录

最终冻结源码全量验证：**687 passed、1 skipped、0 failed、0 error**，共688项，XML计时164.703秒。唯一跳过为 `test_real_langgraph_propagates_worker_context_and_cancellation`，原因 `No module named 'langgraph'`。不把确定性回退说成真实LangGraph通过。权威结果 `reports/workbench/verification-final-frozen/20260929T115648377015Z/results.json` 与 `pytest.xml`。

四套实际评估：core 5/5，safety 4/4，determinism 2/2，task 51/51。任务用例包括正常分析、必要澄清、拒绝与可比性判断；结果是这些固定用例的通过数，不是统计结论正确率。11条完整验证命令均exit0，包括依赖检查、语义资源、全量pytest、四评估、三个Demo各六类导出及plan-only。初轮3个旧布局断言失败、后续中间结果和实际浏览器失败现场保留，没有删掉安全/数值测试或跳过全部慢测。

AppTest覆盖四主导航、十方法搜索/清除、显式清空、无效因果零任务、24行有效因果、探索未确认零执行、明确请求执行一次、图型/分页/导航零统计、城市身份校验、父配置不变、子结果PDF/Excel/ZIP绑定。城市原生选中事件另由真实浏览器验证，不能用AppTest注入事件代替鼠标闭环。

wheel为 `D:/InsightPilot Agent/recovery-backups/workbench-wheel-final3-20260929/insightpilot_agent-0.1.0-py3-none-any.whl`，SHA256 `ae5b43a4d18279c8e6396fed08b4ac58a97d9d38c13cb858649f6091f15bfdd1`。148个源码/资源与wheel、独立site-packages三方SHA逐项一致；版本0.1.0、语义YAML/package data、pip check均通过。独立锁定环境中从项目外以 `-I` 导入安装包，复制的关键测试56/56通过，0skip，10.714秒。证据 `recovery-backups/workbench-wheel-final2-validation-20260929/final-wheel-validation.json` 和 `keytests-validation.json`；带final2的是环境目录，最终包为final3。任务评估UTF-8复核为 `final_task_evaluation_utf8.stdout.txt`。

源码快照使用原白名单工具。生产冻结候选在新目录核验整包和所有文件SHA、新建虚拟环境、从本地wheelhouse离线安装锁定依赖、项目外导入和语义资源验证，再在恢复副本跑同一完整验收。最终交付快照另行核验全部成员，并确认生产源码、测试、依赖清单与该候选逐字节一致；最终解压副本复用这个独立依赖环境，重新安装后核对实际导入位置、跑56项关键测试和四评估。明确区分候选完整恢复与最终包关键复测，不声称为每个仅文档变化的ZIP重跑全量。候选 `insightpilot-agent-0.1.0-source-20260929T121219286074Z.zip` 共356文件，SHA256 `cc225ea7665d9b4ce956553abd63e76897a74599105238a48b68ebd278710dd5` 已在全新环境实际完成：687 passed、1 skipped（同一LangGraph缺依赖）、169.748秒；四评估5/5、4/4、2/2、51/51，全部11命令exit0。完整恢复记录 `D:/InsightPilot Agent/recovery-backups/workbench-source-final-restore-20260929/validation.json`，明细 `verification/20260929T121403251212Z`。最终快照路径、哈希及实际恢复结果单独写入 `reports/workbench/final-delivery.json`，避免让源码快照在自身文档中包含自己的哈希。该记录不进入源码快照，不包含业务数据或凭据。

浏览器使用本机Chrome153.0.8010.53的独立临时上下文，通过原生点击、键盘和文件上传操作，不注入session_state或结果。原浏览器插件受本机Windows1385启动限制，改用已安装Playwright控制真实Chrome，未改系统安全设置。AppTest、浏览器点击、视觉和health分别计证。

`reports/workbench/browser-08/checks.json` 中订单/十方法/无效因果/城市选中草稿/显式提交子分支/返回已释放父节点/两run各六导出共72项已执行检查为true；该次总进程随后因因果多选控件探针定位超时失败，不能将整次标为通过。`browser-pivot-04/checks.json` 独立透视闭环67项通过、exit0：四行手算数据sum120、mean30、加权比率10/92、整体distinct3且两组各2，每个新run分别生成六类报告，PDF与manifest身份一致，ZIP内PDF与单独PDF字节相同。此浏览器fixture与核心测试的distinct整体2案例不同，不能混用样本。

上述首页、方法库、订单结果和透视按1366×768、1440×900、1920×1080、1024×768检查，visualViewport.scale=1、documentWidth等于视口宽，无页面横向溢出。root实际查看1366/1024首页、1024方法库、1366订单结果、父结果释放、透视配置/导出截图；因果最终补测单独记录，root亦已目视最终并列图。1366首屏开始按钮y692.25–727.25；1024主配置堆叠。正文/说明14px（10.5pt），标题/卡名16px（12pt），原生按钮/标签12.25px保留既有控件比例，没有缩小正文或改浏览器缩放。

最终中文占位复核使用 `browser-final-visual/placeholder-protocol.json`：可选日期/筛选字段与粒度下发中文占位，DOM实际已选值为“不选择”。旧探针遍历所有input.placeholder时把已有中文值控件的隐藏默认英文属性计为可见文字，现按空值且实际可见判断；没有靠放宽业务结果断言通过。

`browser-causal-08/checks.json` 最终独立因果闭环36/36检查通过、exit0。界面只选取 `covariate`，从最终运行清单核对实际协变量列表，原始差2、调整估计2、n24；六类导出和因果限制通过，run_id为 `477bb320-eac5-44e9-b7b7-07c1bdce5995`。`07b-causal-grouped-chart.png` 实际展示两项2并列；根代理已目视。此前多选定位失败来自探针填入/默认选项处理，改为原生逐键输入、读取可见已选标签并显式移除多余选项后完成，没有注入会话或替换统计输出。

HTTP `/_stcore/health` 实际返回200，只证明服务就绪，不代替以上业务闭环。原始失败目录保留；精确报告路径和最终补测见 `final-delivery.json`。

## 当前限制

探索仅受控单表、一个指标、一行维度和一列维度，不是任意BI表达式平台。完整聚合超过既有100,000行输出上限会明确拒绝；PDF/HTML保留原有说明性预览上限，Excel/ZIP完整聚合受原预算约束。

当前下钻提供城市原生表格选择，不宣称所有Plotly鼠标事件均支持。旧维度表以字符串保存分组时，只有现有元数据可无歧义还原的真实城市键可选；高基数未完整保留键、真实缺失和Others不伪装为可下钻项。交易诊断子分支明确汇总父运行目标日选定城市，不能冒充重新完成跨期归因、显著性或因果证明。

已有直播质量相关性模块为领域受限描述性Pearson；本轮不新增通用Pearson/Spearman方法，不开放假第十一项。真实LangGraph若本机未安装，继续如实跳过；确定性工作流与回退分开验证。

当前仍是本地协作取消与内存保留预算，生成导出时瞬时RSS不是硬进程上限。新增概览图表使部分渲染耗时增加，不能把分析调用不变说成界面全面提速。

## 修改文件与复测入口

完整新增/修改清单由修改前快照逐文件SHA对照生成，位于 `reports/workbench/source-changes.json`，没有删除原源码。关键文件如下：

|职责|文件与主要接口|
|---|---|
|主导航/工作台|`app/ui_streamlit.py:main`、`workbench_shell.py`、`method_gallery.py`、`guidance_panel.py`|
|探索UI与冻结请求|`app/components/exploration_panel.py:stage_exploration`、`history_panel.py:apply_pending_branch`|
|全量聚合/受控透视|`insightpilot/analysis/exploration.py`、`playbooks/executor.py`、`playbooks/validation.py`|
|现有指标与预检扩展|`ingestion/mapping.py`、`metrics/definitions.py`、`planning/planner.py`、`planning/analysis_advisor.py`|
|下钻真实身份|`analysis/drilldown.py:city_candidates/validate_selection/build_drilldown_config`、`app/components/drilldown_panel.py`|
|证据/口径/历史/CLI|`analysis/package_builder.py`、`analysis/threads.py`、`cli.py`|
|结果/字号/图型|`app/components/result_layout.py`、`result_panel.py`、`mapping_panel.py`、`metric_definition_panel.py`、`semantic_panel.py`、`insightpilot/ui/theme.py`、`visualization/factory.py`|
|SQL边界|`insightpilot/tools/sql_safety.py`（精确分位数函数的有限许可）|
|本轮测试/探针|`tests/test_workbench_*.py`、`tests/test_workbench_cli.py`、既有UI断言迁移、`scripts/benchmark_workbench.py`、`benchmark_exploration_ui.py`、`check_workbench_consistency.py`、`check_workbench_browser.py`|
|文档|README、demo_script、releases/v0.1，以及本轮design/references/exploration/performance/acceptance文档|

已实际执行的全量与数值复测命令如下。脚本保留时间戳或拒绝覆盖；重复运行需给新的输出目录。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts/verify_project.py --output-dir reports/workbench/verification-final-frozen
.\.venv\Scripts\python.exe scripts/check_workbench_consistency.py --before reports/workbench/baseline-source/insightpilot-agent --after . --output reports/workbench/consistency-01
```

性能的三次复测命令和实际参数见[性能报告](workbench_performance.md)；最终源码恢复的完整实参和退出码以 `final-delivery.json` 指向的 `validation.json` 为准。恢复工具拒绝覆盖旧目录，离线wheelhouse用于这台机器的Python3.14/Windows64位；不能假定可跨平台直接复用其二进制依赖。

实际浏览器复测命令（先启动本机Streamlit服务，URL必须指向待验收工作副本）：

```powershell
.\.venv\Scripts\python.exe scripts/check_workbench_browser.py --url http://127.0.0.1:8511 --output reports/workbench/browser-08 --scenario all
.\.venv\Scripts\python.exe scripts/check_workbench_browser.py --url http://127.0.0.1:8511 --output reports/workbench/browser-pivot-04 --scenario pivot
.\.venv\Scripts\python.exe scripts/check_workbench_browser.py --url http://127.0.0.1:8511 --output reports/workbench/browser-causal-08 --scenario causal
```

第一条是在探针修复过程中实际执行的分阶段证据，整条当时因后续控件定位失败退出；后两条为对应独立完整成功命令。新一轮复测应更换输出目录，不能覆盖本轮事实记录。最终脚本保留all入口，可以重跑完整串联，但不把尚未用最终脚本重跑的all说成整条通过。

本轮已实际启动并完成health与浏览器检查的命令：

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m streamlit run app/ui_streamlit.py --server.address 127.0.0.1 --server.port 8511 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
```

浏览器访问 `http://127.0.0.1:8511`。验收完成后已用Ctrl+C停止本轮测试服务，未停止用户其他端口。上述命令中的fileWatcherType=none用于冻结验收代码；修改源码后需重启此服务。GUI普通运行也可用README启动方式，但本报告不将未实际执行的变体列成本轮命令。
