# 引导式分析修复验收（0.1.0）

验收日期：2026-09-29。本轮保持版本0.1.0，仅增量修改推荐、适配预检、状态与错误恢复、统一工作台；没有更换统计方法或重建平台。实际完整规则文件位于上一级 `GUIDED_ANALYSIS_SPEC.md.md`。下文所有成绩来自本轮本机运行，历史报告数字不计入。

## 1. 修改前备份与环境

修改前使用既有白名单快照工具保存315个源码文件（包含未提交源码）：

`D:\InsightPilot Agent\recovery-backups\insightpilot-agent-0.1.0-source-20260929T065135883435Z.zip`

SHA256：`63db1d026603488755edf50f26cb3bde6f7da8e2e9d0fd6a0ecfaa129ab0fda6`。已核验ZIP成员与文件哈希后解压到 `reports/guided/source-before-20260929T065135883435Z/insightpilot-agent` 作本轮对照。此目录与最初只读恢复基线 `source-original` 的用途不同。快照排除报告、环境、上传数据、数据库、凭据和旧.git，不覆盖旧备份。

Windows11 26100、Ryzen9 9900X（12物理核/24逻辑核）、31.65GiB内存，Python3.14.7；Streamlit1.63.0、pandas3.0.5、NumPy2.5.3、DuckDB1.5.5、SQLGlot30.18.0、pypdf6.19.0、pytest9.1.1。全部锁定依赖见 requirements-lock.txt，原始记录见 reports/guided/baseline-environment.json。没有为本轮添加在线模型或云端依赖。

只读恢复基线222个源码文件哈希、main `2532e4665eda9fe16dee98994691a3e6ddbec0e8`、6个标签及干净状态均保持不变；工作项目没有复制旧.git。证据：reports/guided/source-integrity-final.json。没有自动暂存、提交、打标签、推送、修改remote或上传数据。

## 2. 截图故障的实际原因

在修改前源码上复现 standard交易、问题“昨日订单量为什么下降？”、目标指标波动诊断、手动/残留因果探索、仅 treatment/control 组值的组合。

- 映射中的 outcome_column 已是 orders，真实缺口是 treatment_column；组值不能代替分组字段。空控制变量不是本次原始错误，旧执行器会复用维度。
- 原始底层校验正确阻断，分析SQL和因果统计调用为0。但旧Planner预检仍是 ready，随后进入一次workflow并在剧本校验阶段变成FAILED，界面只展示笼统失败和再次尝试，未在提交前揭示缺口。
- 同一个请求还存在方法与目标不匹配：订单变化诊断需要描述性比较/漏斗/维度变化，不能仅因“为什么”就使用因果推断。

|选择来源调查|本轮证据|
|---|---|
|新会话默认/注册表排序|修改前实测默认是 `__legacy__` 原自动工作流，不是因果。因果虽在注册表排序靠前，但不是页面首个默认项。|
|残留session|注入旧因果配置可保持该选择并复现截图失败。证明这是一条可能路径，不能证明用户当时确实如此。|
|示例按钮|旧示例按钮会恢复原自动工作流；新按钮明确原子清理旧专属参数并恢复自动推荐。|
|历史恢复、widget key复用、先前手动操作|仅凭截图无法恢复当时操作顺序；用户实际选中因果的来源未确认，未编造唯一根因。|

证据：reports/guided/before-reproduction.json、before-browser-final/checks.json及截图。修改前全量基线为524 passed、1 skipped。第一次基线运行受到editable安装路径影响，两个CLI子进程读到了当前源码；该次结果保留于before-pytest.log/xml，不作有效基线。隔离导入路径后结果为before-pytest-isolated.log/xml。

## 3. 本轮实现与状态契约

复用现有Planner、PlaybookRegistry、requirements、ColumnMapping、SemanticCatalog、PreparedDataset与原预检。统一 `analysis_advisor` 由UI/CLI/workflow共享，分别输出requested/recommended/effective方法、选择来源、问题适配、数据可用性、中文原因码、真实缺口、必要澄清和修复动作。原自动工作流仍是合法推荐目标，没有新增平行剧本目录。

推荐规则按问题含义与当前已确认数据判断：订单下降优先原指标诊断；趋势要求日期与有效观察范围；静态维度构成与跨期变化贡献区分；明确实验、控制调整关联、留存、数据质量及周期比较使用相应既有方法。手动方法不合适时不偷偷替换。未来预测、因果证明和超出已实现目标明确拒绝；规则不是通用语言理解，匹配不是置信度。

新会话 `automatic`；手动选择 `user_selected`；示例 `example_applied`；历史 `history_restored`；旧会话来源不明时 `legacy_unconfirmed`，需要明确保留或恢复推荐。方法使用稳定ID，不以排序位置代表。切换数据、映射、方法、有效参数使建议/口径/审批失效；预览表与真正分析范围分离。

|情况|预检与实际动作|
|---|---|
|当前交易订单诊断|ready；明确开始后执行一次。|
|缺实际处理字段/组值不存在/结果全空/独立单位或方向未明确|needs_clarification；显示待补充及真实缺口；不创建分析任务。|
|参数格式或取值不合法|invalid_input；指出具体参数。|
|预测未来、要求证明因果或现有引擎未支持的目标|unsupported；不会退化为无关画像再标PASS。|
|真实引擎异常|运行FAILED并显示脱敏具体原因；与预检状态区分。|
|待审批|保留既有审批契约；ready不是审批授权。|

数据准备阶段建立精确、受预算限制的日期/有限组值/有效数值摘要；建议只读取元数据，不重复扫描原DataFrame。没有抽样替代统计、静默截断或临时磁盘缓存。提交参数表单后才收到新值；开始执行前重新预检冻结请求并核对fingerprint。UI/workflow同快照指纹一致；CLI独立数据快照身份不同，指纹可以不同但方法及原因必须一致。

首页改为单一工作台：数据摘要、一个问题、三个适配示例、建议和状态、一个主要开始按钮。目标、后端、手动方法、重算和专属参数移入高级入口。结果为结论/图表/明细/报告；技术详情、质量、历史按需展开。旧模式枚举保留内部兼容，技术数据没有删除。使用说明见 analysis_guidance.md、ui_simplification.md。

## 4. 实测回归与数值一致性

最终全量pytest：**609 passed，1 skipped，0失败/错误**，耗时174.41秒。证据：reports/guided/verification-final/20260929T074811013657Z/pytest.xml。唯一skip是默认环境未安装LangGraph；在既有 .venv-langgraph 环境已实际补跑 `test_real_langgraph_propagates_worker_context_and_cancellation`，1 passed。真实三Demo LangGraph与规则数值表一致，预览0查询（langgraph-final.json）；有效/阻断方法另见core-langgraph.json。

|评估套件|PASS|WARN|FAIL|
|---|---:|---:|---:|
|core|5|0|0|
|safety|4|0|0|
|determinism|2|0|0|
|task|51|0|0|

任务评估保留原29项独立预期，并增加22个引导案例，共51项、16类。没有自动更新基线或使用被测实现生成expected。

|任务类别|通过/总数|
|---|---:|
|不可比单位/口径|2/2|
|六类导出绑定|2/2|
|加权比率与均值比率|3/3|
|去重人数与行数|3/3|
|安全作用域与危险分支|2/2|
|实验单位/方向/区间|3/3|
|引导契约：身份与轻量预检|2/2|
|引导执行：独立小表数值|2/2|
|引导推荐：目标与表达边界|7/7|
|引导预检：字段与真实取值|11/11|
|维度分支与窗口对比|2/2|
|缓存失效与历史不可变|3/3|
|订单口径与净/毛收入|3/3|
|转化率澄清|2/2|
|连接放大与跨事实边界|2/2|
|释放与分支归属|2/2|

39个原示例与8个中文同义/否定改写均实际COMPLETED，方法符合预期；4个边界请求为2个UNSUPPORTED和2个NEEDS_INPUT，零查询。详细逐例方法与状态见reports/guided/guided-cases-final.json，不是只检查进程exit0。独立有效因果小表实际naive与调整差均为2；独立用户实验每组2人、差2、p=0.29289321881345254，未把重复行当样本。原三个Demo CLI各实际完成PDF、Markdown、HTML、Excel、manifest、ZIP六种导出。

十剧本在相同输入指纹的小表上运行，55张结果表、样本量、极小p-value、结构化结论与证据完整比较：数值/证据差异0、presentation差异0。严格payload比较仍有65处新增映射来源/预检说明等元数据差异，因此严格比较脚本返回1；不能称payload完全相同。原始差异保留于reports/guided/playbook-comparison-final-frozen.json。独立统计正确性由core及task小表另行验证，前后相等本身不是正确性证明。

本轮首个全量检查564 passed、10 failed、1 skipped的记录没有覆盖。失败涉及旧三模式展示契约、单日趋势/手造metadata旧fixture、真实异步spy拼写、入口映射来源指纹。分别修复或明确迁移；保留去重人数、净收入公式、无虚构结果、安全和证据断言，额外加入单日观察不足反例。实际运行README命令还发现CLI虚拟auto/legacy参数处理遗漏及默认参数泄漏，均先保留红测再修复。另外真实复现了变化贡献误用全期静态占比，修复后独立小表A=-20、B=0；手动选择静态方法不能冒充变化贡献。自动分支比较过去只记auto，可能错误把不同实际方法相减；现绑定成功运行的实际方法，不同或未知方法明确不可比（auto-method-comparison-final.xml）。两项均只改路由/契约，没有改统计算法。最终全量结果以上表为准。

## 5. 实际点击、视觉与零执行门禁

AppTest交互、真实浏览器视觉和health分别记录。AppTest使用测试专属Expander适配器补传本机Streamlit1.63尚未发送的布尔展开状态；不修改产品门禁、不伪造开始操作。浏览器使用独立Chrome153.0.8010.53会话，真实鼠标/键盘操作，无用户浏览器资料或session_state注入。原浏览器工具受本机1385启动错误限制，使用已安装Playwright控制隔离Chrome；无远程平台安装或安全配置修改。

真实浏览器19项通过，health=200，page_errors=0；本机截图已实际查看：

![新会话统一工作台](../reports/guided/browser-final-verified/fresh.png)

![错误因果配置：具体缺口、修复按钮及禁用开始](../reports/guided/browser-final-verified/blocked.png)

![接受推荐并明确执行后的实际结果](../reports/guided/browser-final-verified/completed.png)

口径卡computed style标题16px=12pt、正文14px=10.5pt。新会话默认问题可直接一次点击开始；采用一个常用示例需要示例+开始两次点击；截图错误状态修复为改用推荐+开始两次点击（不计此前展开/选择错误方法的诊断操作）。接受推荐本身不执行。PDF/Excel/ZIP均真实生成、下载、读回；ZIP内PDF与单独下载PDF字节一致（browser-final-verified/checks.json）。浏览器按钮返回时间包含服务端重跑和绘制，后台提交返回时间不是分析完成耗时。

|门禁检查|实际调用|
|---|---|
|已加载数据后切到错误方法、编辑问题、展开全部方法、接受推荐|后台submit=0，workflow=0，SQL=0，统计=0，导出=0；没有新增历史。|
|对禁用按钮进行单独标注的伪客户端提交测试|服务端仍阻断，以上调用为0；原生AppTest disabled click本身也拒绝。|
|接受推荐后明确开始|submit=1、workflow=1、实际7张结果表、未请求导出=0。|
|切页、重复相同请求|分析=0、完整源表哈希=0、重新加载=0。|

证据：entry-guards-final.xml、entry-guards-async.json、entry-guards-three-interfaces.json，以及最终全量pytest。SQL外层run_sql与其内层run_parameterized_sql是同一条调用链，不能相加成两条分析查询。

复用原受限后台任务，没有新框架或增加并发。真实大型数据六项检查均通过：准备时展开设置0.203秒、取消响应0.306秒、分析提交返回0.398秒、分析中释放0.344秒；大切小不采纳旧数据、取消不自动重启、明确刷新可恢复、晚到结果被丢弃。证据background-browser-final-20260929/checks.json。进度来自实际阶段，无虚构百分比。取消是协作式，当前原生统计/解析/SQL调用结束后才响应，不能强杀线程或承诺立即回收操作系统RSS。

## 6. 同机三次性能对照

数据固定transaction/standard、seed42：users20000×7、merchants3000×3、daily_metrics36000×39、transaction_detail316035×27、orders316035×27、traffic_events36000×19；相同数据指纹、相同字段维度，没有缩小数据。before/after各3个独立Python进程，中位数及[min,max]，单位秒。测试进程错开运行；不是压力测试，也不声称P95或其他机器固定耗时。

界面基准用同步AppTest隔离服务端渲染成本，包含实际控件渲染但不包含Chrome网络/绘制；后台浏览器响应另列。

|操作|补丁前|补丁后|
|---|---:|---:|
|首页数据就绪（含准备/渲染）|1.702 [1.683, 1.755]|1.990 [1.981, 2.013]|
|改问题并更新建议（含页面重绘）|0.042 [0.042, 0.047]|0.035 [0.035, 0.036]|
|数据就绪后首次分析（含渲染）|0.749 [0.735, 0.786]|0.721 [0.717, 0.725]|
|相同请求热复用（含渲染）|0.044 [0.044, 0.044]|0.035 [0.034, 0.035]|
|切到明细|0.052 [0.049, 0.053]|0.041 [0.039, 0.041]|
|切回结论|0.045 [0.042, 0.047]|0.034 [0.032, 0.035]|
|切到报告|0.041 [0.040, 0.042]|0.030 [0.030, 0.030]|
|单PDF|0.353 [0.347, 0.354]|0.345 [0.345, 0.349]|
|单Excel|0.308 [0.296, 0.521]|0.307 [0.301, 0.310]|
|ZIP（已生成PDF/Excel）|0.576 [0.543, 1.005]|0.590 [0.588, 0.596]|

后端独立测量（与界面表不可混算）：

|阶段|补丁前|补丁后|
|---|---:|---:|
|数据生成/加载|0.193 [0.192, 0.200]|0.200 [0.191, 0.210]|
|所有源表准备|0.972 [0.971, 1.076]|1.347 [1.345, 1.351]|
|首次后端分析|0.666 [0.658, 0.684]|0.673 [0.664, 0.675]|
|按需图表构建|0.147 [0.143, 0.156]|0.144 [0.143, 0.146]|
|图表序列化|0.004 [0.004, 0.005]|0.004 [0.004, 0.005]|
|PDF|0.254 [0.253, 0.254]|0.265 [0.256, 0.267]|
|Markdown|0.036 [0.036, 0.037]|0.039 [0.039, 0.040]|
|HTML|0.255 [0.253, 0.260]|0.261 [0.259, 0.264]|
|Excel|0.304 [0.302, 0.313]|0.309 [0.302, 0.316]|
|运行清单JSON|0.003 [0.003, 0.003]|0.004 [0.004, 0.004]|
|ZIP组包|0.065 [0.064, 0.065]|0.064 [0.064, 0.065]|
|冷ZIP全部组成格式加组包|0.921 [0.913, 0.926]|0.942 [0.929, 0.951]|

后端热复用仅为缓存lookup（微秒级），不等于重新计算。冷ZIP总耗时是本次各组成格式与组包实测相加；界面warm ZIP复用已生成PDF/Excel，二者不可混称。

精确适配摘要增加一次性准备成本。首次实现标准数据摘要约3.517秒，测出重复字符串转换后改为对不同值解析并复用有效组计数，仍是全量精确检查；正式三次摘要约0.392秒。首次分析基本持平，轻量交互下降；数据准备和部分ZIP耗时增加，未宣称全面提速。原慢项仍包括完整指纹（约0.72秒）、准备阶段画像/有效性检查（约0.59秒，含摘要）、分析结果构建（约0.46秒）；嵌套trace时段不能相加为总耗时。

RSS使用20ms Windows进程工作集采样，并保存OS lifetime PeakWorkingSetSize作补充，包含原生库内存，不用tracemalloc冒充RSS。界面采样峰值中位数 566.76→571.56MiB，范围563.28–567.38→571.14–572.07MiB。后端峰值中位数 561.39→564.08MiB。OS峰值可能高于采样峰值；三次测量不足以推断长时间泄漏或严格内存上限。

数据预算1GiB、结果总预算256MiB（历史预留512KiB、最多10节点）、导出64MiB均不增加；完整历史大结果仍受原预算控制，没有每节点复制DataFrame。新增metadata也计入预算。全局最多2任务、每会话1任务不变。预算约束保留对象，不是进程RSS硬上限。正式每轮首次数据加载1次、schema/完整哈希各6次；改问题、切页、接受推荐均不增加分析或全表指纹。新预检在提交前增加一次轻量身份复核，不是分析调用；首次仍只有1次workflow。报告生成前导出调用0。

原始记录：reports/guided/before-ui、after-ui-final、before-session-20260929T065831851734Z、after-session-final-20260929T075222536052Z；performance-comparison-final.json逐值比对3组共21张结果表无差异。各函数次数/耗时、阶段RSS、明细字段基数和所有范围保留JSON，未仅挑最快的一次。

## 7. 分发、恢复与限制

新wheel仍为0.1.0，SHA256：`1529d73baf57c7ae5da5bfe846252e2aa54b786d2cd0d9061f45f289cca82376`。对全部141个包内模块/页面/YAML资产核验无遗漏；在项目外新venv从现有本地wheelhouse安装锁定依赖并安装指定wheel，site-packages导入、pip check、语义校验、51项task契约通过。记录位于 `D:\InsightPilot Agent\recovery-backups\guided-wheel-validation-final\validation.json`，不会把旧同版本wheel当作新构建。

冻结代码快照已在 `D:\InsightPilot Agent\recovery-backups\guided-source-restore-final` 建立新venv并完成独立全量复测：609 passed、1 skipped；四套评估和三个Demo六类导出通过。该目录validation.json与verification保留确切ZIP、SHA256、安装和复测记录。最终交付前仅校订本验收文档的状态用语及恢复记录；最终ZIP再安全解包至 `D:\InsightPilot Agent\recovery-backups\guided-source-restore-delivery`，复用本轮新建的隔离环境重新安装，核对除本文外所有源码与完整复测版本一致，并执行引导UI、CLI、零执行预检和PDF关键恢复检查。最终快照、恢复命令与两轮证据统一记录于reports/guided/final-delivery.json。全部使用本地离线wheelhouse，不依赖旧账号、旧.git或工作项目虚拟环境；不覆盖原有快照，运行报告不放进源码ZIP。

P0功能与本机验收完成；已知边界：

- 推荐是有限中文规则，不支持任意复杂自然语言、多目标DAG、预测或因果证明。来源阅读范围及未核实内容见guided_references.md；未复制外部平台代码。
- 精确摘要只保留最多100个候选组值；高基数字段或未准备的联合有效值摘要会保守要求补充，不静默通过。数字0/1自定义字段在明确映射后可用，任意二分类字段不会自动获实验语义。
- 随机化、独立性、无混杂不是有字段就成立；部分联合单位/统计前提仍由执行阶段的既有统计门禁检查。没有伪称所有统计前提已验证。
- 数据准备新增精确检查有成本；仍保留原完整哈希和质量扫描。导出在用户请求时仍同步生成，大报告可能暂时占用该会话；本轮未新增后台导出平台。
- DuckDB/SQLite之外方言继续明确拒绝。未验证其他操作系统/浏览器、无限数据规模或多人长期压力，不把本机通过外推为通用保证。
- 桌面浏览器工具1385限制仍存在；真实Chrome替代路径已验证。停止本轮测试服务后，用户按下列命令启动即可。

## 8. 本机已执行命令

以下从 `D:\InsightPilot Agent\insightpilot-agent` 的PowerShell执行。输出目录中的示例名称代表本轮实际路径；重复运行会保护已有结果，需使用新的目录名。完整参数和退出码还保存在各验证results.json/validation.json。

```powershell
$env:PYTHONUTF8='1'
& ./.venv/Scripts/python.exe -m streamlit run app/ui_streamlit.py --server.headless true --server.address 127.0.0.1 --server.port 8508 --server.fileWatcherType none --browser.gatherUsageStats false
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario transaction --scale standard --question '昨日订单量为什么下降？' --playbook auto --advise-only --output-format json
& ./.venv/Scripts/python.exe -m insightpilot.cli --scenario transaction --scale standard --question '昨日订单量为什么下降？' --playbook auto --output-format json
& ./.venv/Scripts/python.exe scripts/verify_project.py --output-dir reports/guided/verification-final
& ./.venv/Scripts/python.exe scripts/check_guided_cases.py --examples --scale standard --output reports/guided/guided-cases-final.json
& ./.venv/Scripts/python.exe scripts/check_guided_browser.py --url http://127.0.0.1:8508 --output reports/guided/browser-final-verified
& ./.venv/Scripts/python.exe scripts/benchmark_guided_ui.py --output-dir reports/guided/after-ui-final --repeat 3
& ./.venv/Scripts/python.exe scripts/benchmark_performance.py --output-dir reports/guided --label after-session-final --case transaction --rows 0 --session-path --repeat 3
& ./.venv-langgraph/Scripts/python.exe scripts/check_langgraph.py --output reports/guided/langgraph-final.json
& ./.venv-langgraph/Scripts/python.exe -m pytest tests/test_performance_task_core.py::test_real_langgraph_propagates_worker_context_and_cancellation --junitxml=reports/guided/langgraph-cancellation-final.xml
& ./.venv/Scripts/python.exe -m build --no-isolation --wheel --outdir ../recovery-backups/guided-wheel-final
& ./.venv/Scripts/python.exe scripts/check_distribution.py --wheel ../recovery-backups/guided-wheel-final/insightpilot_agent-0.1.0-py3-none-any.whl --work-dir ../recovery-backups/guided-wheel-validation-final --wheelhouse ../recovery-backups/wheelhouse-python314-win64 --wheelhouse ../recovery-backups/upstream-dependencies-20260923T125309977613Z
& ./.venv/Scripts/python.exe scripts/export_source_snapshot.py --output-dir ../recovery-backups
```

最终快照恢复的完整实际命令与确切ZIP名保存在 `reports/guided/final-delivery.json`，也写入恢复目录validation.json；不使用模糊的“最新ZIP”替代校验后的确切文件。verify_project内实际执行了pytest、pip check、语义校验、四套evaluation及三Demo CLI六导出。

## 9. 实际源码文件清单

对本轮修改前白名单源码比较：修改37个、新增16个、删除0个。对应逐文件前后SHA256见reports/guided/change-inventory-final.json；源码ZIP另带SHA256SUMS.json。不包含运行报告、数据或环境文件。

- `AGENTS.md`
- `README.md`
- `app/components/data_source_panel.py`
- `app/components/history_panel.py`
- `app/components/mapping_panel.py`
- `app/components/metric_definition_panel.py`
- `app/components/question_panel.py`
- `app/components/result_panel.py`
- `app/components/semantic_panel.py`
- `app/components/sidebar.py`
- `app/ui_streamlit.py`
- `insightpilot/agents/dataset.py`
- `insightpilot/agents/workflow.py`
- `insightpilot/analysis/threads.py`
- `insightpilot/cli.py`
- `insightpilot/evaluation/task_suite.py`
- `insightpilot/planning/planner.py`
- `insightpilot/reports/manifest.py`
- `scripts/check_browser_background.py`
- `scripts/compare_playbook_snapshots.py`
- `tests/conftest.py`
- `tests/test_chinese_labels.py`
- `tests/test_metric_ui_confirmation.py`
- `tests/test_performance_background_ui.py`
- `tests/test_performance_core.py`
- `tests/test_performance_ui.py`
- `tests/test_rebuild_engine.py`
- `tests/test_rebuild_export_ui.py`
- `tests/test_streamlit_demo_mode.py`
- `tests/test_streamlit_developer_mode.py`
- `tests/test_streamlit_professional_mode.py`
- `tests/test_streamlit_result_details.py`
- `tests/test_upstream_definitions_clarification.py`
- `tests/test_upstream_task_evaluation.py`
- `tests/test_upstream_threads.py`
- `tests/test_upstream_ui.py`
- `tests/test_workflow_column_mapping.py`
- `app/components/guidance_panel.py`
- `docs/analysis_guidance.md`
- `docs/guided_analysis_acceptance.md`
- `docs/guided_references.md`
- `docs/ui_simplification.md`
- `insightpilot/evaluation/guided_suite.py`
- `insightpilot/planning/analysis_advisor.py`
- `scripts/benchmark_guided_ui.py`
- `scripts/check_guided_browser.py`
- `scripts/check_guided_cases.py`
- `tests/test_guided_advisor.py`
- `tests/test_guided_cases.py`
- `tests/test_guided_cli.py`
- `tests/test_guided_entry_guards.py`
- `tests/test_guided_ui.py`
- `tests/ui_expander_support.py`
