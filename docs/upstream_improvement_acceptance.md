# InsightPilot Agent 0.1.0 增量改造验收

本轮日期：2026-09-23。按实际 `D:/InsightPilot Agent/UPSTREAM_IMPROVEMENT_SPEC.md.md` 执行。项目在原0.1.0上增量修改；未重建、未发布，未执行git add/commit/tag/push或修改remote。source-original保持只读。下列均为本轮运行；README前面的历史数字不能当成本次成绩。

## 1. 完成范围与边界

P0-A完成：在既有MetricDefinition/SemanticMetric/ColumnMapping上扩充口径；Planner轻量预检输出ready/needs_clarification/unsupported/invalid_input；收入、转化率、人数、实验方向/独立单位必要澄清；未确认时不执行SQL或统计；内置明确场景免重复追问。展示与计算指纹分离，标题变化只更新显示/报告，语义或SQL策略变化使相关计划/缓存失效。

P0-B完成：沿用本机SQLGlot30.18.0补全作用域、列、函数、AST节点及所有分支检查，原查询和限流包装都检查；DuckDB/SQLite明确方言与只读执行。缺依赖、解析/作用域失败均关闭执行，未降级弱正则。

P0-C完成：不可变配置、最多10条小历史摘要、显式分支/返回/比较，沿用一份完整结果与原后台管理器。旧结果释放后需要重新执行；不同维度按键核对而非逐行相减；不同语义拒绝，窗口不同只作描述性差异；比例绝对差显示百分点。六格式报告绑定选定且仍可用的run_id，未提交表单不混入历史报告。

P0-D完成：29个独立小表/真实问题任务、12族、手算或独立参考预期；五个质量维度单独显示，保留旧Reviewer接口和“流程评分不代表统计结论百分之百正确”说明。未验证的随机化、独立性、无混杂前提仍显示未验证。

明确未实施：可选P1持久模板/完整口径目录导入；任意多轮追问理解、任意自由公式、跨事实时间关联；未认证的数据库方言。PG/MySQL/MariaDB查询现在连接前明确拒绝，而非把DuckDB解析误作安全认证。历史JSON仅核验脱敏schema/版本/大小/引用，不恢复数据、路径或执行授权。未安装/启动研究平台、未复制上游代码、未接在线LLM/训练/下载模型。

设计与来源：[差距表](upstream_gap_analysis.md)、[实施计划](upstream_improvement_plan.md)、[固定提交与许可证](upstream_references.md)、[指标/澄清](metric_definitions_and_clarification.md)、[SQL策略](sql_policy.md)、[历史/对比](analysis_threads_and_comparison.md)、[任务评估](task_evaluation.md)。

## 2. 保护、环境与独立恢复

修改前白名单快照：`../recovery-backups/insightpilot-agent-0.1.0-source-20260923T115636978648Z.zip`，291文件，SHA256 `23b615a761596e4e353fdf94bd43915db39140ae37ba004c766062f89fa407c9`。包含未提交源码，排除.git/环境/数据/报告/凭据，逐文件校验后解压到reports/upstream/source-before作本轮精确对照。

Windows本机AMD Ryzen 9 9900X、12核24线程，物理内存33,984,663,552字节（31.65GiB）；Python3.14.7、pandas3.0.5、numpy2.5.3、DuckDB1.5.5、Streamlit1.63.0、SQLGlot30.18.0、Chrome153.0.8010.48。完整包版本见本轮results.json/requirements-lock.txt。仅增加纯Python pypdf6.19.0供正式任务评估PDF读回，源自官方PyPI；分析/测试不调用在线模型。

原始基线只读完整性：222个tracked文件哈希、main提交 `2532e4665eda9fe16dee98994691a3e6ddbec0e8`、分支、标签、clean状态与恢复记录一致。新工作项目无旧.git；证据reports/upstream/source-integrity.json。

wheel：`../recovery-backups/upstream-wheel-20260923T125309977613Z/insightpilot_agent-0.1.0-py3-none-any.whl`；SHA256 `546219588f70c0a4ed7401fd5578c8e79ea3b4d6048658c1f1e5a05ff7795d55`。138项Python模块/语义YAML/页面资产逐字节匹配。独立venv、源码目录外的隔离导入、pip check、语义校验和29项task均通过。首次验证命令的-I忽略环境编码导致捕获乱码，已改为显式-X utf8并重跑；原记录与修正记录都保留，产品源码无此乱码。证据reports/upstream/wheel-acceptance-utf8.json。

最终源码快照和独立恢复由 `reports/upstream/source-restore-result.json` 记录准确路径、SHA256、独立环境、每条命令/退出码、全量pytest及四套评估/三个Demo导出结果。该证据与报告留在reports，不纳入源码快照，也不上传。恢复使用新目录和锁依赖，不借用当前.venv或源码导入；快照工具拒绝成员哈希不符、路径逃逸、重复成员、链接或超限展开。

## 3. 测试、评估与数值证据

修改前：355 passed、1 skipped，97.76秒。最终冻结代码：524 passed、1 skipped，115.11秒；JUnit525项、0失败/0错误，见reports/upstream/final-verification/20260923T125256126047Z/pytest.xml。唯一skip为主venv未安装可选langgraph.graph；不是跳过慢测。另在.venv-langgraph实际运行三场景COMPLETED且表一致、preview0查询，见p0a-langgraph.json。

core 5/5、safety 4/4、determinism 2/2；task 29/29、12族。三主Demo CLI均实际导出PDF/Markdown/HTML/Excel/Manifest/ZIP；多表plan-only成功。完整命令退出码保存在同目录results.json。

任务逐族：
|任务族|PASS|FAIL|WARN|
|---|---|---|---|
|不可比单位/口径|2|0|0|
|六类导出绑定|2|0|0|
|加权比率与均值比率|3|0|0|
|去重人数与行数|3|0|0|
|安全作用域与危险分支|2|0|0|
|实验单位/方向/区间|3|0|0|
|维度分支与窗口对比|2|0|0|
|缓存失效与历史不可变|3|0|0|
|订单口径与净/毛收入|3|0|0|
|转化率澄清|2|0|0|
|连接放大与跨事实边界|2|0|0|
|释放与分支归属|2|0|0|

独立预期不是由被测函数自生成；详情含输入、问题、选择、预期状态/指标/数值/容差、必需证据和禁止行为。通过表示这些任务契约成立，不等于所有业务问题统计正确。

39示例本轮最终全部COMPLETED，第一次37/39的失败日志保留。十剧本在精确before源码与现代码两个子进程中运行：55张表、664行、55条结构化证据的数值/证据差异0；完整strict协议仍有33处新增映射/确认/策略身份差异，原exit1与passed=false保留，单列numerical_evidence_compatible=true，不删差异。

核心/会话路径各18份参考文件、117张表，全部列、有序行、嵌套值比较差异0。计数精确，浮点rtol1e-10/atol1e-12，p值atol1e-300。独立实验小表仍每组4用户、方向/点估计/p值/CI/百分点一致。

确有两类旧错误输出被修正：显式mean漏传导致sum，以及显式自定义维度比率直接取均值；新独立预期分别[20,40]、加权10/92与5/20。不能宣称所有旧错误请求数值不变。无效映射/缺实验单位现在明确拒绝或澄清，是安全行为变化。

首轮综合测试的502通过/1跳过/3失败完整保留；修复报告口径真实ID与旧中文章节断言冲突、PDF辅助函数兼容、requirements格式。额外真实AppTest复现自定义实验默认方向冒充确认后修复，并保留首次失败。没有删失败测试、自动更新数值基线或硬编码满分。

## 4. 实际交互闭环与视觉检查

AppTest：收入/多转化率问题→候选默认空→未确认开始0次分析→明确选择→完成；转化率核对cvr=orders/visitors。城市与渠道两个分支、返回已释放父节点、明确不同维度不可比；同指标两个窗口产生带单位的context_differs差异。未提交新问题时PDF/Excel/ZIP仍绑定历史选定run。指纹/画像/分析调用计数在切页、浏览历史、比较、展示模式变化时不增加；未请求不生成报告。自定义实验方向必须明确选，换数据revision/group清除旧选择，内置实验免重问。

安全闭环：中文列名+参数CTE合法，字符串DROP为普通值；嵌套/UNION后续越权拒绝且执行0次；SQLite缺失文件不创建。SQLGlot缺失时失败关闭。相关定向和完整pytest覆盖连接关闭、限流包装、取消及会话隔离。

Chrome与AppTest分开：reports/upstream/browser-accepted/checks.json记录真实城市/渠道/返回、PDF/Excel/ZIP点击下载、console无错误；口径卡computed style标题16px=12pt、正文14px=10.5pt。概览、口径卡、质量五维已人工视觉检查；完整可见的比较提示也已人工视觉检查；截图存browser-visual-final。后台真实浏览器6/6通过：运行时切模式响应0.245秒、取消请求响应0.305秒、分析提交返回0.404秒、运行中释放响应0.379秒；并验证切源不接收旧数据、取消后不自动重启。该耗时是UI响应，不是native步骤完成或RSS完全回收时间，见background-browser/checks.json。截图检查范围是对应视口，不能宣称检查了所有可能滚动位置。首轮定位器误把带图标按钮当作精确文字、格式化选项选择失败的日志保留，已按实际run标识和可访问名称修正；不是静默略过步骤。

PDF中文、实验完整样本量/p值/CI/百分点与口径来源经读回和渲染检查，具体页面范围见task_evaluation.md。单PDF不调用其它生成器，ZIP内PDF与同run已生成PDF一致；未把原始数据或凭据打入包。源数据数值不为图表抽样替换统计。

## 5. 性能方法与数据规模

所有样本固定seed42，同机同代码入口，前后各3次；主场景standard，另自定义10万/50万/100万行。直接调用与会话路径各18个独立子进程，导入、加载、准备、统计、结果构建、图表和六导出分段记录。首次分析时间从数据准备完成后开始；首次使用的总等待还包含加载/准备/导入。热重复是已有会话结果缓存查找，不能当作重新算全表的速度。

RSS为20ms采样进程WorkingSetSize，并记录Windows进程生命周期PeakWorkingSetSize，包含native内存；不是tracemalloc、不是所有进程总和、不是永久缓存占用。缓存另用深层大小估计/唯一对象计数，可能与分配器实际RSS不同。浏览器另测点击到脚本完成+指定UI出现+两个animation frame，并记录首次响应、WebSocket字节及长任务；这些不是AppTest耗时或网络端到端吞吐。三次只报中位数/范围，不宣称P95。

数据规模（每表行列、字符串比例和维度基数详见原始JSON）：
|场景|表数|合计行数|最大表行数|DataFrame深层MiB|
|---|---|---|---|---|
|标准交易|6|727070|316035|204.24|
|标准内容|6|215242|108042|58.52|
|标准直播|7|294095|54000|64.77|
|自定义全量100000|1|100000|100000|9.38|
|自定义全量500000|1|500000|500000|46.89|
|自定义全量1000000|1|1000000|1000000|93.78|

会话后端：秒，中位数[最小,最大]；RSS列为三次采样峰值的最大MiB。
|场景|首次分析前|首次分析后|重复分析后|峰值RSS前→后|
|---|---|---|---|---|
|标准交易|0.6055 [0.6009, 0.6059]|0.6169 [0.6050, 0.6172]|0.0000 [0.0000, 0.0000]|562.96→563.46|
|标准内容|0.1075 [0.1071, 0.1088]|0.1098 [0.1092, 0.1134]|0.0000 [0.0000, 0.0000]|344.71→346.25|
|标准直播|0.2727 [0.2677, 0.2785]|0.2773 [0.2732, 0.2797]|0.0000 [0.0000, 0.0000]|332.41→333.56|
|自定义全量100000|0.0685 [0.0684, 0.0710]|0.0712 [0.0688, 0.0719]|0.0000 [0.0000, 0.0000]|268.68→269.29|
|自定义全量500000|0.2194 [0.2172, 0.2336]|0.2229 [0.2187, 0.2310]|0.0000 [0.0000, 0.0000]|389.45→388.97|
|自定义全量1000000|0.4070 [0.4055, 0.4106]|0.4092 [0.4049, 0.4276]|0.0000 [0.0000, 0.0000]|535.48→536.10|

阶段拆分：标准交易会话路径，秒、中位数[最小,最大]。加载只生成/读取数据，准备包含画像/质量/精确指纹。
|阶段|前|后|
|---|---|---|
|imports|1.1576 [1.1532, 1.1944]|1.1423 [1.1408, 1.1426]|
|data_loading|0.1707 [0.1697, 0.1733]|0.1733 [0.1705, 0.1787]|
|dataset_preparation|0.8620 [0.8576, 0.8799]|0.8899 [0.8898, 0.9025]|
|analysis_first|0.6055 [0.6009, 0.6059]|0.6169 [0.6050, 0.6172]|
|chart_materialize_requested|0.1305 [0.1303, 0.1312]|0.1300 [0.1295, 0.1332]|
|chart_serialization|0.0039 [0.0038, 0.0041]|0.0039 [0.0039, 0.0040]|
|export_pdf|0.2305 [0.2256, 0.2307]|0.2382 [0.2378, 0.2397]|
|export_markdown|0.0339 [0.0332, 0.0344]|0.0353 [0.0352, 0.0354]|
|export_html|0.2345 [0.2344, 0.2431]|0.2378 [0.2359, 0.2383]|
|export_excel|0.2557 [0.2475, 0.2764]|0.2647 [0.2644, 0.2691]|
|export_manifest|0.0018 [0.0018, 0.0018]|0.0024 [0.0024, 0.0024]|
|export_zip_assembly|0.0622 [0.0619, 0.0655]|0.0622 [0.0615, 0.0637]|
|export_zip_cold_total|0.8177 [0.8109, 0.8464]|0.8441 [0.8375, 0.8447]|

不含解释器导入时，标准交易最慢三项顶层业务阶段为：数据准备0.8899秒、冷ZIP全部依赖生成0.8441秒、首次分析0.6169秒。ZIP冷值是各格式生成加压缩；用户先生成PDF/Excel后点ZIP的实际热复用耗时另列。嵌套function_calls进一步分开画像、全量指纹、统计与结果协议，并保留调用次数，不能把嵌套耗时再相加当总时长。

100万行一次采样细分：画像0.0523秒、质量检查0.0360秒、原始数据精确指纹0.3071秒；统计0.1551秒、结果构建0.2399秒。分析阶段7次指纹针对小结果证据，不是重新扫描100万行源表，合计0.0049秒。重复分析没有新增这些调用。所有18份完整function_calls与workflow_spans可复核；数据没有被静默截断。

浏览器前后各3个隔离context，同一预热服务；先实际standard分析1次、0导出、释放预热会话。秒、中位数[最小,最大]：

标准场景：
|操作|前|后|
|---|---|---|
|initial_navigation|2.6050 [2.5291, 2.6273]|2.5600 [2.5348, 2.5834]|
|analysis_first|1.6969 [1.6896, 1.7061]|1.6926 [1.6726, 1.7129]|
|analysis_repeat|0.2984 [0.2592, 0.3129]|0.2965 [0.2951, 0.3154]|
|results_tab|0.3331 [0.3163, 0.3480]|0.3509 [0.3320, 0.3680]|
|visual_tab|0.7631 [0.7526, 0.8557]|0.7761 [0.7688, 0.8018]|
|overview_tab|0.3135 [0.2958, 0.3223]|0.3329 [0.2963, 0.3339]|
|professional_mode|0.3133 [0.2983, 0.3135]|0.3294 [0.3142, 0.3329]|
|export_tab|0.2777 [0.2763, 0.2971]|0.2959 [0.2600, 0.2990]|
|generate_pdf|0.5253 [0.5213, 0.5416]|0.5566 [0.5427, 0.5581]|
|generate_excel|0.4704 [0.4498, 0.5434]|0.5253 [0.5079, 0.5424]|
|generate_zip|0.6683 [0.6493, 0.7356]|0.6813 [0.6808, 0.6957]|
|pdf_download|0.1210 [0.1178, 0.1971]|0.1203 [0.1201, 0.1768]|

大型场景：
|操作|前|后|
|---|---|---|
|initial_navigation|2.5786 [2.5350, 3.0725]|2.5803 [2.5588, 3.0735]|
|analysis_first|2.8216 [2.7767, 3.2843]|3.3107 [2.8549, 3.3339]|
|analysis_repeat|0.2980 [0.2813, 0.2984]|0.2931 [0.2800, 0.2970]|
|results_tab|0.3326 [0.3311, 0.3509]|0.3485 [0.3330, 0.3492]|
|visual_tab|0.8018 [0.7594, 0.8306]|0.8088 [0.8054, 0.8100]|
|overview_tab|0.3155 [0.2965, 0.3311]|0.3327 [0.3159, 0.3491]|
|professional_mode|0.2968 [0.2943, 0.3119]|0.3317 [0.3133, 0.3320]|
|export_tab|0.2755 [0.2593, 0.2953]|0.2967 [0.2966, 0.3142]|
|generate_pdf|0.5239 [0.5072, 0.6354]|0.5744 [0.5579, 0.5750]|
|generate_excel|0.4734 [0.4524, 0.4880]|0.5222 [0.5119, 0.5264]|
|generate_zip|0.6871 [0.6473, 0.7063]|0.7029 [0.7002, 0.8350]|
|pdf_download|0.1207 [0.1188, 0.1733]|0.1217 [0.1206, 0.1979]|

两条后端路径和浏览器全部关键中位数未同时超过20%且绝对0.2秒退化门槛。不能因此宣称所有操作更快：大型浏览器首次完成2.8216→3.3107秒（+17.3%、+0.4890秒）；标准切明细0.3331→0.3509秒，PDF0.5253→0.5566秒、Excel0.4704→0.5253秒。实际范围保留，未将0.5秒级轮询/调度波动直接归因某个函数；本轮目标是能力增加且无规定门槛的持续性能回归。

内存预算不变：原始数据1份/1GiB、完整结果1份/256MiB（其中扣512KiB给历史）、导出6项/64MiB，TTL30分钟；不新增无隔离全局数据缓存、不写临时磁盘缓存、不增并发。显式导出生成过程有临时内存，预算限制保留对象，不能保证进程RSS立刻下降；Streamlit媒体下载引用和Python/native分配器回收也不等同删除会话引用。

## 6. 后台任务和当前限制

继续使用已有受限后台管理器（全局2、会话1），没有新增分布式架构。UI线程管理session_state；worker只处理不可变请求和受控数据引用，不调用Streamlit控件。完成时验证owner/revision/request/node，用户切历史或改参数时旧任务不能覆盖新结果。进度来自已进入的真实阶段，不伪造百分比。

取消是协作式：排队任务可取消，运行中的pandas/native SQL步骤在边界或既有超时后返回才释放引用；不承诺立即强杀线程或立即归还全部RSS。释放会话会取消/失效旧引用；后台资源finally关闭。默认后台、同步兼容、晚到结果、跨会话与资源清理有完整pytest及真实浏览器检查。大型数据准备仍是首次真实全量成本；结果/报告新增口径和证据也有少量序列化开销。

当前仍无任意长期历史大表库、跨进程共享用户缓存或自动磁盘缓存。内置交易visitors是旅程，不改名伪称去重用户。独立row声明不等于证明随机化。比较摘要有128值上限并明确范围；完整统计从未用该上限截断。对未支持分析明确拒绝，不能自动退化无关剧本再标PASS。

## 7. 已实际使用的本机命令

在PowerShell项目根目录执行；新输出目录避免覆盖旧记录。恢复/备份所用精确带时间戳命令见source-restore-result.json，wheel命令见wheel-acceptance-utf8.json。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m streamlit run app/ui_streamlit.py --server.address 127.0.0.1 --server.port 8506 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
# 在另一个PowerShell中复测；下方工具均已于本轮实际执行。
.\.venv\Scripts\python.exe scripts/verify_project.py --output-dir reports/upstream/final-verification
.\.venv\Scripts\python.exe -m insightpilot.evaluation.cli --suite task --output-format json
.\.venv-langgraph\Scripts\python.exe -B scripts/check_langgraph.py --output reports/upstream/langgraph-new-run.json
.\.venv\Scripts\python.exe scripts/benchmark_performance.py --output-dir reports/upstream --label after-raw --repeat 3
.\.venv\Scripts\python.exe scripts/benchmark_performance.py --output-dir reports/upstream --label after-session --session-path --repeat 3
.\.venv\Scripts\python.exe scripts/benchmark_browser.py --url http://127.0.0.1:8506 --ui-version p1 --output reports/upstream/browser-retest/standard.json
.\.venv\Scripts\python.exe scripts/benchmark_browser.py --url http://127.0.0.1:8506 --ui-version p1 --scale large --output reports/upstream/browser-retest/large.json
.\.venv\Scripts\python.exe scripts/check_upstream_browser.py --url http://127.0.0.1:8506 --output reports/upstream/browser-visual-retest
.\.venv\Scripts\python.exe scripts/check_browser_background.py --url http://127.0.0.1:8506 --output reports/upstream/background-retest/checks.json
.\.venv\Scripts\python.exe scripts/compare_performance.py --before reports/upstream/before-session-20260923T115849526016Z --after reports/upstream/after-session-20260923T124856004205Z --output reports/upstream/session-recheck.json
.\.venv\Scripts\python.exe -B scripts/compare_playbook_snapshots.py --before reports/upstream/source-before/insightpilot-agent --confirm-experiment-fixture --output reports/upstream/playbook-new-run.json
```

十剧本严格协议比较预期仍返回1并保留33处协议差异；需同时读取numerical_evidence_compatible，不能把命令非零掩盖成全通过。性能比较前清空其他计算负载，使用相同锁依赖/seed/场景/预热；基线文件来自本轮修改前快照而非旧验收报告。报告/上传数据/数据库/凭据不提交或上传。
