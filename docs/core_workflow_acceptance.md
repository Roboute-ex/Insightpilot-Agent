# 主任务闭环验收（0.1.0）

本轮日期：2026-10-08。以下为本轮本机实际执行结果；中间失败和被替代轮次仍保留，不计入最终通过。

## 本机基线与保护

完整依据工作区上层的 `D:/InsightPilot Agent/CORE_WORKFLOW_SPEC.md`；项目目录未找到同名文件。工作分支为 main，HEAD 为 `1ee0f4dd9b67379d86ea744764185884f75a9283`，版本保持 0.1.0。开始时实际有 14 个未提交文件，已保存在修改前白名单快照；未拉取远程覆盖本地，也未执行 Git add、commit、tag、push 或修改 remote。

本轮原始证据均在本机 `reports/core-workflow/20261008-171620883/`。报告、模拟运行输出、截图及验证环境不属于源码快照，也不应据此上传用户数据。

修改前快照为 `before/insightpilot-agent-0.1.0-source-20261008T091621248007Z.zip`，365 个源码文件，SHA256 为 `8736381bf7c9063b33c600afb0c9b1218c36801cf99c23331761a8ac303a5e7b`。它包含当时的未提交源码，未包含旧 Git、用户数据、环境或凭据。先核验所有成员及哈希，再恢复到 baseline-copy 作为本轮对照；没有使用旧远程源码替换工作项目。

原始恢复基线 source-original 的 222 个文件哈希与审计时相同。用户原有 8511、8512、8513 实例未停止、刷新或清缓存；验证服务使用隔离副本及独立端口。依赖锁和 Streamlit 配置保持不变。

## 实际障碍与改动

原来父关系已存在，但返回入口位于历史页；选择历史又与待执行任务身份混在一起，晚到结果可能重选当前运行。父完整结果被一份结果预算释放后，也缺少结果旁可发现的摘要和恢复路径。恢复配置会立即覆盖草稿。上述问题来自本机代码和实际复现，没有将因果方法误判为被删除。

现在在共用结果区展示父关系路径、已执行问题、源表、日期、基准、筛选、指标单位与实际方法。相对词“昨日”的具体目标日取自已经计算的异常结果并冻结到小历史中，不从电脑日期或新草稿推定。

|操作与状态|实际行为|
|---|---|
|根分析|无伪造的父路径或返回按钮。|
|返回父完整结果|只改变查看节点，不执行分析、不新建 run、不生成导出。|
|返回已释放父结果|展示该父节点的小摘要与释放提示，不显示子图表或生成子报告冒充父报告。|
|探索页返回、点击祖先|保留当前探索页和表单，只改变下方选定运行。|
|恢复配置|先提示覆盖内容；可保留当前草稿或确认恢复。恢复本身不执行。|
|明确重新运行|重新预检，创建一次新运行并保留来源关系。|
|数据版本变化|应用到当前数据须明确确认；重新检查字段、口径及审批。缺源表时不能恢复执行。|
|后台晚到|保持用户已经选择的父视图，不能冒充父报告。|
|历史裁剪或非法节点|提示路径边界；拒绝伪造、过期及跨会话节点。|

真实浏览器额外发现：强制离开探索页会丢未提交表单；仅保持页面仍不足，因为已有 initialize_guidance 会自赋所有 widget SessionState，导致 Streamlit 下发旧值。现在对当前挂载表单不做这种自赋，隐藏控件仍保留已提交状态；明确恢复仍允许写入确认后的配置。协议测试检查实际 `set_value`，浏览器另验证未提交值，二者不能互相替代。

没有建立新历史、缓存或后台框架。AnalysisThread 的兼容参数将查看与请求身份分开，UI 用查看序号决定晚到结果是否激活。仍只保留一份完整结果、最多十条有界小历史，未增加父 DataFrame 副本。

## 操作路径

分析工作台 → 输入“昨日订单量为什么下降？” → 开始分析 → 结论中的城市表选择“西城” → 查看该城市当日表现 → 在结果旁核对日期与“城市 = 西城” → 返回上一级分析。

从探索页返回会保留探索表单，下方显示父运行。父结果已释放时：恢复该分析配置 → 阅读覆盖提示 → 保留当前草稿或确认恢复配置 → 完成预检 → 重新运行该分析 → 报告 → 生成 PDF 报告 → 下载 PDF 报告。

恢复父诊断配置的确认动作才切回分析工作台。表单内尚未提交的值不被当作服务器已经读取；手动切换其它主导航、刷新或停止服务不是保存未提交表单的方法。

## 数值、能力与限制

十个原有剧本全部保留，统一从“分析方法”发现和配置。四导航、39 示例、三个场景、自动推荐及必要澄清均沿用。指标诊断围绕“发生了什么、变化集中在哪里、证据支持到哪一步、下一步”组织已有结果；因果、实验、漏斗、留存保留各自模板。

本轮与修改前快照对照的十个剧本全部完成，55 张完整结果表、664 行结果、55 条结构化证据严格一致，数值与证据差异为 0；固定输入指纹相同，没有修改统计算法或测试数值期望。独立关键数值回归另有 17 项通过。因果教学小样仍为原始差 2、OLS 调整估计 2、n=24；没有协变量时不能伪造调整估计。

城市子分支是父目标日的描述汇总，不是重新完成跨期归因，更不是因果效果。实验单位、p-value、区间与百分点、均值、加权比率、跨格去重、Others、变化贡献及安全和审批边界不变。语义多表没有单表映射时，只以该运行冻结的已加载范围作保守检查，缺任何记录源表仍阻断，不猜测替代表。

## 文档同步范围

已更新 README、现有 user_manual.md、quick_reference.md、demo_script.md、demo_mode.md。三项演示分别是指标闭环、专业统计和必要澄清/正确阻断。core_workflow_observation.md 是三任务空白观察表，尚未开展真人试用，不能当作完成率或节省时间成绩。

2026-09-30 的手册 HTML、PDF、速查卡 PDF 与旧手册截图未重建，不能声称与新路径同步。软件报告导出与手册构建是两件事。本轮没有验证真实 LangGraph 路径，本机缺少该可选依赖。

## 最终执行证据

|验收|本轮实际结果|本机证据（相对此次 reports 目录）|
|---|---|---|
|全量 pytest|761 passed，1 skipped，0 failed；202.97 秒|pytest-final4.xml、pytest-final4.log|
|唯一 skip|tests/test_performance_task_core.py:192，本机未安装 langgraph.graph|pytest-final4.log|
|四套评估|core 5/5、safety 4/4、determinism 2/2、task 51/51；0 failed、0 warning|evaluation-final4.json|
|十剧本严格对照|55 表、664 行、55 条结构化证据一致；输入指纹相同，数值/证据差异 0|consistency/summary.json|
|实际浏览器|Chrome 154.0.8037.58，最终强化串联 92 checks 全通过，完整脚本 exit 0|final-browser-attempt4/checks.json、browser-acceptance-record-final3.json|
|未提交表单|实际输入单位而不提交；返回、恢复提示、取消恢复后均保留|browser-form-draft-check-attempt4/checks.json；上述完整串联再次覆盖|
|截图目视|1366×768、1440×900、1024×768，100% 缩放；首页、范围与返回、重算及窄屏父摘要可读，无横向溢出|final-browser-attempt4/01、05、06、07 系列 PNG|
|健康检查|隔离服务实际 HTTP 200；不是功能通过的替代物|browser-acceptance-record-final3.json|
|分发|wheel 构建、离线独立安装、源目录外导入、pip check、语义与任务评估全部 exit 0；150 个必要模块/资源无缺失，逐字节与工作源码一致|wheel-validation-final4/validation.json、wheel-final4-source-receipt.json|

浏览器与性能收据的文件名含 final3，但内部明确绑定最终 **final-copy-attempt4**、快照 SHA256 `424ee8f84b4c4a6caf77710e2ae07866675824cac2fd7bceeb9e0baa8ab3f03f`，不是 candidate3。该副本的产品源码通过真实表单边界后冻结；最终交付快照再加入完整验收文档。

浏览器实测订单目标日 2026-06-30、772 单；西城是该日 38 行、208 单的描述汇总。返回不会把 208 当作整体值。父结果释放后无子图表、无伪父 PDF；确认恢复并明确重跑的新运行 `f75aa25a-9786-467f-9b92-e0d011226aee` 与父、子旧运行不同，下载 PDF 含新运行身份，不含子运行身份。六类导出入口仍在，PDF 第一；生成一种格式不自动生成其他格式。

AppTest/组件测试覆盖根、兄弟父关系、父完整与释放、数据变化、缺源、显式空 outcome、历史裁剪、伪造及跨会话节点、真实异步任务的晚到成功/失败/预览、重复提交，以及实际 widget set_value 协议。父完整结果通过组件与真实状态对象测试，浏览器主链对应真实的一份结果预算下父已释放情形。浏览器不注入 session_state 或分析结果，使用真实控件及表格行选择。

早期 pytest 的旧恢复断言、语义多表源表误判已修正并重跑完整测试；没有删除安全或数值测试。浏览器第一轮定位器缺图标、父日期未冻结，以及 candidate2/3 的未提交表单丢稿均保留失败证据。最后一次完整脚本的成绩独立，不拼接中途成功检查。桌面浏览器插件初始化失败，实际验证使用本机已安装 Chrome 的独立 Playwright 上下文，没有操作用户页面。

自建 8514、8515 服务已停止；用户 8511/8512/8513 的进程仍为 36768/27572/42752。健康 200 是停止前的实测值，不能解释为测试服务现在仍运行。

## 性能对照

机器：AMD Ryzen 9 9900X，12 核 / 24 线程，物理内存 33,984,663,552 字节。Python 3.14.7；Streamlit 1.63.0、pandas 3.0.5、NumPy 2.5.3、DuckDB 1.5.5、SQLGlot 30.18.0。两侧同一解释器和依赖，standard 交易模拟数据、seed=42：daily_metrics 36,000×39，transaction_detail 316,035×27（orders 是该明细的入口），另有 users 20,000 行、merchants 3,000 行及 traffic_events 36,000 行。不能把这些表行数相加当作独立实验样本量。

每侧三次全新进程；同步 AppTest 隔离数据准备、分析和渲染。测试适配器只补足 AppTest 不支持的折叠和表格选择事件，不注入分析结果。测量窗口没有并行测试、安装或自建测试服务；用户原有实例保持运行。真实浏览器用于功能，不将与测试并行时的浏览器用时计作性能数据。

单位秒，格式为中位数 [最小，最大]：

|动作|修改前|最终|
|---|---:|---:|
|数据准备|2.0809 [2.0790, 2.3984]|1.9368 [1.9273, 1.9600]|
|已就绪后的首次分析|0.8311 [0.8303, 0.9578]|0.7989 [0.7935, 0.8015]|
|相同请求复用|0.1437 [0.1435, 0.1438]|0.1436 [0.1404, 0.1516]|
|探索导航|0.0369 [0.0358, 0.0390]|0.0364 [0.0364, 0.0379]|
|明细页面|0.0476 [0.0460, 0.0507]|0.0472 [0.0469, 0.0481]|
|方法目录|0.0376 [0.0370, 0.0418]|0.0365 [0.0359, 0.0372]|
|切换已计算图表|0.0627 [0.0601, 0.0658]|0.0627 [0.0610, 0.0631]|
|既有历史页返回|0.0364 [0.0352, 0.0364]|0.0398 [0.0375, 0.0424]|
|明确恢复后重算|0.8752 [0.8630, 0.9094]|0.7881 [0.7665, 0.7952]|
|单 PDF|0.3822 [0.3756, 0.4131]|0.3710 [0.3642, 0.4100]|
|单 Excel|0.3345 [0.3166, 0.3399]|0.3200 [0.3163, 0.3485]|
|冷 ZIP|0.9749 [0.9659, 1.0031]|0.9499 [0.9315, 0.9502]|
|恢复配置：旧一步、新两步合计|0.0550 [0.0545, 0.0562]|0.0962 [0.0936, 0.0980]|
|新增结果旁原位返回|原来没有此入口|0.0401 [0.0400, 0.0416]|

新增原位返回与既有历史返回是不同入口，分开报告。恢复现在增加显式覆盖确认，完整两步耗时高于旧一步；它换来草稿保护，并未执行分析。没有将仅点击“恢复”打开提示的时间当作完整恢复耗时，也不作固定提速承诺。

RSS 用 Windows GetProcessMemoryInfo 每 20ms 采样 WorkingSetSize，含原生库内存，同时保留 OS lifetime PeakWorkingSetSize；未用 tracemalloc 冒充 RSS。采样峰值中位数修改前 603,402,240 字节 [603,156,480，604,438,528]，最终 603,144,192 字节 [601,518,080，604,557,312]。本次样本没有显示显著内存改善，也没有靠提高预算获得结果。

数据缓存仍为 1 份 / 1 GiB，结果 1 份 / 256 MiB（小历史预留最多 512 KiB 包含其中），导出 6 项 / 64 MiB，图表最多 3,000 点和 20 序列，TTL 1,800 秒；任务最大并发仍为 2，DuckDB 4 线程、1,024 MiB。预算前后完全一致。

三次最终计数均显示：返回、恢复、导航、方法库和切页的加载、画像/校验、完整指纹、SQL、分析入口、后台任务提交、导出均为 0；只有现有轻量元数据预检（常规 1 次、恢复两阶段各 2 次）。首次分析、城市分析、明确重算各调用分析一次。执行时仍计算必要结果指纹，不将其虚报为零。未请求导出调用均为 0，前后六进程的七张根结果表完全相同。原始阶段、调用次数及完整范围见 performance-comparison-final3.json 和两侧 summary.json。

## 实际修改文件与调用关系

|文件|作用|
|---|---|
|insightpilot/analysis/threads.py|沿用 AnalysisThread：查看与请求分离、晚到激活控制、小历史数据身份及已执行日期。|
|app/components/analysis_context.py|project_run_context 从冻结节点投影路径/范围；render_analysis_context 提供共用返回及释放恢复入口；run_source_tables 复用明确来源。|
|app/components/history_panel.py|选择父节点、恢复覆盖确认、数据版本与源表检查；清旧审批；不让空闲恢复伪报取消。|
|app/components/guidance_panel.py|当前挂载表单不自赋旧 widget 值，隐藏字段仍保留已提交配置。|
|app/ui_streamlit.py|请求/结果接纳与查看序号核对，防晚到覆盖；选定结果隔离；显式重新运行。|
|app/components/exploration_panel.py|保留探索表单，按同一身份和数据检查原位展示父完整结果或摘要。|
|app/components/diagnostic_summary.py、result_panel.py、result_layout.py|已有结果的四段诊断呈现、保守去重、风险与最多三个可执行后续动作；不改统计算法。|
|app/components/drilldown_panel.py、insightpilot/analysis/drilldown.py|“查看该城市当日表现”与跨数据会话的分组身份核验。|
|五个 tests/test_core_*.py、相关既有 UI 测试|新增状态/协议测试并迁移有意改变的恢复交互，保留安全、数值和证据断言。|
|scripts/benchmark_core_workflow.py、scripts/check_core_workflow_browser.py|复用已有测试/浏览器工具进行本轮测量与完整串联。|
|README 与上述既有文档、core_workflow_observation.md、本报告|操作路径、三案例及待真人执行的观察表。|

工作区在本轮之前已有 14 个未提交文件；不能把当前 Git diff 的全部内容当成本轮新增。实际相对修改前快照的文件清单见 final-local-audit.json。

## 分发、源码恢复与复测

最终 wheel：`wheel-final4/insightpilot_agent-0.1.0-py3-none-any.whl`，SHA256 `6cda44af1fb7e5af1af2d595368f869243b76c2446c2804da437b7e996caac44`。首次分发验证因主 wheelhouse 缺 pypdf 6.19.0 失败，已保留日志；从本机已有 wheelhouse 找到准确文件并核对 SHA 后离线补入本轮补充目录，没有升级工作环境或网络下载。

最终白名单快照保存于本轮 `final-source/`，校验外部 SHA、成员列表和逐文件 SHA 后，使用另一个全新环境执行源码关键恢复。精确快照名、SHA、导入来源、锁版本一致性、关键 pytest 和四套评估结果以 `source-validation-final/validation.json`、`final-delivery.json` 为准。外部收据在最终归档之后生成，避免文档对自己的快照哈希形成循环引用；未列为通过的检查不能凭安装完成推断通过。

以下命令已实际执行；输出目录为本轮证据目录。再次执行时使用新的时间戳输出目录，工具不会覆盖已有备份。不要在用户当前页面运行浏览器验收。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8 = '1'
& .\.venv\Scripts\python.exe -B -m pytest -ra -o cache_dir=reports/core-workflow/20261008-171620883/pytest-cache-final4 --junitxml=reports/core-workflow/20261008-171620883/pytest-final4.xml
& .\.venv\Scripts\python.exe -B -m insightpilot.evaluation.cli --suite all --output-format json
& .\.venv\Scripts\python.exe scripts/benchmark_core_workflow.py --source-root reports/core-workflow/20261008-171620883/final-copy-attempt4/insightpilot-agent --output-dir reports/core-workflow/20261008-171620883/final-performance3 --repeat 3
& .\.venv\Scripts\python.exe scripts/check_core_workflow_browser.py --url http://127.0.0.1:8515 --output reports/core-workflow/20261008-171620883/final-browser-attempt4
```

浏览器验收前，在独立终端启动的实际命令如下（本轮测试服务已停止）：

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent\reports\core-workflow\20261008-171620883\final-copy-attempt4\insightpilot-agent'
& 'D:\InsightPilot Agent\insightpilot-agent\.venv\Scripts\python.exe' -m streamlit run app/ui_streamlit.py --server.address=127.0.0.1 --server.port=8515 --server.headless=true --browser.gatherUsageStats=false
```

分发、恢复的完整实际命令（含准确 wheel、双离线 wheelhouse、独立解释器和导入路径）分别保存在 wheel-validation-final4/validation.json、source-validation-final/validation.json；源码归档工具仍为 scripts/export_source_snapshot.py，校验沿用 scripts/restore_and_verify.py 的 verify_snapshot。

## 本轮边界

本轮没有真人试用结果、远程 CI 结果、在线模型或新统计方法，也没有新的导航、并行分析平台或持久草稿系统。后台取消仍是既有协作取消：原生步骤可能在当前边界结束后才停止并释放引用；晚到结果的查看隔离已测试。历史上限与一份完整结果意味着返回常需先看摘要，再明确恢复重算。未重新生成的手册 HTML/PDF、未安装的真实 LangGraph 路径继续如实标注。达到主流程可理解、可返回、明确恢复、报告身份正确后停止新增功能。
