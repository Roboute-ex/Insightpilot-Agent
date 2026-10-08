# 工作台改造性能验收（2026-09-29）

## 测量范围与机器

在同一台 AMD Ryzen 9 9900X（12核24线程）、33,984,663,552字节物理内存、Windows 11 build 26100 上测量。每个前后阶段各3次全新 Python 3.14.7 进程，使用 standard 交易场景、seed=42；源数据指纹逐表相同。首次准备与首次分析分开。计时使用 perf_counter；AppTest 设置同步执行用于区分计算和渲染，不把该探针任务提交为0描述成真实后台行为。真实异步生命周期由独立浏览器验收覆盖。

修改前使用本轮源码快照解压副本，包含未提交源码：`insightpilot-agent-0.1.0-source-20260929T111238207905Z.zip`，335文件，SHA256 `6ccf7589fa5e7b3d7cfc7e9aee9e89db559162873c0adb48085a84122cf89b13`。只读恢复基线 source-original 未改动。正式后测时暂停其他 CPU 验证；之后的 CLI 配置透传与非交易空卡展示修复不影响交易测量配置，原4类非空内容和顺序保留。

依赖实测：insightpilot-agent 0.1.0；pandas 3.0.5；numpy 2.5.3；duckdb 1.5.5；streamlit 1.63.0；plotly 7.0.0；scipy 1.18.1；reportlab 5.0.1；openpyxl 3.1.5；sqlglot 30.18.0。

|数据表|行数|列数|
|---|---:|---:|
|users|20,000|7|
|merchants|3,000|3|
|daily_metrics|36,000|39|
|transaction_detail|316,035|27|
|orders|316,035|27|
|traffic_events|36,000|19|

缓存统计的源数据估计总量为214,381,833字节；这不是操作系统RSS。所有统计使用完整范围，图表显示点上限与统计范围分开。

## 前后耗时

单位秒，格式为中位数 [最小值, 最大值]，均为本轮3次实测。首次分析后的页面工作量有意改变：新版直接显示两张已有聚合关键图和主表；旧版只显示简短摘要。方法目录和历史从折叠区改成主导航，所以对应用户操作相同，但HTML不完全相同。

|阶段|修改前|修改后|
|---|---:|---:|
|首次准备（含六表准备与界面）|1.8382 [1.8321, 1.8635]|1.8178 [1.8044, 1.8390]|
|修改问题、更新建议|0.0298 [0.0291, 0.0321]|0.0378 [0.0363, 0.0385]|
|进入全部方法目录|0.0312 [0.0307, 0.0335]|0.0343 [0.0339, 0.0353]|
|返回工作台|0.0258 [0.0253, 0.0259]|0.0339 [0.0332, 0.0362]|
|首次分析及默认结果渲染|0.6652 [0.6627, 0.6671]|0.7554 [0.7552, 0.7608]|
|相同请求复用结果及默认渲染|0.0322 [0.0316, 0.0351]|0.1222 [0.1196, 0.1323]|
|明细页|0.0360 [0.0356, 0.0374]|0.0420 [0.0412, 0.0454]|
|选择明细表|0.0400 [0.0382, 0.0405]|0.0456 [0.0436, 0.0487]|
|设置每页50行|0.0358 [0.0352, 0.0368]|0.0423 [0.0412, 0.0430]|
|实际翻到第2页|0.0336 [0.0321, 0.0354]|0.0392 [0.0383, 0.0404]|
|进入图表页|0.1510 [0.1465, 0.1632]|0.0537 [0.0535, 0.0545]|
|切换已有图表|0.0511 [0.0503, 0.0513]|0.0535 [0.0531, 0.0551]|
|返回结论页|0.0307 [0.0306, 0.0326]|0.0911 [0.0881, 0.0915]|
|进入历史|0.0312 [0.0301, 0.0320]|0.0456 [0.0453, 0.0492]|
|返回结果|0.0301 [0.0297, 0.0303]|0.0492 [0.0473, 0.0504]|
|进入报告页|0.0269 [0.0261, 0.0273]|0.0322 [0.0319, 0.0353]|
|生成单份PDF|0.3261 [0.3240, 0.3268]|0.3328 [0.3316, 0.3391]|
|生成单份Excel|0.2704 [0.2693, 0.2745]|0.2788 [0.2782, 0.2828]|
|冷ZIP（含依赖生成）|0.8685 [0.8617, 0.8889]|0.8767 [0.8672, 0.9492]|

首次分析增加0.0903秒，相同请求的结果复用增加0.0900秒；新增默认图表和主表渲染是可见工作量增加，不能宣称这两项提速。结果复用仍然不执行分析或统计。返回概览增加约0.0604秒。首次准备、冷ZIP和首次分析仍是上述UI过程最慢的三个阶段。图表页耗时下降，因为默认概览已使用已有图表缓存；不是减少统计范围。

PDF与Excel分别显式生成；测冷ZIP前只清理本会话导出缓存，保留数据及结果缓存，计入所有依赖格式重新生成。未把仅ZIP拼装耗时当成完整报告包成本。

新增导航单列：进入数据探索 0.0314 [0.0308, 0.0329] 秒，返回工作台 0.0313 [0.0305, 0.0321] 秒，没有修改前等价操作。

## 调用次数与数值一致性

三次结果一致：首次数据准备加载1次、六表画像/映射6次、源表完整指纹6次；首次分析 workflow入口1次、路由分析1次、SQL1次、结果表指纹7次，源表重新指纹0次。修改前后这些次数相同。首次计算后结果重用、目录、历史、分页、图型切换、建议更新均不增加源表加载、画像、完整指纹、统计或分析SQL调用。轻量prepare_analysis_request允许更新建议，不能将其误计为执行分析。

|操作|分析入口|分析SQL|源表完整指纹|请求导出|
|---|---:|---:|---:|
|首次分析|1|1|0|0|
|相同请求复用|0|0|0|0|
|方法目录 / 主导航 / 历史 / 分页 / 切图（各次）|0|0|0|0|
|请求PDF|0|0|0|1|
|请求Excel|0|0|0|1|
|请求冷ZIP|0|0|0|6（ZIP及5个依赖）|

7张基线表逐项验证字段和数值一致：`metric_comparisons`、`anomalies`、`dimension_contributions`、`evidence`、`recommendations`、`data_quality`、`funnel_decomposition`。本轮未请求任何报告时生成次数为0。真实翻页使用76行的dimension_contributions，先显式改为50行/页，再翻第2页。

## 内存与预算

由Windows进程工作集API每20ms采样RSS，另保留操作系统进程生存期 PeakWorkingSetSize；RSS包括Python、原生库和短期分配，未使用tracemalloc代替。20ms采样可能漏掉更短峰值，不能将其当内存硬限制。

|采样RSS峰值（MiB）|中位数|最小值|最大值|
|---|---:|---:|---:|
|修改前|578.99|578.60|581.85|
|修改后|578.36|578.34|580.78|

预算前后相同：数据1份/1GiB，完整结果1份/256MiB（其中历史预留512KiB不额外增加），导出6份/64MiB，闲置1800秒过期；图表最多3000点、20系列，默认表格100行/页；DuckDB4线程与1024MiB限制不变。未新增全局数据缓存、磁盘缓存或任务并发。单次样本实际结果缓存943,689字节；RSS不是这些预算的简单总和。

## 新探索的全量计算成本

以下每种3次全新进程，同一daily_metrics 36,000行。分布使用orders；分组按city汇总orders；二维透视按city/channel汇总orders，均显式确认口径后提交。它们是新的查询计算，不与旧静态切页比较。

|请求|阶段|秒：中位数 [最小, 最大]|
|---|---|---:|
|distribution|initial_data_ready|1.8415 [1.8093, 1.8539]|
|distribution|exploration_navigation|0.0354 [0.0344, 0.0359]|
|distribution|configure_view|0.0311 [0.0300, 0.0340]|
|distribution|explicit_exploration_execution|0.5698 [0.5546, 0.5741]|
|distribution|existing_result_chart_page|0.0525 [0.0516, 0.0537]|
|distribution|existing_result_chart_style|0.0424 [0.0420, 0.0447]|
|grouped|initial_data_ready|1.8098 [1.7967, 1.8103]|
|grouped|exploration_navigation|0.0343 [0.0342, 0.0348]|
|grouped|configure_view|0.0309 [0.0309, 0.0314]|
|grouped|explicit_exploration_execution|0.5762 [0.5694, 0.5859]|
|grouped|existing_result_chart_page|0.0535 [0.0517, 0.0565]|
|grouped|existing_result_chart_style|0.0523 [0.0515, 0.0531]|
|pivot|initial_data_ready|1.8630 [1.8217, 1.8645]|
|pivot|exploration_navigation|0.0341 [0.0341, 0.0347]|
|pivot|configure_view|0.0317 [0.0314, 0.0323]|
|pivot|explicit_exploration_execution|0.6145 [0.6029, 0.6247]|
|pivot|existing_result_chart_page|0.0488 [0.0462, 0.0492]|
|pivot|existing_result_chart_style|0.0762 [0.0749, 0.0786]|

|请求|执行/SQL次数|新增结果表指纹|采样RSS峰值MiB 中位数 [最小, 最大]|
|---|---|---:|---:|
|distribution|workflow 1 / exploration 1 / SQL 2|5|576.05 [575.79, 578.47]|
|grouped|workflow 1 / exploration 1 / SQL 2|6|578.23 [576.44, 580.63]|
|pivot|workflow 1 / exploration 1 / SQL 4|6|578.14 [576.38, 578.52]|

各探索请求源表重新指纹0、导出0，同步探针任务提交0；进入探索、调整视图、查看图表和换图型的SQL/统计/加载/画像/完整指纹/导出均0。真实异步提交和晚到保护另见应用测试与浏览器报告。

## 原始记录与复测

原始记录保留在 `reports/workbench/baseline-ui-v2`、`after-ui`、`after-exploration`；每次JSON含阶段计时、函数调用次数、函数累积耗时、结果参考和RSS样本统计。汇总为 `reports/workbench/performance-comparison.json`。旧 `baseline-ui` 初试未翻到实际第2页，保留供追溯，正式对比使用v2。独立核心探针记录 `baseline-core-20260929T111809034862Z` 与 `after-core-20260929T114706359151Z`，其样本描述参数rows=100000不是生成器实际交易行数，实际表规模以上表及JSON为准。

以下命令已经实际执行；重跑必须改成新的输出目录名，脚本拒绝覆盖旧产物。先停止其他CPU密集验证。

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe scripts/benchmark_workbench.py --source-root reports/workbench/baseline-source/insightpilot-agent --output-dir reports/workbench/baseline-ui-v2 --repeat 3
.\.venv\Scripts\python.exe scripts/benchmark_workbench.py --output-dir reports/workbench/after-ui --repeat 3
.\.venv\Scripts\python.exe scripts/benchmark_exploration_ui.py --output-dir reports/workbench/after-exploration --repeat 3
```

AppTest中expander事件适配仅补足Streamlit 1.63测试树未暴露的展开状态，不替换业务结果；浏览器测试另用原生操作。正式数值不混用并行pytest期间的浏览器动作时延；浏览器时延只用于定位交互问题。
