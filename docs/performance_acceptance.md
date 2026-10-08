# 性能专项最终验收（0.1.0）

生成时间：2026-09-07T11:13:12.812566+00:00。依据实际读取的 `D:\InsightPilot Agent\PERFORMANCE_SPEC.md.md` 执行。先建立基线、保留性能前源码，再完成P0；P0大型源准备仍阻塞5.755秒后才追加P1。项目版本保持0.1.0，没有发布或Git写入。

## 最慢三个原环节

标准交易首次分析，3次新进程中位数；下列函数耗时包含子调用，不能相加为总耗时。

|环节|优化前秒|最终秒|解释|
|---|---:|---:|---|
|完整内容指纹|1.4971|0.6610|原始直接调用19→13次；页面快照摄入一次，后续复用精确指纹。|
|数据库准备|1.2781|0.0693|旧_safe_engine提前注册所有表；最终此列为实际物理注册span，仅注册SQL需要的表，连接/查询另计。|
|结果构建|0.7398|0.5972|含统计结果包及图表，保留完整统计与证据。页面路径延迟图表。|

原切页的分析调用本来就是0；实测重复工作是重新解析上传文件、完整数据指纹、隐藏图表和详情构建。基线不能被改写为“以前切页每次重跑分析”。图表构造、序列化、Reviewer、真实SQL、画像和所有导出均有独立记录，详见下列原始JSON及 `core-p0-measured.md`。

## 同口径核心性能

两侧均为默认eager API，保留原图表/Markdown行为；首次和重复均真正计算。每例3个独立Python进程，表中中位秒。加载/导入/导出不混入分析耗时。

|数据|首次 前→后|再次真重算 前→后|峰值RSS 前→后 MiB|
|---|---:|---:|---:|
|标准交易|4.3352 → 1.6711|4.2077 → 1.5996|701.2 → 552.3|
|标准内容实验|1.0138 → 0.3805|0.9700 → 0.3534|407.5 → 345.6|
|标准直播|1.4404 → 0.6804|1.4013 → 0.6328|359.4 → 328.1|
|100,000行|0.2668 → 0.1135|0.2516 → 0.1101|286.8 → 265.4|
|500,000行|1.0213 → 0.4552|1.0365 → 0.4415|403.8 → 373.8|
|1,000,000行|1.9798 → 0.8592|1.9374 → 0.8483|564.6 → 520.6|

页面会话路径另测：一次加载、一次受控快照/画像/完整指纹，分析只构造完整结构化结果。再次同配置提交命中同一结果；不能把微秒级缓存查找说成真实浏览器等待。

|数据|生成/读入秒|快照准备秒|首次统计秒|重复缓存查找秒|
|---|---:|---:|---:|---:|
|标准交易|0.1855|0.9318|0.6493|0.000006|
|标准内容实验|0.1081|0.2551|0.1165|0.000005|
|标准直播|0.1470|0.2605|0.2955|0.000006|
|100,000行|0.0459|0.0376|0.0753|0.000005|
|500,000行|0.2279|0.2153|0.2412|0.000005|
|1,000,000行|0.4483|0.4194|0.4502|0.000010|

## 真实浏览器

Chrome 151.0.7922.173，独立无登录上下文；同一暖服务，各3次。计时至Streamlit完成事件、所需控件/图表可见及两次动画帧，包含浏览器自动化等待；P1另外记录首个UI完成事件的响应，不能替代任务完成。首次Plotly等待实际图形可见。范围及WS传输字节保存在JSON。

|标准交易操作|优化前秒|P0秒|最终P1秒|
|---|---:|---:|---:|
|导航至数据就绪|1.9911|2.0104|2.5036|
|首次分析真正完成|6.2842|0.9508|1.6096|
|重复同配置提交|5.6706|0.2292|0.2589|
|切结果明细|1.5134|0.3129|0.3442|
|切分析概览|1.3135|0.2638|0.2941|
|首次打开图表|1.3135|1.2293|0.7645|
|切报告导出|1.3302|0.2460|0.2765|
|下载已有PDF|0.1805|0.1129|0.1328|

标准交易首次提交约0.295秒返回可操作页面，结果于1.610秒完成。初次导航较P0更慢，首次导航加首次分析的合计为8.275→4.113秒，避免把摄入工作转移后隐藏。

|大型交易操作|P0阻塞/完成秒|P1首个UI响应秒|P1真正完成秒|
|---|---:|---:|---:|
|选择大型源|5.7551|0.2960|6.6516|
|首次分析|2.4485|0.3964|3.2233|

P1增加轮询和结果交接，总完成时间比P0更长；收益是计算期间页面可操作，不是后台计算自动加速。独立真实大型任务检查：模式切换0.223秒、取消请求0.286秒、分析提交0.228秒、释放页面引用0.445秒；6项检查通过、观察到23条不同状态/阶段消息、0页面错误。运行中切大型→小型、取消不自动重启、显式刷新恢复、分析中释放后旧结果不采纳均已实测。

## 六类导出

下表同样使用标准交易默认eager结果，3次中位秒；各格式独立调用。ZIP冷总耗时是PDF/Markdown/HTML/Excel/Manifest及组包之和，不能只用组包时间冒充完整ZIP。

|格式|优化前秒|最终秒|
|---|---:|---:|
|PDF|0.3108|0.2397|
|Markdown|0.0866|0.0353|
|HTML|0.1882|0.1455|
|Excel|0.3236|0.2622|
|运行清单JSON|0.0019|0.0019|
|ZIP仅组包|0.0560|0.0656|
|ZIP冷总计|0.9626|0.7503|

最终页面请求PDF/Excel/ZIP分别约0.521/0.452/0.662秒；这里ZIP复用了先生成的PDF和Excel，不能与冷ZIP直接作加速比。旧页面只有一次准备全部格式的入口（中位2.396秒），没有对应的单格式页面基线。P0→P1浏览器等待顺序因异步事件调整，因此单格式性能变化以同口径后端表为准。

原API已经能独立生成PDF，旧ZIP也能复用已准备文件；本次把每格式请求与有界缓存接入页面。PDF第一，未请求不生成报告；下载使用现有bytes，六次最终浏览器PDF下载均为0新增script_finished、0新增WS字节。测试确认只点PDF不会调用HTML/Excel/ZIP，重复请求命中，ZIP内PDF与已缓存PDF逐字节相同，源结果/trace不被导出器修改。

三标准场景六种文件完成读回；PDF共31页（16/4/11）已渲染目视检查，中文与分页正常。PDF最多20表、每表40行，HTML每表100行、Excel/CSV每表100,000行等历史导出预览限制均显示说明，未截断统计输入。外部PDF阅读器的字体替换表现未全部验证。

## 数据、机器和内存方法

Windows，AMD Ryzen 9 9900X，12物理核/24逻辑核，内存33,984,663,552字节（约31.65GiB）。Python3.14.7、pandas3.0.5、numpy2.5.3、duckdb1.5.5、streamlit1.63.0、plotly7.0.0、reportlab5.0.1、scipy1.18.1、openpyxl3.1.5；全部依赖版本保存在运行JSON/最终verification结果。

固定seed42；标准交易6表（订单明细316,035行，日表36,000行，逻辑DataFrame深度估计204.2MiB），内容6表、直播7表。大行数自定义表10列，100k/500k/1m行，字符串列30%，日期180值、城市16、渠道6、设备3；所有统计用全量数据。百万行通用分析路径与多表交易路径不同，不能只用行数排名。

补充大型交易6表：订单明细1,283,484行×27列，日表146,000行×39列；逻辑深度估计826.6MiB。单新进程会话路径最大RSS1535.7MiB，加载0.731秒、快照准备4.253秒、首次统计2.137秒。

RSS每20ms使用Windows GetProcessMemoryInfo采样工作集，并另记操作系统PeakWorkingSetSize，包含原生分配；不使用tracemalloc代表总内存。表格另记memory_usage(deep=True)、行列数、基数、字符串比例；缓存只在插入/摄入时估算大小，共享对象引用去重。RSS不是会话归属内存；本报告未用Chrome内存或多会话暖服务RSS替代独立进程对照。3次报告中位/最小/最大，不能称p95。

文件摄入补充：CSV100k×10、Excel选中sheet20k×10（另有50行参考sheet），BytesIO模拟数据，3次。解析中位CSV0.0814→0.0726秒，Excel0.8330→0.7981秒；6次完整内容指纹完全相同。解析库未重写，这一小差异不作为主要优化收益。

## 有界缓存与后台边界

默认各会话：数据1项/1024MiB（含保留上传bytes），结果1项/256MiB，单图16MiB、当前表行号16MiB、单表CSV64MiB、六格式导出合计64MiB、开发JSON8MiB；独立保留限额合计1448MiB，TTL1800秒。图表3000点/20序列仅限制展示，表格50/100/200/500行按页，先全量稳定排序/过滤。预算明确拒绝，不静默截断或落盘。

任务管理器全局2执行槽、每会话1任务，无无界队列；8条记录、已完成待接收对象合计2GiB。源任务/分析任务分别受数据/结果预算约束。随机owner隔离，只有匹配owner、task_id、配置key、dataset revision才能转移结果。工作线程不访问Streamlit或session_state；页面fragment每0.5秒显示真实阶段/已用时，空闲不定时轮询。

取消只请求协作停止：当前pandas/NumPy/SciPy/解析/SQL原生调用返回后检查，期间仍持必要引用。原SQL安全超时独立保留，不将取消误称即时interrupt。任务完成、失败、取消、接收、释放和TTL均有引用回收测试；守护线程最多每30秒检查任务TTL，即使没有浏览器访问也清理。运行任务过期先取消，仍等当前步骤返回；close(wait=False)不保证Python进程立刻退出。

页面缓存每次执行统一清理过期的隐藏展示/导出；数据/结果访问检查TTL。主页面完全闲置时没有额外计时线程逐项清理这些会话缓存，宿主会话断连生命周期和下次访问释放引用。活跃分析保活其绑定数据修订。已消费数据库快照过期/丢失任务不会自动重查SQL或重跑分析；需要明确重试。

改变数据源取消旧工作并只准备当前选择；原生取消尚未结束时新分析明确显示“本次未提交，结束后再次点击”，不谎称排队成功。清空上传取消任务并清理原bytes。INSIGHTPILOT_UI_SYNC=1是显式同步兼容入口，CLI保持同步。缓存预算不是RSS硬上限，原生临时数组、解析、图表/报告、浏览器内存和取消过渡期重叠可能超过保留估计；释放引用不保证操作系统马上降低RSS。

## 正确性和实际验收结果

- 最终全量pytest：**355 passed、1 skipped、0 failed、0 error，113.12秒**，见final-pytest.log/xml。唯一跳过是真实LangGraph环境未安装于默认venv；已在独立已安装环境实际执行新增7项，全通过。
- 第一次全量运行354 passed/1 failed/1 skipped，旧test_export_order依赖源码字面量。保留原失败日志，改为AppTest实际验证反序生成缓存时仍按PDF、Markdown、HTML、Excel、JSON、ZIP显示六按钮，再重跑完整pytest；未删除测试或更改统计expected。
- 本次最终core评估：5项通过、0失败，得分1.0。
- 本次最终safety评估：4项通过、0失败，得分1.0。
- 本次最终determinism评估：2项通过、0失败，得分1.0。
- 依赖pip check、语义验证、3个CLI场景及六类导出、多表只读计划预览全部退出0。
- 默认核心和会话路径分别18份/117表对照优化前：全部列、行、有序值及嵌套证据差异0。计数精确；浮点rtol1e-10/atol1e-12，p值atol1e-300；没有更新expected。
- 十剧本在两套独立源码导入进程再次比较：55表、664行、55条结构化证据，输入指纹一致、数值/证据差异0。20处图表新增displayed_rows/total_display_rows展示元数据已单独记录，strict_payload_identical=false，不能宣称所有payload相同。
- 16项P0 UI回归、12项真实后台UI回归及14项任务管理器回归保留于全量套件；旧UI意图使用显式同步设置，后台套件明确清除此设置并运行真实线程。覆盖切页不加载/画像/指纹/分析、上传内容与编码/分隔符/sheet变化、真实分页/单图、未请求导出不生成、任务取消/异常/过期/错误结果重试/旧配置覆盖保护/真实守护清理。

## 尚未改善及限制

冷Python导入仍约1.2秒，首次浏览器资源加载、首次大Excel解析及完整内容指纹仍需时间；没有用抽样统计或近似指纹替代。完整质量扫描仍保留，新增result_quality_scan计时便于继续观察。P1总完成时间比P0更长，改善的是响应和取消；本机最大实测是上述大型场景及百万行通用表，未承诺任意数据、远程数据库或更多并发用户都有同样耗时。

十剧本回归证明优化前后兼容，不代替独立统计真值。core-p0-measured.md记录周期/因果/数据画像等独立真值及部分cohort/事件窗口边界尚未穷尽的覆盖缺口。没有扩展为分布式架构，没有新增模型训练或在线LLM。

## 原始记录与复测命令

主要目录：

- 修改前：`reports\performance\baseline-valid-20260907T092715031540Z`；核心最终：`reports\performance\final-raw-20260907T103223707483Z`。
- 会话最终：`reports\performance\final-session-20260907T104133902469Z`；大型：`reports\performance\final-large-session-20260907T104228983638Z`。
- 浏览器：`reports/performance/baseline-browser-valid`、`p0-browser-valid`、`final-browser`；真实任务检查：`final-background-browser`。
- 最终pytest：`reports/performance/final-pytest.log/xml`；最终评估/CLI：`reports/performance/final-verification/20260907T105007018987Z`（其中第一次pytest失败已由独立最终pytest替代，日志不删除）。
- 导出读回/视觉：`reports/performance/export-verification-p0`；P1只改变执行调度，报告产品代码此后未改。
- 源码关系：性能前备份`../recovery-backups/insightpilot-agent-0.1.0-source-20260907T090942312118Z.zip`，SHA256 `098bfea82d1a5d522d307c34d14b1dae4c88b6b547c141d7ab8c6a0120154388`。

首次RSS探针HANDLE声明错误、下载按钮带图标导致精确名称等待失败、十剧本子进程相对输出路径失败均保留在各initial/failed日志中；修复探针后重跑成功，未用失败数据作为成绩。

以下命令在现有项目环境执行。性能命令按顺序运行，勿与全量测试或其他CPU任务并行；脚本创建带时间戳的新目录并输出该路径。浏览器依赖本机已安装Playwright/独立Chrome，不是分析的默认依赖。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8 = '1'
$perfPython = '.\.venv\Scripts\python.exe'
$perfStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
& $perfPython scripts/benchmark_performance.py --label recheck-raw --repeat 3
& $perfPython scripts/benchmark_performance.py --label recheck-session --repeat 3 --session-path
& $perfPython scripts/benchmark_performance.py --label recheck-large --case transaction --rows 0 --scale large --repeat 3 --session-path
& $perfPython scripts/benchmark_ingestion.py --output "reports/performance/ingestion-$perfStamp.json"
& $perfPython scripts/compare_playbook_snapshots.py --output "reports/performance/playbooks-$perfStamp.json"
& $perfPython scripts/verify_project.py --output-dir reports/performance/reverification
& ./.venv-langgraph/Scripts/python.exe -m pytest tests/test_performance_task_core.py
```

对照核心时将新输出目录传给`--after`。下列命令直接对本次保存的最终记录复核；复测时替换after目录即可。

```powershell
& $perfPython scripts/compare_performance.py --before reports/performance/baseline-valid-20260907T092715031540Z --after reports/performance/final-raw-20260907T103223707483Z --output "reports/performance/comparison-$perfStamp.json"
& $perfPython scripts/benchmark_performance.py --label before-recheck --repeat 3 --source-root reports/performance/source-before/insightpilot-agent
```

真实浏览器另开一个终端启动当前服务，再在第二个终端运行检查；同步兼容复测时显式设置`$env:INSIGHTPILOT_UI_SYNC = '1'`后重启服务，默认P1复测先删除该环境变量。

```powershell
Remove-Item Env:INSIGHTPILOT_UI_SYNC -ErrorAction SilentlyContinue
& $perfPython -m streamlit run app/ui_streamlit.py --server.address 127.0.0.1 --server.port 8503 --server.headless true --server.fileWatcherType none --browser.gatherUsageStats false
# 在第二个同目录终端设置上面的perfPython/perfStamp变量，然后执行：
& $perfPython scripts/check_browser_background.py --url http://127.0.0.1:8503 --output "reports/performance/browser-check-$perfStamp/checks.json"
& $perfPython scripts/benchmark_browser.py --ui-version p1 --url http://127.0.0.1:8503 --output "reports/performance/browser-$perfStamp/standard.json"
& $perfPython scripts/benchmark_browser.py --ui-version p1 --url http://127.0.0.1:8503 --scale large --output "reports/performance/browser-$perfStamp/large.json"
```

原始恢复基线source-original的main仍为2532e4665eda9fe16dee98994691a3e6ddbec0e8；222文件、6标签及备份哈希核验未变，工作项目没有.git。最终核验与变更清单见source-integrity.json/performance-change-inventory.json。未git add/commit/tag/push，未修改旧远程、全局凭据或证书设置；运行产物仅在本机reports下，没有上传。
