# 性能优化前基线

本页在修改产品执行代码之前完成。版本0.1.0；源码备份为外层recovery-backups/insightpilot-agent-0.1.0-source-20260907T090942312118Z.zip，SHA256 098bfea82d1a5d522d307c34d14b1dae4c88b6b547c141d7ab8c6a0120154388。原始source-original保持只读。

## 测量方法与环境

本机AMD Ryzen 9 9900X，12物理核/24逻辑核，33,984,663,552字节物理内存。Python3.14.7；pandas3.0.5、numpy2.5.3、DuckDB1.5.5、Streamlit1.63.0、Plotly7.0.0、ReportLab5.0.1。

标准三场景和固定seed42的10万/50万/100万行10列模拟表，各3个顺序新进程。计时为perf_counter，冷进程导入/加载/首次分析与同进程强制重复分析分开；此时尚无分析命中缓存。以下为3次中位数，不宣称P95。函数计时为inclusive，不与重叠节点相加。真实SQL计数来自AnalyticsEngine.run_parameterized_sql，trace操作记录另计。

RSS使用Windows GetProcessMemoryInfo WorkingSetSize每20ms采样，同时记录OS进程生存期PeakWorkingSetSize，包含原生扩展内存；DataFrame.memory_usage(deep=True)是数据对象估计，不能替代进程RSS。首轮baseline-20260907T091818299751Z存在采样句柄错误，其RSS=0无效，已保留错误并完整重测；本页只使用baseline-valid-20260907T092715031540Z。

| 数据 | 加载s | 首次分析s | 同进程重算s | PDF s | Excel s | ZIP完整准备s | 采样峰值MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
|transaction|0.2064|4.3352|4.2077|0.3108|0.3236|0.9626|701.2|
|content|0.1144|1.0138|0.9700|0.0757|0.2395|0.4546|407.5|
|live|0.1640|1.4404|1.4013|0.1850|0.2683|0.6890|359.4|
|100000行|0.0509|0.2668|0.2516|0.0785|0.2400|0.3675|286.8|
|500000行|0.2420|1.0213|1.0365|0.0810|0.2441|0.3740|403.8|
|1000000行|0.4752|1.9798|1.9374|0.0797|0.2417|0.3719|564.6|

ZIP完整准备为分别实测PDF/Markdown/HTML/Excel/Manifest加ZIP装配的总和；ZIP装配另有原始计时。它不冒充点击ZIP后跨格式缓存命中耗时。全部18个进程退出0，原始每次范围、行列数、字符串列占比、维度基数、结果行数、图表点数/JSON字节、导出字节在reports/performance/baseline-valid-20260907T092715031540Z/。

## 浏览器与重复交互

独立Chrome上下文三次，服务端为相同已启动服务，不能叫新Python进程冷启动。按实际ForwardMsg.script_finished事件、Streamlit空闲和随后两个animation frame计时；WebSocket统计为应用负载字节，不是HTTP压缩传输字节。完整记录baseline-browser-valid/standard.json。前一次控件定位错误已保留，未用于下表。

| 操作 | 中位s | 范围s |
|---|---:|---:|
|initial_navigation|1.9911|1.8390–2.5187|
|professional_mode|1.3967|1.3807–1.4309|
|analysis_first|6.2842|6.1679–6.3886|
|prepare_all_exports|2.3961|2.3800–2.3978|
|analysis_repeat|5.6706|5.6006–5.6850|
|visual_tab|1.3135|1.3123–1.3614|
|overview_tab|1.3135|1.2960–1.3462|
|export_tab|1.3302|1.3129–1.3307|
|demo_mode|1.3627|1.3127–1.3964|
|results_tab|1.5134|1.4978–1.5471|
|pdf_download|0.1805|0.1719–0.2143|

AppTest实际56步0异常：纯切页/模式/下载分析调用增量为0，但每次仍6表指纹、8个隐藏图表构建，结果明细全量传输；CSV/Excel每轮重新解析。未请求PDF/HTML/Excel/ZIP时这些导出器为0，但工作流已自动生成Markdown；点击准备导出一次性执行全部格式。详见baseline-ui/README.md及计数JSON。

## 已测热点和P0目标

标准交易主链路最慢成本为重复完整指纹、表注册/类型转换、结果构建与图表。首次交易的函数计时见原始JSON；画像/质量被重复调用，不能把整个等待归因于统计检验。百万行自定义表和标准交易的路径不同，行数不能代替工作量。

修复顺序：会话单数据引用与精确revision/指纹复用；显式分析提交和上次结果复用；动态容器条件渲染/分页；单格式导出与预算；消除已测重复画像/扫描/复制。保留全量统计、SQL/Join/审批与原测试意图。P0完成后再测首次等待和UI响应，仅在仍有明显持续阻塞时增加受限后台任务。

## 复测命令

```powershell
Set-Location 'D:\InsightPilot Agent\insightpilot-agent'
& ./.venv/Scripts/python.exe scripts/benchmark_performance.py --label baseline-repeat --repeat 3
& ./.venv/Scripts/python.exe scripts/benchmark_browser.py --url http://127.0.0.1:8503 --output reports/performance/browser-repeat/standard.json
```

基准仅生成模拟数据，保存统计与小型聚合参考结果；不读取用户输入、不启用数据磁盘缓存。首次RSS采样错误和浏览器定位错误属于探针错误，已修正，不被当作产品性能或功能失败。

## 文件摄入补充基线

为避免实现期间源码变化影响基线，此项从优化前SHA256快照解压的独立source-before目录导入原读取器，使用相同已安装依赖。固定seed模拟内容仅在BytesIO中构造；CSV100,000行×10列、Excel选定工作表20,000行×10列（另有50行参考sheet），每种3次。CSV解析中位0.0814秒；Excel解析0.8330秒，sheet名称读取另计。原始范围、注册画像、精确指纹与导入文件路径见reports/performance/baseline-ingestion.json。生成输入的时间未混入解析时间。
